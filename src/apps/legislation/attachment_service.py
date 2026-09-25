"""Secure, session-bound temporary document attachments for the chat.

Metadata is persisted in the operational database while original bytes and
extracted text are stored behind a pluggable local/S3-compatible backend.
"""

from __future__ import annotations

import hashlib
import os
import re
import secrets
import subprocess
import sys
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.attachment_storage import get_attachment_storage, sha256_file
from src.apps.operations.models import AttachmentRecord

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".json", ".docx"}
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_FILES = 5
DEFAULT_TTL_SECONDS = 2 * 60 * 60


class AttachmentError(ValueError):
    pass


def _session_hash(request) -> str:
    if not request.session.session_key:
        request.session.save()
    return hashlib.sha256(request.session.session_key.encode("utf-8")).hexdigest()


def _safe_filename(name: str) -> str:
    candidate = SAFE_NAME_RE.sub("_", os.path.basename(name or "document"))
    return candidate[:120] or "document"


def _extract_text(path: Path, suffix: str) -> str:
    worker = Path(__file__).resolve().parents[2] / "processing" / "attachment_worker.py"
    try:
        result = subprocess.run(
            [sys.executable, str(worker), str(path.resolve())],
            capture_output=True,
            timeout=20,
            check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise AttachmentError(
            "Não foi possível processar o documento dentro dos limites permitidos."
        ) from exc
    return result.stdout.decode("utf-8")[:60_000]


def _validate_file_signature(path: Path, suffix: str) -> None:
    """Reject renamed binaries before handing them to document parsers."""
    with path.open("rb") as source:
        header = source.read(8)
    if suffix == ".pdf" and not header.startswith(b"%PDF-"):
        raise AttachmentError("O conteúdo não corresponde a um PDF válido.")
    if suffix == ".docx" and header[:2] != b"PK":
        raise AttachmentError("O conteúdo não corresponde a um DOCX válido.")
    if suffix in {".txt", ".md", ".csv", ".json"} and b"\x00" in header:
        raise AttachmentError("Arquivo de texto inválido.")


def _cleanup_queryset(session_hash: str | None = None, now=None) -> int:
    now = now or timezone.now()
    qs = AttachmentRecord.objects.all()
    if session_hash:
        qs = qs.filter(session_hash=session_hash)
    expired = qs.filter(expires_at__lte=now)
    storage = get_attachment_storage()
    removed = 0
    for record in expired:
        for key in (record.storage_key, record.text_storage_key):
            try:
                storage.delete(key)
            except Exception:
                pass
        record.delete()
        removed += 1
    return removed


def cleanup_expired_attachments(now=None) -> int:
    return _cleanup_queryset(None, now=now)


def cleanup_request_attachments(request, now=None) -> int:
    return _cleanup_queryset(_session_hash(request), now=now)


def list_attachments(request) -> list[dict[str, object]]:
    cleanup_request_attachments(request)
    return [
        {
            "id": item.id,
            "name": item.name,
            "size": item.size,
            "content_type": item.content_type,
            "created_at": item.created_at.timestamp(),
        }
        for item in AttachmentRecord.objects.filter(session_hash=_session_hash(request)).order_by(
            "created_at"
        )
    ]


def upload_attachment(request, upload: UploadedFile) -> dict[str, object]:
    cleanup_request_attachments(request)
    session_hash = _session_hash(request)
    max_files = int(getattr(settings, "JURIX_ATTACHMENT_MAX_FILES", DEFAULT_MAX_FILES))
    max_bytes = int(getattr(settings, "JURIX_ATTACHMENT_MAX_BYTES", DEFAULT_MAX_BYTES))
    if AttachmentRecord.objects.filter(session_hash=session_hash).count() >= max_files:
        raise AttachmentError(f"Máximo de {max_files} documentos por sessão.")
    original = upload.name or "document"
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AttachmentError("Formato não suportado. Use PDF, TXT, MD, CSV, JSON ou DOCX.")
    size = int(getattr(upload, "size", 0) or 0)
    if size <= 0 or size > max_bytes:
        raise AttachmentError(f"Arquivo inválido ou maior que {max_bytes // (1024 * 1024)} MB.")

    staging_dir = Path(
        getattr(
            settings,
            "JURIX_ATTACHMENT_STAGING_DIR",
            Path(settings.BASE_DIR) / "data" / "attachment-staging",
        )
    )
    staging_dir.mkdir(parents=True, exist_ok=True)
    attachment_id = secrets.token_urlsafe(12)
    stage = staging_dir / f"{attachment_id}{suffix}"
    storage_key = f"chat/{session_hash}/{attachment_id}{suffix}"
    text_storage_key = f"{storage_key}.txt"
    written = 0
    stored = False
    try:
        with stage.open("wb") as target:
            for chunk in upload.chunks():
                written += len(chunk)
                if written > max_bytes:
                    raise AttachmentError("Arquivo excede o limite permitido.")
                target.write(chunk)
        _validate_file_signature(stage, suffix)
        text = _extract_text(stage, suffix).strip()
        if not text:
            raise AttachmentError("Não foi possível extrair texto do documento.")
        storage = get_attachment_storage()
        content_type = getattr(upload, "content_type", None) or "application/octet-stream"
        storage.save_file(storage_key, stage, content_type)
        storage.save_bytes(
            text_storage_key,
            text[:60_000].encode("utf-8"),
            "text/plain; charset=utf-8",
        )
        stored = True
        created_at = timezone.now()
        expires_at = created_at + timedelta(
            seconds=int(getattr(settings, "JURIX_ATTACHMENT_TTL_SECONDS", DEFAULT_TTL_SECONDS))
        )
        with transaction.atomic():
            record = AttachmentRecord.objects.create(
                id=attachment_id,
                session_hash=session_hash,
                name=_safe_filename(original),
                size=written,
                content_type=content_type,
                storage_key=storage_key,
                text_storage_key=text_storage_key,
                sha256=sha256_file(stage),
                expires_at=expires_at,
            )
    except AttachmentError:
        from src.observability.metrics import ATTACHMENT_PROCESSING_FAILURES

        ATTACHMENT_PROCESSING_FAILURES.inc()
        raise
    except Exception as exc:
        from src.observability.metrics import ATTACHMENT_PROCESSING_FAILURES

        ATTACHMENT_PROCESSING_FAILURES.inc()
        if stored:
            try:
                storage = get_attachment_storage()
                storage.delete(storage_key)
                storage.delete(text_storage_key)
            except Exception:
                pass
        raise AttachmentError("Não foi possível armazenar o documento.") from exc
    finally:
        stage.unlink(missing_ok=True)

    return {
        "id": record.id,
        "name": record.name,
        "size": record.size,
        "content_type": record.content_type,
        "created_at": record.created_at.timestamp(),
    }


def delete_attachment(request, attachment_id: str) -> bool:
    record = AttachmentRecord.objects.filter(
        id=attachment_id, session_hash=_session_hash(request)
    ).first()
    if not record:
        return False
    storage = get_attachment_storage()
    for key in (record.storage_key, record.text_storage_key):
        try:
            storage.delete(key)
        except Exception:
            pass
    record.delete()
    return True


def get_attachment_texts(request, attachment_ids: list[str]) -> list[str]:
    cleanup_request_attachments(request)
    storage = get_attachment_storage()
    records = AttachmentRecord.objects.filter(
        session_hash=_session_hash(request),
        id__in={str(item) for item in attachment_ids},
    ).order_by("created_at")
    texts = []
    for item in records:
        try:
            text = (
                storage.read_bytes(item.text_storage_key).decode("utf-8", errors="replace").strip()
            )
        except Exception:
            continue
        if text:
            texts.append(text[:60_000])
    return texts
