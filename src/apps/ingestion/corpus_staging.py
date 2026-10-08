"""Bounded, resumable staging of authentic archive PDFs in isolated QA."""

from __future__ import annotations

import hashlib
import os
import time
import uuid
import zipfile
from datetime import timedelta
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from src.apps.ingestion.archive_import import (
    LEASE_SECONDS,
    MAX_RETRIES,
    ArchiveImportError,
    _candidate_metadata,
    _copy_verified,
    _manifest_records,
    _storage_root,
)
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.operations.models import ArchiveImportRun
from src.processing.archive_inventory import sha256_file

STAGING_VERSION = "corpus-staging-v1"
MAX_BATCH_SIZE = 20
MAX_BYTE_BUDGET = 512 * 1024 * 1024
MAX_TIME_BUDGET_SECONDS = 600


def _validate_environment(manifest_path: Path) -> None:
    qa_root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        or not qa_root.is_dir()
        or not qa_root.is_relative_to(Path(__import__("tempfile").gettempdir()).resolve())
    ):
        raise ArchiveImportError("staging permitido somente na raiz QA isolada")
    if not manifest_path.is_relative_to(qa_root) or manifest_path == qa_root:
        raise ArchiveImportError("manifesto deve permanecer dentro da raiz QA isolada")


def _candidate_batch(rows: list[dict], cursor: int, batch_size: int, byte_budget: int) -> list[dict]:
    selected = []
    total_bytes = 0
    for row in rows[cursor : cursor + batch_size]:
        size = int(row["uncompressed_bytes"])
        if total_bytes + size > byte_budget:
            break
        selected.append(row)
        total_bytes += size
    return selected


def _stage_pdf(zip_archive: zipfile.ZipFile, row: dict, archive_hash: str) -> dict:
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
    if doc.norma_id or doc.accepted_extraction_id:
        raise ArchiveImportError("staging encontrou documento já vinculado ou promovido")
    return {"created": created, "copied": copied}


def stage_normative_corpus(
    *,
    archive_path: Path,
    manifest_path: Path,
    apply: bool = False,
    batch_size: int = 10,
    byte_budget: int = 256 * 1024 * 1024,
    time_budget_seconds: int = 300,
    resume: str | None = None,
    extractor=None,
) -> dict:
    """Stage at most one bounded batch, preserving provenance and resumability.

    ``extractor`` is accepted only for test dependency injection; staging never
    runs OCR or text extraction.
    """
    if extractor is not None:
        raise ArchiveImportError("staging não executa OCR nem extração")
    if not 1 <= batch_size <= MAX_BATCH_SIZE:
        raise ArchiveImportError(f"batch_size deve ficar entre 1 e {MAX_BATCH_SIZE}")
    if not 1 <= byte_budget <= MAX_BYTE_BUDGET:
        raise ArchiveImportError("byte_budget fora do limite QA")
    if not 1 <= time_budget_seconds <= MAX_TIME_BUDGET_SECONDS:
        raise ArchiveImportError("time_budget_seconds fora do limite QA")

    archive_path = Path(archive_path).resolve()
    manifest_path = Path(manifest_path).resolve()
    _validate_environment(manifest_path)
    archive_hash = sha256_file(archive_path)
    rows, manifest_hash = _manifest_records(manifest_path, archive_hash)
    if not rows:
        raise ArchiveImportError("manifesto não contém PDFs selecionáveis")

    if resume:
        try:
            run_id = uuid.UUID(resume)
        except ValueError as exc:
            raise ArchiveImportError("resume deve ser UUID de ArchiveImportRun") from exc
        run = ArchiveImportRun.objects.get(pk=run_id)
        run_stats = dict(run.stats_json or {})
        if (
            run.archive_sha256 != archive_hash
            or run.manifest_sha256 != manifest_hash
            or run.import_limit != len(rows)
            or run.batch_size != batch_size
            or run_stats.get("staging_version") != STAGING_VERSION
        ):
            raise ArchiveImportError("checkpoint não corresponde ao ZIP, manifesto ou parâmetros de staging")
    else:
        run = None
        run_stats = {"completed": [], "attempts": {}, "errors": {}}

    cursor = run.cursor if run else 0
    batch = _candidate_batch(rows, cursor, batch_size, byte_budget)
    if not batch:
        saved_status = run_stats.get("corpus_status", "partial") if run else "partial"
        complete = cursor >= len(rows)
        return {
            "mode": "dry-run" if not apply else saved_status,
            "run_id": str(run.pk) if run else None,
            "corpus_status": saved_status if run else None,
            "total_pdfs": len(rows),
            "cursor": cursor,
            "remaining": max(len(rows) - cursor, 0),
            "selected": 0,
            "created": int(run_stats.get("created", 0)),
            "unchanged": int(run_stats.get("unchanged", 0)),
            "failed": len(run_stats.get("errors", {})),
            "reason": "corpus_complete" if complete else "next_pdf_exceeds_byte_budget",
        }
    selected_bytes = sum(int(row["uncompressed_bytes"]) for row in batch)

    if not apply:
        return {
            "mode": "dry-run",
            "archive_sha256": archive_hash,
            "manifest_sha256": manifest_hash,
            "total_pdfs": len(rows),
            "cursor": cursor,
            "selected": len(batch),
            "selected_bytes": selected_bytes,
            "remaining_after_batch": len(rows) - cursor - len(batch),
            "batch_size": batch_size,
            "byte_budget": byte_budget,
            "time_budget_seconds": time_budget_seconds,
            "will_create_norma": False,
            "will_extract_text": False,
        }

    if run is None:
        run = ArchiveImportRun.objects.create(
            archive_sha256=archive_hash,
            manifest_sha256=manifest_hash,
            manifest_path=str(manifest_path),
            total_entries=len(rows),
            import_limit=len(rows),
            batch_size=batch_size,
            stats_json={
                "staging_version": STAGING_VERSION,
                "corpus_status": "partial",
                "completed": [],
                "attempts": {},
                "errors": {},
                "created": 0,
                "unchanged": 0,
                "copied_bytes": 0,
            },
        )
        run_stats = dict(run.stats_json)

    lease_token = uuid.uuid4().hex
    with transaction.atomic():
        locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
        if locked.lease_until and locked.lease_until > timezone.now():
            raise ArchiveImportError("este checkpoint já está em uso por outra execução")
        locked.status = ArchiveImportRun.Status.RUNNING
        locked.lease_token = lease_token
        locked.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
        locked.started_at = locked.started_at or timezone.now()
        locked.save(update_fields=["status", "lease_token", "lease_until", "started_at", "updated_at"])

    completed = set(run_stats.get("completed", []))
    attempts = dict(run_stats.get("attempts", {}))
    errors = dict(run_stats.get("errors", {}))
    invocation = {"created": 0, "unchanged": 0, "copied": 0, "failed": 0, "processed": 0}
    started = time.monotonic()
    current_position = cursor
    try:
        with zipfile.ZipFile(archive_path, "r") as zipped:
            for row in batch:
                if time.monotonic() - started >= time_budget_seconds:
                    break
                entry_index = str(row["entry_index"])
                if entry_index in completed:
                    current_position += 1
                    continue
                attempt_count = int(attempts.get(entry_index, 0))
                if attempt_count >= MAX_RETRIES:
                    invocation["failed"] += 1
                    errors[entry_index] = "retry_limit_reached"
                    break
                attempts[entry_index] = attempt_count + 1
                try:
                    with transaction.atomic():
                        result = _stage_pdf(zipped, row, archive_hash)
                    completed.add(entry_index)
                    errors.pop(entry_index, None)
                    invocation["created" if result["created"] else "unchanged"] += 1
                    invocation["copied"] += int(result["copied"])
                    invocation["processed"] += 1
                    run_stats["copied_bytes"] = int(run_stats.get("copied_bytes", 0)) + int(
                        row["uncompressed_bytes"]
                    )
                except Exception as exc:
                    invocation["failed"] += 1
                    errors[entry_index] = type(exc).__name__
                    break
                current_position += 1
                run_stats.update({
                    "completed": sorted(completed, key=int),
                    "attempts": attempts,
                    "errors": errors,
                    "created": int(run_stats.get("created", 0)) + int(result["created"]),
                    "unchanged": int(run_stats.get("unchanged", 0)) + int(not result["created"]),
                })
                with transaction.atomic():
                    locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
                    if locked.lease_token != lease_token:
                        raise ArchiveImportError("lease do staging foi perdida")
                    locked.cursor = current_position
                    locked.stats_json = {**run_stats, "corpus_status": "partial"}
                    locked.lease_until = timezone.now() + timedelta(seconds=LEASE_SECONDS)
                    locked.save(update_fields=["cursor", "stats_json", "lease_until", "updated_at"])

        finished = current_position >= len(rows) and not errors
        final_status = ArchiveImportRun.Status.COMPLETED if finished else ArchiveImportRun.Status.PAUSED
        run_stats["corpus_status"] = "complete" if finished else "partial"
        run_stats["completed"] = sorted(completed, key=int)
        run_stats["attempts"] = attempts
        run_stats["errors"] = errors
        with transaction.atomic():
            locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
            if locked.lease_token != lease_token:
                raise ArchiveImportError("lease do staging foi perdida")
            locked.cursor = current_position
            locked.status = final_status
            locked.lease_token = ""
            locked.lease_until = None
            locked.completed_at = timezone.now() if finished else None
            locked.stats_json = run_stats
            locked.save(update_fields=[
                "cursor", "status", "lease_token", "lease_until", "completed_at", "stats_json", "updated_at",
            ])
        return {
            "mode": "apply",
            "run_id": str(run.pk),
            "corpus_status": run_stats["corpus_status"],
            "total_pdfs": len(rows),
            "cursor": current_position,
            "remaining": len(rows) - current_position,
            **invocation,
        }
    except Exception:
        with transaction.atomic():
            locked = ArchiveImportRun.objects.select_for_update().get(pk=run.pk)
            if locked.lease_token == lease_token:
                run_stats.update({
                    "corpus_status": "partial",
                    "completed": sorted(completed, key=int),
                    "attempts": attempts,
                    "errors": errors,
                })
                locked.status = ArchiveImportRun.Status.PAUSED
                locked.lease_token = ""
                locked.lease_until = None
                locked.cursor = current_position
                locked.stats_json = run_stats
                locked.save(update_fields=[
                    "status", "lease_token", "lease_until", "cursor", "stats_json", "updated_at",
                ])
        raise
