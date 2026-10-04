"""Immutable staging for changed SAPL PDF revisions."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from django.conf import settings

from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.clients.sapl.sapl_client import SaplAPIClient


class SaplDocumentCandidateError(RuntimeError):
    """A remote PDF could not be verified or staged as a new immutable candidate."""


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _storage_root() -> Path:
    configured = getattr(settings, "NORMATIVE_ARCHIVE_ROOT", None)
    if configured:
        root = Path(configured).resolve()
    else:
        base = Path(getattr(settings, "QA_ROOT", settings.MEDIA_ROOT)).resolve()
        root = (base / "normative-archive").resolve()

    if os.environ.get("JURIX_QA_ONLY") == "1":
        qa_root = Path(getattr(settings, "QA_ROOT", "")).resolve()
        if not qa_root.is_dir() or not root.is_relative_to(qa_root):
            raise SaplDocumentCandidateError("SAPL candidate storage escaped the QA root")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _matches_fingerprint(remote_fingerprint: str, download: dict[str, Any]) -> bool:
    if remote_fingerprint.startswith("sha256:"):
        return remote_fingerprint.removeprefix("sha256:") == download["content_sha256"]
    if remote_fingerprint.startswith("etag:"):
        etag = remote_fingerprint.removeprefix("etag:")
        return bool(etag and not etag.lower().startswith("w/") and etag == download["etag"])
    if remote_fingerprint.startswith("last-modified:"):
        validator = remote_fingerprint.removeprefix("last-modified:")
        last_modified, separator, size = validator.rpartition(":bytes:")
        return bool(
            separator
            and size.isdigit()
            and last_modified == download["last_modified"]
            and int(size) == download["size_bytes"]
        )
    return False


def _store_content_addressed_pdf(source: Path, root: Path, expected_sha256: str) -> tuple[str, bool]:
    digest = hashlib.sha256()
    total = 0
    prefix = b""
    with source.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            total += len(chunk)
            digest.update(chunk)
            if len(prefix) < 5:
                prefix += chunk[: 5 - len(prefix)]
    actual_sha256 = digest.hexdigest()
    if actual_sha256 != expected_sha256 or total == 0 or not prefix.startswith(b"%PDF-"):
        raise SaplDocumentCandidateError("Staged SAPL PDF failed its content integrity check")

    relative_key = Path("sha256") / actual_sha256[:2] / actual_sha256[2:4] / f"{actual_sha256}.pdf"
    target = (root / relative_key).resolve()
    if not target.is_relative_to(root):
        raise SaplDocumentCandidateError("Content-addressed PDF path escaped storage root")
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        existing_hash = _sha256_file(target)
        if existing_hash != actual_sha256:
            raise SaplDocumentCandidateError("Existing content-addressed blob has a hash conflict")
        return relative_key.as_posix(), False

    try:
        os.link(source, target)
        return relative_key.as_posix(), True
    except FileExistsError as exc:
        existing_hash = _sha256_file(target)
        if existing_hash != actual_sha256:
            raise SaplDocumentCandidateError(
                "Concurrent content-addressed blob has a hash conflict"
            ) from exc
        return relative_key.as_posix(), False


def stage_sapl_pdf_candidate(
    *,
    client: SaplAPIClient,
    norma: Norma,
    pdf_url: str,
    remote_fingerprint: str,
) -> tuple[DocumentoNormativo, bool]:
    """Download and record an unapproved immutable SAPL document revision.

    The current Norma PDF path, consolidated text, and accepted document are not
    changed. The candidate has unknown use conditions and remains pending review.
    """
    if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
        raise SaplDocumentCandidateError("Normative document staging is disabled")
    if not norma.sapl_id:
        raise SaplDocumentCandidateError("Norma has no stable SAPL identifier")

    existing = DocumentoNormativo.objects.filter(
        norma=norma,
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        metadata_json__remote_fingerprint=remote_fingerprint,
    ).order_by("created_at", "public_id").first()
    if existing:
        return existing, False

    root = _storage_root()
    staging_root = root / ".staging"
    staging_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=f"sapl-{norma.sapl_id}-", dir=staging_root) as tmp:
        downloaded_path = Path(tmp) / "candidate.pdf"
        download = client.download_pdf_version(pdf_url, downloaded_path)
        if not _matches_fingerprint(remote_fingerprint, download):
            raise SaplDocumentCandidateError(
                "Downloaded PDF does not match the SAPL fingerprint observed by sync"
            )
        storage_key, _ = _store_content_addressed_pdf(
            downloaded_path, root, download["content_sha256"]
        )

    document_key = hashlib.sha256(
        f"sapl:{norma.sapl_id}:{download['content_sha256']}".encode()
    ).hexdigest()
    url_path = unquote(urlparse(pdf_url).path)
    original_filename = Path(url_path).name[:500] or f"sapl-{norma.sapl_id}.pdf"
    identity_json = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    defaults = {
        "norma": norma,
        "source_kind": DocumentoNormativo.SourceKind.SAPL,
        "source_ref": f"sapl:{norma.sapl_id}:sha256:{download['content_sha256']}",
        "original_filename": original_filename,
        "role": DocumentoNormativo.Role.UNDETERMINED,
        "storage_key": storage_key,
        "size_bytes": download["size_bytes"],
        "content_sha256": download["content_sha256"],
        "official_url": client._validated_sapl_pdf_url(pdf_url),
        "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
        "metadata_json": {
            "sapl_id": norma.sapl_id,
            "identity_key": norma.identity_key,
            "identity_candidate": identity_json,
            "remote_fingerprint": remote_fingerprint,
            "candidate_reason": "remote_pdf_revision",
        },
        "extraction_status": DocumentoNormativo.ExtractionStatus.PENDING,
        "review_status": DocumentoNormativo.ReviewStatus.PENDING,
    }
    document, created = DocumentoNormativo.objects.get_or_create(
        document_key=document_key,
        defaults=defaults,
    )
    if document.content_sha256 != download["content_sha256"]:
        raise SaplDocumentCandidateError("SAPL document key is already bound to different bytes")
    if document.storage_key != storage_key:
        raise SaplDocumentCandidateError("SAPL document key is already bound to a different blob")
    return document, created
