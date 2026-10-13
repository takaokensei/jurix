"""Extract a resumable batch of local archive PDFs into pending QA candidates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from src.apps.ingestion.normative_tasks import _extract_archive_candidate
from src.apps.legislation.document_models import DocumentoNormativo
from src.processing.document_extraction import page_has_image, should_ocr_page

CHECKPOINT_NAME = "archive-extraction-checkpoint.json"
CHECKPOINT_SCHEMA = 1
BATCH_OCR_PAGE_BUDGET = 10
BATCH_OCR_TIMEOUT_SECONDS = 15
BATCH_MAX_PAGES = 500


def _candidate_rows():
    return list(
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .exclude(storage_key="")
        .exclude(content_sha256="")
        .order_by("public_id")
        .values_list("public_id", "storage_key", "content_sha256", "size_bytes")
    )


def _universe_fingerprint(rows) -> str:
    digest = hashlib.sha256()
    for public_id, storage_key, content_sha256, size_bytes in rows:
        digest.update(
            f"{public_id}\0{storage_key}\0{content_sha256}\0{size_bytes}\n".encode()
        )
    return digest.hexdigest()


def _checkpoint_path() -> Path:
    root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    if not root.is_dir():
        raise CommandError("A raiz QA isolada não está disponível.")
    return root / CHECKPOINT_NAME


def _save_checkpoint(path: Path, checkpoint: dict) -> None:
    """Atomically persist only counters, cursor and hashes (never document text)."""
    temporary_path = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, prefix=".archive-checkpoint-",
            suffix=".tmp", delete=False,
        ) as stream:
            temporary_path = Path(stream.name)
            json.dump(checkpoint, stream, ensure_ascii=False, sort_keys=True)
            stream.flush()
            os.fsync(stream.fileno())
        temporary_path.replace(path)
    finally:
        if temporary_path and temporary_path.exists():
            temporary_path.unlink()


def _verified_pdf(qa_root: Path, storage_key: str, expected_sha256: str) -> Path:
    archive_root = (qa_root / "normative-archive").resolve()
    pdf_path = (archive_root / storage_key).resolve()
    if not pdf_path.is_relative_to(archive_root) or not pdf_path.is_file():
        raise CommandError("PDF ausente ou fora do armazenamento de arquivos QA.")
    digest = hashlib.sha256()
    with pdf_path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    if digest.hexdigest() != expected_sha256:
        raise CommandError("Hash do PDF diverge do registro QA.")
    return pdf_path


class Command(BaseCommand):
    help = "Extrai PDFs locais em lotes retomáveis, sempre como candidatos pendentes de revisão QA."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=10)
        parser.add_argument("--resume", action="store_true")

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o ambiente QA normativo isolado.")
        batch_size = options["batch_size"]
        if not 1 <= batch_size <= 10:
            raise CommandError("--batch-size deve estar entre 1 e 10.")
        if options["resume"] and not (options["apply"] or options["dry_run"]):
            raise CommandError("--resume exige --apply ou --dry-run.")

        checkpoint_path = _checkpoint_path()
        exists = checkpoint_path.exists()
        if options["apply"] and exists != options["resume"]:
            raise CommandError(
                "Checkpoint existente exige --resume; sem checkpoint, inicie sem --resume."
            )
        if options["resume"] and not exists:
            raise CommandError("Não existe checkpoint QA para retomar.")

        qa_root = Path(getattr(settings, "QA_ROOT", os.environ["JURIX_QA_ROOT"])).resolve()
        rows = _candidate_rows()
        fingerprint = _universe_fingerprint(rows)
        if options["resume"]:
            try:
                checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError("Checkpoint QA inválido; interrompendo sem alterar dados.") from exc
            if (
                checkpoint.get("schema") != CHECKPOINT_SCHEMA
                or checkpoint.get("universe_sha256") != fingerprint
                or checkpoint.get("universe_count") != len(rows)
            ):
                raise CommandError("Universo de candidatos mudou; checkpoint não será aplicado.")
            if checkpoint.get("status") == "completed":
                self.stdout.write(json.dumps({"status": "completed", "remaining": 0}, sort_keys=True))
                return
        else:
            checkpoint = {
                "schema": CHECKPOINT_SCHEMA,
                "universe_sha256": fingerprint,
                "universe_count": len(rows),
                "cursor": 0,
                "processed": 0,
                "created": 0,
                "skipped_existing": 0,
                "status": "pending",
            }

        if not rows and options["apply"]:
            checkpoint["status"] = "completed"
            _save_checkpoint(checkpoint_path, checkpoint)

        start = checkpoint["cursor"]
        if not isinstance(start, int) or not 0 <= start <= len(rows):
            raise CommandError("Cursor do checkpoint QA fora do intervalo.")
        batch = rows[start : start + batch_size]
        verified_bytes = 0
        existing_extractions = 0
        page_counts = []
        ocr_page_counts = []
        for public_id, storage_key, content_sha256, size_bytes in batch:
            pdf_path = _verified_pdf(qa_root, storage_key, content_sha256)
            verified_bytes += size_bytes
            if options["dry_run"]:
                import fitz

                with fitz.open(pdf_path) as pdf:
                    page_counts.append(len(pdf))
                    ocr_page_counts.append(
                        sum(
                            should_ocr_page(page.get_text("text") or "", page_has_image(page))[0]
                            for page in pdf
                        )
                    )
            if DocumentoNormativo.objects.filter(public_id=public_id, extracoes__isnull=False).exists():
                existing_extractions += 1

        if options["dry_run"]:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "batch_size": batch_size,
                        "cursor": start,
                        "batch_candidates": len(batch),
                        "universe_candidates": len(rows),
                        "existing_extractions_in_batch": existing_extractions,
                        "verified_pdf_bytes": verified_bytes,
                        "page_counts": page_counts,
                        "ocr_page_counts": ocr_page_counts,
                        "checkpoint_written": False,
                    },
                    sort_keys=True,
                )
            )
            return

        for index, (public_id, _storage_key, _sha256, _size) in enumerate(batch, start=start):
            document = DocumentoNormativo.objects.get(public_id=public_id)
            if document.extracoes.exists():
                checkpoint["skipped_existing"] += 1
            else:
                try:
                    extraction = _extract_archive_candidate(
                        document,
                        max_pages=BATCH_MAX_PAGES,
                        max_ocr_pages=BATCH_OCR_PAGE_BUDGET,
                        ocr_timeout_seconds=BATCH_OCR_TIMEOUT_SECONDS,
                    )
                except Exception as exc:  # keep cursor on failure so resume retries this exact item
                    checkpoint["status"] = "failed"
                    checkpoint["failed_item"] = str(public_id)
                    checkpoint["error_type"] = type(exc).__name__
                    _save_checkpoint(checkpoint_path, checkpoint)
                    self.stderr.write(
                        json.dumps(
                            {
                                "status": "failed",
                                "document_id": str(public_id),
                                "error_type": type(exc).__name__,
                                "cursor": index,
                            },
                            sort_keys=True,
                        )
                    )
                    raise CommandError("Extração interrompida; checkpoint preservado para retomada.") from exc
                if extraction.documento_id != document.pk:
                    raise CommandError("Extração retornou documento divergente; cursor não avançado.")
                checkpoint["created"] += 1
            checkpoint["processed"] += 1
            checkpoint["cursor"] = index + 1
            checkpoint["status"] = "completed" if checkpoint["cursor"] == len(rows) else "pending"
            checkpoint.pop("failed_item", None)
            checkpoint.pop("error_type", None)
            _save_checkpoint(checkpoint_path, checkpoint)

        self.stdout.write(
            json.dumps(
                {
                    "mode": "apply",
                    "status": checkpoint["status"],
                    "batch_processed": len(batch),
                    "cursor": checkpoint["cursor"],
                    "universe_candidates": len(rows),
                    "candidate_extractions_created_total": checkpoint["created"],
                    "skipped_existing_total": checkpoint["skipped_existing"],
                    "pending_archive_extractions_by_status": dict(
                        DocumentoNormativo.objects.filter(
                            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                            review_status=DocumentoNormativo.ReviewStatus.PENDING,
                            extracoes__isnull=False,
                        )
                        .values("extracoes__status")
                        .annotate(count=Count("pk"))
                        .values_list("extracoes__status", "count")
                    ),
                    "review_accepted": False,
                    "norma_linkage_created": False,
                },
                sort_keys=True,
            )
        )
