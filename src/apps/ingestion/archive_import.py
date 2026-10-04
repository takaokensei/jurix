"""Resumable, QA-only staging import of PDF entries from an inventoried ZIP."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path, PurePosixPath

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.operations.models import ArchiveImportRun
from src.processing.archive_inventory import sha256_file
from src.processing.document_extraction import extract_pdf_document
from src.processing.document_metadata import (
    build_normative_identity,
    parse_filename_metadata,
)

IMPORT_VERSION = "archive-staging-v1"
LEASE_SECONDS = 900
MAX_RETRIES = 3


class ArchiveImportError(ValueError):
    """Input or checkpoint cannot be safely resumed."""


def _manifest_records(path: Path, archive_hash: str) -> tuple[list[dict], str]:
    digest = hashlib.sha256()
    entries = []
    summary = None
    with path.open("rb") as stream:
        for line in stream:
            digest.update(line)
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("record_type") == "summary":
                summary = row
            elif row.get("record_type") == "entry" and row.get("extension") == ".pdf":
                entries.append(row)
    if not summary or not summary.get("complete") or summary.get("archive_sha256") != archive_hash:
        raise ArchiveImportError("manifesto ausente, incompleto ou referente a outro ZIP")
    if summary.get("entry_count") != sum(1 for _ in _iter_jsonl(path) if _.get("record_type") == "entry"):
        raise ArchiveImportError("contagem de entradas do manifesto não confere")
    for row in entries:
        if row.get("archive_sha256") != archive_hash or row.get("hash_status") != "hashed" or row.get("flags"):
            raise ArchiveImportError("manifesto contém PDF não verificado ou sinalizado")
    return entries, digest.hexdigest()


def _iter_jsonl(path: Path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            if line.strip():
                yield json.loads(line)


def _safe_entry_name(name: str) -> bool:
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    return not (
        path.is_absolute()
        or normalized.startswith("//")
        or ".." in path.parts
        or (len(normalized) > 1 and normalized[1] == ":")
        or "\x00" in normalized
    )


def _storage_root() -> Path:
    root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    if not root.is_dir() or not root.is_relative_to(Path(tempfile.gettempdir()).resolve()):
        raise ArchiveImportError("storage QA isolado indisponível")
    target = root / "normative-archive"
    target.mkdir(parents=True, exist_ok=True)
    return target


def _copy_verified(zip_archive: zipfile.ZipFile, row: dict) -> tuple[Path, bool]:
    expected_hash = row["content_sha256"]
    root = _storage_root()
    target = root / "sha256" / expected_hash[:2] / expected_hash[2:4] / f"{expected_hash}.pdf"
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists():
        if sha256_file(target) != expected_hash:
            raise ArchiveImportError("blob content-addressed existente não confere")
        return target, False
    info = zip_archive.infolist()[row["entry_index"]]
    if info.filename != row["entry_name"] or not _safe_entry_name(info.filename):
        raise ArchiveImportError("índice/nome do ZIP diverge do manifesto seguro")
    fd, temporary_name = tempfile.mkstemp(prefix="archive-", suffix=".part", dir=target.parent)
    digest = hashlib.sha256()
    try:
        with os.fdopen(fd, "wb") as destination, zip_archive.open(info, "r") as source:
            while chunk := source.read(1024 * 1024):
                digest.update(chunk)
                destination.write(chunk)
            destination.flush()
            os.fsync(destination.fileno())
        if digest.hexdigest() != expected_hash:
            raise ArchiveImportError("hash PDF diverge do manifesto")
        try:
            os.link(temporary_name, target)
        except FileExistsError:
            if sha256_file(target) != expected_hash:
                raise ArchiveImportError("colisão no storage content-addressed") from None
            return target, False
        return target, True
    finally:
        Path(temporary_name).unlink(missing_ok=True)


def _candidate_metadata(entry: dict) -> dict:
    filename = entry["entry_name"].replace("\\", "/").rsplit("/", 1)[-1]
    parsed = parse_filename_metadata(filename)
    year = next(
        (item["value"][:4] for item in parsed.as_dict()["candidates"] if item["field"] == "unclassified_filename_date"),
        None,
    )
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type=parsed.type_key or "",
        series=parsed.series,
        number=parsed.number,
        year=year,
    )
    return {
        "filename_metadata": parsed.as_dict(),
        "identity_candidate": identity.identity_json,
        "identity_key": identity.identity_key,
        "identity_status": "candidate" if identity.identity_key else "unresolved",
    }


def _stage_entry(zip_archive, row, archive_hash, extractor: Callable):
    path, copied = _copy_verified(zip_archive, row)
    metadata = _candidate_metadata(row)
    document_key = hashlib.sha256(
        f"{archive_hash}:{row['entry_index']}:{row['content_sha256']}".encode()
    ).hexdigest()
    doc, created = DocumentoNormativo.objects.get_or_create(
        document_key=document_key,
        defaults={
            "source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
            "source_ref": f"archive:{archive_hash}:entry:{row['entry_index']}",
            "archive_sha256": archive_hash,
            "entry_index": row["entry_index"],
            "entry_name": row["entry_name"],
            "original_filename": row["entry_name"].replace("\\", "/").rsplit("/", 1)[-1][:500],
            "role": metadata["filename_metadata"]["role"],
            "storage_key": path.relative_to(_storage_root()).as_posix(),
            "size_bytes": row["uncompressed_bytes"],
            "content_sha256": row["content_sha256"],
            "metadata_json": metadata,
            "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
            "review_status": DocumentoNormativo.ReviewStatus.PENDING,
        },
    )
    if doc.content_sha256 != row["content_sha256"]:
        raise ArchiveImportError("document_key existente associado a hash incompatível")
    extraction_created = False
    extraction = ExtracaoDocumento.objects.filter(
        documento=doc, extractor_version=IMPORT_VERSION,
        policy_fingerprint=hashlib.sha256(b"staging-no-ocr-v1").hexdigest(),
    ).first()
    if not extraction:
        result = extractor(str(path), max_pages=200, ocr_timeout_seconds=30, ocr=lambda image, timeout: "")
        extraction = ExtracaoDocumento(
            documento=doc,
            extractor_version=IMPORT_VERSION,
            policy_fingerprint=hashlib.sha256(b"staging-no-ocr-v1").hexdigest(),
            text_version=result["text_version"],
            raw_text=result["raw_text"],
            legal_text=result["legal_text"],
            page_count=result["page_count"],
            page_map_json=result["source_map"][:200],
            metadata_candidates_json=result["metadata_candidates"],
            quality_json={**result["quality"], "needs_review": True, "staging_only": True},
            status=ExtracaoDocumento.Status.COMPLETE if result["complete"] else ExtracaoDocumento.Status.PARTIAL,
            extraction_sha256=result["extraction_sha256"],
        )
        extraction.save()
        extraction_created = True
        doc.extraction_status = (
            DocumentoNormativo.ExtractionStatus.NEEDS_REVIEW
            if result["needs_review"] else DocumentoNormativo.ExtractionStatus.EXTRACTED
        )
        doc.save(update_fields=["extraction_status", "updated_at"])
    return {"created": created, "extraction_created": extraction_created, "copied": copied, "document_id": str(doc.public_id)}


def import_archive(
    *, archive_path: Path, manifest_path: Path, apply: bool, limit: int = 40,
    batch_size: int = 10, resume: str | None = None, fail_after: int | None = None,
    extractor: Callable = extract_pdf_document,
) -> dict:
    if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False) or not os.environ.get("JURIX_QA_ONLY") == "1":
        raise ArchiveImportError("importador disponível somente no ambiente QA explícito")
    if limit < 1 or limit > 40 or batch_size < 1 or batch_size > 10:
        raise ArchiveImportError("limit máximo 40 e batch_size máximo 10")
    archive_path, manifest_path = archive_path.resolve(), manifest_path.resolve()
    archive_hash = sha256_file(archive_path)
    rows, manifest_hash = _manifest_records(manifest_path, archive_hash)
    selected = rows[:limit]
    if not apply:
        return {"mode": "dry-run", "archive_sha256": archive_hash, "manifest_sha256": manifest_hash, "selected": len(selected), "limit": limit, "batch_size": batch_size}
    if resume:
        try:
            run_id = uuid.UUID(resume)
        except ValueError as exc:
            raise ArchiveImportError("resume deve ser UUID de ArchiveImportRun") from exc
        run = ArchiveImportRun.objects.get(pk=run_id)
        if (
            run.archive_sha256 != archive_hash
            or run.manifest_sha256 != manifest_hash
            or run.import_limit != limit
            or run.batch_size != batch_size
        ):
            raise ArchiveImportError("checkpoint não corresponde ao mesmo ZIP, manifesto e limite")
    else:
        run = ArchiveImportRun.objects.create(
            archive_sha256=archive_hash, manifest_sha256=manifest_hash,
            manifest_path=str(manifest_path), total_entries=len(selected), import_limit=limit,
            batch_size=batch_size, stats_json={"attempts": {}, "completed": []},
        )
    stats = {"created": 0, "unchanged": 0, "failed": 0, "extraction_created": 0, "copied": 0}
    token = uuid.uuid4().hex
    with transaction.atomic():
        locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
        if locked.lease_until and locked.lease_until > timezone.now():
            raise ArchiveImportError("este checkpoint já está em uso por outra execução")
        locked.status = ArchiveImportRun.Status.RUNNING
        locked.lease_token = token
        locked.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
        locked.started_at = locked.started_at or timezone.now()
        locked.save(update_fields=["status", "lease_token", "lease_until", "started_at", "updated_at"])
    checkpoint = dict(run.stats_json or {})
    completed = set(checkpoint.get("completed", []))
    attempts = checkpoint.get("attempts", {})
    processed_this_call = 0
    try:
        with zipfile.ZipFile(archive_path, "r") as archive:
            for offset in range(run.cursor, len(selected), batch_size):
                batch = selected[offset : offset + batch_size]
                batch_failed = False
                for row in batch:
                    index = str(row["entry_index"])
                    if index in completed:
                        continue
                    if int(attempts.get(index, 0)) >= MAX_RETRIES:
                        stats["failed"] += 1
                        continue
                    attempts[index] = int(attempts.get(index, 0)) + 1
                    try:
                        with transaction.atomic():
                            result = _stage_entry(archive, row, archive_hash, extractor)
                            stats["created" if result["created"] else "unchanged"] += 1
                            stats["extraction_created"] += int(result["extraction_created"])
                            stats["copied"] += int(result["copied"])
                            completed.add(index)
                    except Exception as exc:
                        stats["failed"] += 1
                        batch_failed = True
                        checkpoint.setdefault("errors", {})[index] = type(exc).__name__
                    processed_this_call += 1
                    if fail_after is not None and processed_this_call >= fail_after:
                        raise RuntimeError("injected QA interruption")
                cursor = offset if batch_failed else min(offset + len(batch), len(selected))
                checkpoint.update({"attempts": attempts, "completed": sorted(completed, key=int)})
                with transaction.atomic():
                    locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
                    if locked.lease_token != token:
                        raise ArchiveImportError("lease do importador foi perdida")
                    locked.cursor = cursor
                    locked.stats_json = checkpoint
                    locked.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
                    locked.save(update_fields=["cursor", "stats_json", "lease_until", "updated_at"])
        with transaction.atomic():
            locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
            locked.status = ArchiveImportRun.Status.COMPLETED if locked.cursor >= len(selected) else ArchiveImportRun.Status.PAUSED
            locked.lease_token = ""
            locked.lease_until = None
            locked.completed_at = timezone.now() if locked.cursor >= len(selected) else None
            locked.stats_json = {**checkpoint, "last_call": stats}
            locked.save(update_fields=["status", "lease_token", "lease_until", "completed_at", "stats_json", "updated_at"])
    except Exception:
        ArchiveImportRun.objects.filter(pk=run.pk, lease_token=token).update(
            status=ArchiveImportRun.Status.PAUSED, lease_token="", lease_until=None,
            stats_json={**checkpoint, "attempts": attempts, "completed": sorted(completed, key=int)},
        )
        raise
    return {"mode": "apply", "run_id": str(run.pk), "cursor": ArchiveImportRun.objects.get(pk=run.pk).cursor, **stats}
