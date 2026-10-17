"""Extract resumable, non-operative relation candidates from real archive PDFs."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import OuterRef, Subquery

from src.apps.ingestion.document_relation_candidates import (
    extract_document_relation_candidates,
    persist_document_relation_candidates,
)
from src.apps.legislation.document_models import (
    DocumentoNormativo,
    ExtracaoDocumento,
)

CHECKPOINT_NAME = "archive-relation-candidates-checkpoint.json"
CHECKPOINT_SCHEMA = 1
MAX_BATCH_SIZE = 10


def _candidate_rows():
    latest_extraction = ExtracaoDocumento.objects.filter(
        documento_id=OuterRef("pk")
    ).order_by("-created_at", "-pk")
    documents = (
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .exclude(storage_key="")
        .annotate(latest_extraction_id=Subquery(latest_extraction.values("pk")[:1]))
        .annotate(
            latest_extraction_sha256=Subquery(
                latest_extraction.values("extraction_sha256")[:1]
            )
        )
        .annotate(
            latest_extraction_status=Subquery(latest_extraction.values("status")[:1])
        )
        .filter(latest_extraction_status=ExtracaoDocumento.Status.COMPLETE)
        .order_by("public_id")
        .values_list(
            "public_id",
            "metadata_json",
            "latest_extraction_id",
            "latest_extraction_sha256",
        )
    )
    rows = []
    for public_id, raw_metadata, extraction_id, extraction_sha256 in documents.iterator(
        chunk_size=250
    ):
        metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
        identity = metadata.get("identity_candidate")
        identity = identity if isinstance(identity, dict) else {}
        if any(
            value is True
            for value in (
                metadata.get("synthetic"),
                metadata.get("synthetic_fixture"),
                identity.get("synthetic"),
                identity.get("synthetic_fixture"),
            )
        ):
            continue
        rows.append((str(public_id), extraction_id, extraction_sha256))
    return rows


def _universe_fingerprint(rows) -> str:
    digest = hashlib.sha256()
    for public_id, extraction_id, extraction_sha256 in rows:
        digest.update(f"{public_id}\0{extraction_id}\0{extraction_sha256}\n".encode())
    return digest.hexdigest()


def _checkpoint_path(universe_sha256: str) -> Path:
    root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    if not root.is_dir():
        raise CommandError("A raiz QA isolada não está disponível.")
    legacy_path = root / CHECKPOINT_NAME
    if legacy_path.is_file():
        try:
            legacy = json.loads(legacy_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            legacy = None
        if isinstance(legacy, dict) and legacy.get("universe_sha256") == universe_sha256:
            return legacy_path
    # A changed corpus/extraction revision starts a distinct append-only run.
    # Keep the old checkpoint for audit and allow safe resume of this universe.
    return root / f"archive-relation-candidates-{universe_sha256}-checkpoint.json"


def _save_checkpoint(path: Path, checkpoint: dict) -> None:
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=".relation-checkpoint-",
            suffix=".tmp",
            delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(checkpoint, stream, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _record_batch(checkpoint: dict, *, cursor: int, batch_size: int, found: int, created: int,
                  universe_count: int) -> int:
    """Advance exactly once after one idempotently persisted slice."""
    next_cursor = cursor + batch_size
    checkpoint["processed"] += batch_size
    checkpoint["cursor"] = next_cursor
    checkpoint["candidates_found"] += found
    checkpoint["candidates_created"] += created
    checkpoint["status"] = "completed" if next_cursor == universe_count else "pending"
    return next_cursor


class Command(BaseCommand):
    help = "Extrai relações de PDFs históricos em lotes QA, sem revisar ou consolidar."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=10)
        parser.add_argument("--max-batches", type=int, default=1)
        parser.add_argument("--resume", action="store_true")

    def handle(self, *args, **options):
        database = settings.DATABASES.get("default", {})
        host_qa = (
            os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings_normative_qa"
            and database.get("NAME") == "jurix_audit"
            and database.get("HOST") == "127.0.0.1"
            and str(database.get("PORT")) == "55432"
            and database.get("USER") == "jurix_audit"
        )
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or not host_qa
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o banco PostgreSQL QA isolado.")

        batch_size = options["batch_size"]
        if not 1 <= batch_size <= MAX_BATCH_SIZE:
            raise CommandError(f"--batch-size deve estar entre 1 e {MAX_BATCH_SIZE}.")
        max_batches = options["max_batches"]
        if not 1 <= max_batches <= MAX_BATCH_SIZE:
            raise CommandError(f"--max-batches deve estar entre 1 e {MAX_BATCH_SIZE}.")

        rows = _candidate_rows()
        fingerprint = _universe_fingerprint(rows)
        checkpoint_path = _checkpoint_path(fingerprint)
        exists = checkpoint_path.exists()
        if options["apply"] and exists != options["resume"]:
            raise CommandError("Checkpoint existente exige --resume; sem checkpoint, inicie sem.")
        if options["resume"] and not exists:
            raise CommandError("Não existe checkpoint QA para retomar.")

        if options["resume"]:
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError("Checkpoint QA inválido; nenhuma relação foi alterada.") from exc
            if (
                checkpoint.get("schema") != CHECKPOINT_SCHEMA
                or checkpoint.get("universe_sha256") != fingerprint
                or checkpoint.get("universe_count") != len(rows)
            ):
                raise CommandError("Universo de extrações mudou; checkpoint não será aplicado.")
            if checkpoint.get("status") == "completed":
                self.stdout.write(json.dumps({"status": "completed", "remaining": 0}))
                return
        else:
            checkpoint = {
                "schema": CHECKPOINT_SCHEMA,
                "universe_sha256": fingerprint,
                "universe_count": len(rows),
                "cursor": 0,
                "processed": 0,
                "candidates_found": 0,
                "candidates_created": 0,
                "status": "pending",
            }

        cursor = checkpoint.get("cursor")
        if not isinstance(cursor, int) or not 0 <= cursor <= len(rows):
            raise CommandError("Cursor do checkpoint QA fora do intervalo.")
        action_counts: Counter[str] = Counter()
        found = created = 0
        documents_processed = 0
        batches_processed = 0
        initial_cursor = cursor
        while cursor < len(rows) and batches_processed < max_batches:
            batch = rows[cursor : cursor + batch_size]
            batch_found = batch_created = 0
            for _public_id, extraction_id, _extraction_sha256 in batch:
                extraction = ExtracaoDocumento.objects.get(pk=extraction_id)
                candidates = extract_document_relation_candidates(extraction)
                batch_found += len(candidates)
                action_counts.update(item["action"] for item in candidates)
                if options["apply"]:
                    result = persist_document_relation_candidates(extraction)
                    batch_created += result["created"]

            found += batch_found
            created += batch_created
            cursor += len(batch)
            documents_processed += len(batch)
            batches_processed += 1
            if options["apply"]:
                _record_batch(
                    checkpoint,
                    cursor=cursor - len(batch),
                    batch_size=len(batch),
                    found=batch_found,
                    created=batch_created,
                    universe_count=len(rows),
                )
                _save_checkpoint(checkpoint_path, checkpoint)

        if options["apply"] and cursor == len(rows) and checkpoint["status"] != "completed":
            checkpoint["status"] = "completed"
            _save_checkpoint(checkpoint_path, checkpoint)

        if options["dry_run"]:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "cursor": initial_cursor,
                        "next_cursor": cursor,
                        "batch_documents": documents_processed,
                        "batches_processed": batches_processed,
                        "universe_documents": len(rows),
                        "candidates_found": found,
                        "actions": dict(sorted(action_counts.items())),
                        "checkpoint_written": False,
                        "reviewed": False,
                        "legal_effect": False,
                    },
                    sort_keys=True,
                )
            )
            return

        self.stdout.write(
            json.dumps(
                {
                    "mode": "apply",
                    "status": checkpoint["status"],
                    "batch_documents": documents_processed,
                    "batches_processed": batches_processed,
                    "cursor": checkpoint["cursor"],
                    "universe_documents": len(rows),
                    "batch_candidates_found": found,
                    "batch_candidates_created": created,
                    "actions": dict(sorted(action_counts.items())),
                    "total_candidates_created": checkpoint["candidates_created"],
                    "reviewed": False,
                    "legal_effect": False,
                },
                sort_keys=True,
            )
        )
