"""Secure, session-bound temporary document attachments for the chat.

Attachments are deliberately not persisted as legislation. They live under
``DATA_DIR/chat_attachments/<session-key>/`` and are discoverable only by the
Django session that uploaded them. Metadata is stored in the signed Django
session cookie/session backend, so no new database table or migration is
required for the first implementation.
"""
from __future__ import annotations

import hashlib
import os
import re
import secrets
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from django.conf import settings
from django.core.files.uploadedfile import UploadedFile

SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")
ALLOWED_EXTENSIONS = {".pdf", ".txt", ".md", ".csv", ".json", ".docx"}
DEFAULT_MAX_BYTES = 10 * 1024 * 1024
DEFAULT_MAX_FILES = 5
DEFAULT_TTL_SECONDS = 2 * 60 * 60


class AttachmentError(ValueError):
    pass


def _root() -> Path:
    configured = getattr(settings, "JURIX_ATTACHMENT_ROOT", "") or ""
    if configured:
        root = Path(configured)
    else:
        data_dir = Path(getattr(settings, "DATA_DIR", Path(settings.BASE_DIR) / "data"))
        root = data_dir / "chat_attachments"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _session_dir(request) -> Path:
    if not request.session.session_key:
        request.session.save()
    digest = hashlib.sha256(request.session.session_key.encode("utf-8")).hexdigest()
    path = _root() / digest
    path.mkdir(parents=True, exist_ok=True)
    return path


def _meta(request) -> list[dict[str, Any]]:
    return list(request.session.get("jurix_attachments", []))


def _save_meta(request, values: list[dict[str, Any]]) -> None:
    request.session["jurix_attachments"] = values
    request.session.modified = True


def _safe_filename(name: str) -> str:
    candidate = SAFE_NAME_RE.sub("_", os.path.basename(name or "document"))
    return candidate[:120] or "document"


def _extract_text(path: Path, suffix: str) -> str:
    worker = Path(__file__).resolve().parents[2] / 'processing' / 'attachment_worker.py'
    try:
        result = subprocess.run(
            [sys.executable, str(worker), str(path.resolve())],
            capture_output=True, timeout=20, check=True,
            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0,
        )
    except (subprocess.TimeoutExpired, subprocess.CalledProcessError) as exc:
        raise AttachmentError('Não foi possível processar o documento dentro dos limites permitidos.') from exc
    return result.stdout.decode('utf-8')[:60_000]


def cleanup_expired_attachments(now: float | None = None) -> int:
    """Collect expired session files even when their owners never return."""
    cutoff = (time.time() if now is None else now) - DEFAULT_TTL_SECONDS
    root = _root().resolve()
    removed = 0
    for directory in root.iterdir():
        if directory.is_symlink() or not directory.is_dir() or not re.fullmatch(r'[a-f0-9]{64}', directory.name):
            continue
        for path in directory.iterdir():
            if path.is_symlink() or not path.is_file():
                continue
            if path.resolve().parent != directory.resolve():
                continue
            try:
                if path.stat().st_mtime < cutoff:
                    path.unlink()
                    removed += 1
            except FileNotFoundError:
                pass
        try:
            directory.rmdir()
        except OSError:
            pass
    return removed
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


def cleanup_request_attachments(request, now: float | None = None) -> int:
    now = now or time.time()
    values = _meta(request)
    kept: list[dict[str, Any]] = []
    removed = 0
    for item in values:
        if now - float(item.get("created_at", now)) <= DEFAULT_TTL_SECONDS:
            kept.append(item)
            continue
        for file_key in ("path", "text_path"):
            try:
                Path(item[file_key]).unlink(missing_ok=True)
            except (OSError, KeyError):
                pass
        removed += 1
    if removed:
        _save_meta(request, kept)
    return removed


def list_attachments(request) -> list[dict[str, Any]]:
    cleanup_request_attachments(request)
    return [
        {key: item[key] for key in ("id", "name", "size", "content_type", "created_at") if key in item}
        for item in _meta(request)
    ]


def upload_attachment(request, upload: UploadedFile) -> dict[str, Any]:
    cleanup_request_attachments(request)
    current = _meta(request)
    max_files = int(getattr(settings, "JURIX_ATTACHMENT_MAX_FILES", DEFAULT_MAX_FILES))
    max_bytes = int(getattr(settings, "JURIX_ATTACHMENT_MAX_BYTES", DEFAULT_MAX_BYTES))
    if len(current) >= max_files:
        raise AttachmentError(f"Máximo de {max_files} documentos por sessão.")
    original = upload.name or "document"
    suffix = Path(original).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise AttachmentError("Formato não suportado. Use PDF, TXT, MD, CSV, JSON ou DOCX.")
    size = int(getattr(upload, "size", 0) or 0)
    if size <= 0 or size > max_bytes:
        raise AttachmentError(f"Arquivo inválido ou maior que {max_bytes // (1024 * 1024)} MB.")

    attachment_id = secrets.token_urlsafe(12)
    safe_name = _safe_filename(original)
    path = _session_dir(request) / f"{attachment_id}{suffix}"
    written = 0
    with path.open("wb") as target:
        for chunk in upload.chunks():
            written += len(chunk)
            if written > max_bytes:
                path.unlink(missing_ok=True)
                raise AttachmentError("Arquivo excede o limite permitido.")
            target.write(chunk)

    try:
        _validate_file_signature(path, suffix)
        text = _extract_text(path, suffix).strip()
    except Exception:
        path.unlink(missing_ok=True)
        raise
    if not text:
        path.unlink(missing_ok=True)
        raise AttachmentError("Não foi possível extrair texto do documento.")

    text_path = path.with_suffix(path.suffix + ".txt")
    text_path.write_text(text[:60_000], encoding="utf-8")
    item = {
        "id": attachment_id,
        "name": safe_name,
        "size": written,
        "content_type": getattr(upload, "content_type", None) or "application/octet-stream",
        "created_at": time.time(),
        "path": str(path),
        "text_path": str(text_path),
    }
    current.append(item)
    _save_meta(request, current)
    return {key: item[key] for key in ("id", "name", "size", "content_type", "created_at")}


def delete_attachment(request, attachment_id: str) -> bool:
    values = _meta(request)
    found = None
    kept = []
    for item in values:
        if item.get("id") == attachment_id:
            found = item
        else:
            kept.append(item)
    if not found:
        return False
    for file_key in ("path", "text_path"):
        try:
            Path(found[file_key]).unlink(missing_ok=True)
        except (OSError, KeyError):
            pass
    _save_meta(request, kept)
    return True


def get_attachment_texts(request, attachment_ids: list[str]) -> list[str]:
    cleanup_request_attachments(request)
    allowed = set(attachment_ids)
    texts = []
    for item in _meta(request):
        if item.get("id") not in allowed:
            continue
        text_path = item.get("text_path")
        if not text_path:
            continue
        try:
            text = Path(text_path).read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        if text:
            texts.append(text[:60_000])
    return texts
