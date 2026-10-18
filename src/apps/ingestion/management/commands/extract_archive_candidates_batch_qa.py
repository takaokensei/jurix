"""Extract a resumable batch of local archive PDFs into pending QA candidates."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from collections import Counter
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count

from src.apps.ingestion.normative_tasks import _extract_archive_candidate
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.document_extraction import (
    EXTRACTION_POLICY,
    page_has_image,
    should_ocr_page,
)

CHECKPOINT_NAME = "archive-extraction-checkpoint.json"
SAPL_DATE_CHECKPOINT_NAME = "archive-extraction-sapl-date-v2-checkpoint.json"
CHECKPOINT_SCHEMA = 1
BATCH_OCR_PAGE_BUDGET = 10
BATCH_OCR_TIMEOUT_SECONDS = 15
BATCH_MAX_PAGES = 500


def _current_extraction_policy_fingerprint() -> str:
    policy = {
        **EXTRACTION_POLICY,
        "max_pages": BATCH_MAX_PAGES,
        "ocr_timeout_seconds": BATCH_OCR_TIMEOUT_SECONDS,
        "max_ocr_pages": BATCH_OCR_PAGE_BUDGET,
    }
    return hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()


def _has_current_pipeline_extraction(document_id) -> bool:
    return document_id and DocumentoNormativo.objects.filter(
        pk=document_id,
        extracoes__extractor_version__startswith="pymupdf-",
        extracoes__policy_fingerprint=_current_extraction_policy_fingerprint(),
        extracoes__quality_json__pipeline_candidate_only=True,
    ).exists()


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
    for row in rows:
        public_id, storage_key, content_sha256, size_bytes, *ordering_fields = row
        digest.update(
            f"{public_id}\0{storage_key}\0{content_sha256}\0{size_bytes}\n".encode()
        )
        for field in ordering_fields:
            digest.update(f"{field}\0".encode())
    return digest.hexdigest()


def _batch_extraction_summary(public_ids: list[str]) -> dict[str, object]:
    """Return aggregate latest-extraction and table-candidate counts for one batch."""
    document_ids = list(
        DocumentoNormativo.objects.filter(public_id__in=public_ids).values_list("pk", flat=True)
    )
    latest_by_document = {}
    rows = (
        ExtracaoDocumento.objects.filter(documento_id__in=document_ids)
        .order_by("documento_id", "-created_at", "-pk")
        .values_list("documento_id", "status", "page_count", "metadata_candidates_json")
    )
    for document_id, status, page_count, metadata_candidates in rows:
        latest_by_document.setdefault(
            document_id, (status, page_count, metadata_candidates)
        )

    status_counts = Counter()
    page_count_total = 0
    documents_with_layout_tables = 0
    layout_table_candidate_count = 0
    for document_id in document_ids:
        extraction = latest_by_document.get(document_id)
        if extraction is None:
            status_counts["none"] += 1
            continue
        status, page_count, metadata_candidates = extraction
        status_counts[status] += 1
        page_count_total += page_count or 0
        layout_tables = (metadata_candidates or {}).get("layout_tables") or {}
        candidate_count = layout_tables.get("candidate_count", 0)
        if isinstance(candidate_count, int) and not isinstance(candidate_count, bool):
            layout_table_candidate_count += max(0, candidate_count)
            documents_with_layout_tables += int(candidate_count > 0)

    return {
        "document_count": len(document_ids),
        "latest_extraction_statuses": dict(sorted(status_counts.items())),
        "latest_extraction_page_count_total": page_count_total,
        "documents_with_layout_table_candidates": documents_with_layout_tables,
        "layout_table_candidate_count": layout_table_candidate_count,
    }


def _checkpoint_path(name: str = CHECKPOINT_NAME) -> Path:
    root = Path(getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))).resolve()
    if not root.is_dir():
        raise CommandError("A raiz QA isolada não está disponível.")
    if name not in {CHECKPOINT_NAME, SAPL_DATE_CHECKPOINT_NAME}:
        raise CommandError("Nome de checkpoint QA não permitido.")
    return root / name


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


def _publication_ordered_candidate_rows(qa_root: Path):
    from src.processing.archive_sapl_crosswalk import rank_archive_candidates_by_publication

    crosswalk_path = qa_root / "sapl-archive-crosswalk-cursor.json"
    try:
        crosswalk = json.loads(crosswalk_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise CommandError("Crosswalk SAPL completo não está disponível no QA.") from exc
    if (
        crosswalk.get("schema_version") != 1
        or crosswalk.get("complete") is not True
        or len(crosswalk.get("records") or []) != crosswalk.get("total_entries")
    ):
        raise CommandError("Crosswalk SAPL incompleto/inconsistente; não ordenarei por data.")

    documents = list(
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .exclude(storage_key="")
        .exclude(content_sha256="")
        .values_list("pk", "public_id", "original_filename", "storage_key", "content_sha256", "size_bytes")
    )
    archive_rows = [
        {
            "document_id": pk,
            "public_id": public_id,
            "filename": filename,
            "storage_key": storage_key,
            "content_sha256": content_sha256,
            "size_bytes": size_bytes,
        }
        for pk, public_id, filename, storage_key, content_sha256, size_bytes in documents
    ]
    ranked = rank_archive_candidates_by_publication(
        archive_rows,
        crosswalk["records"],
        {int(key): value for key, value in crosswalk["type_labels"].items()},
    )
    document_ids = [item["document_id"] for item in ranked]
    current_extraction_pairs = set(
        ExtracaoDocumento.objects.filter(
            documento_id__in=document_ids,
            extractor_version__startswith="pymupdf-",
            policy_fingerprint=_current_extraction_policy_fingerprint(),
            quality_json__pipeline_candidate_only=True,
        ).values_list("documento_id", "documento__public_id")
    )
    current_public_ids = {str(public_id) for _, public_id in current_extraction_pairs}
    rows = [
        (item["public_id"], item["storage_key"], item["content_sha256"], item["size_bytes"])
        for item in ranked
    ]
    ordering_fingerprint_fields = [
        item["publication_date"] or f"fallback:{item['act_year']}:{item['act_number']}"
        for item in ranked
    ]
    summary = {
        "matched_one_to_one_candidates": len(ranked),
        "candidates_with_sapl_publication_date": sum(bool(item["publication_date"]) for item in ranked),
        "candidates_using_year_number_fallback": sum(not item["publication_date"] for item in ranked),
        "already_currently_extracted_in_stable_queue": len(current_public_ids),
        "catalog_scan_complete": True,
    }
    return rows, ordering_fingerprint_fields, summary


class Command(BaseCommand):
    help = "Extrai PDFs locais em lotes retomáveis, sempre como candidatos pendentes de revisão QA."

    def add_arguments(self, parser):
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument("--batch-size", type=int, default=10)
        parser.add_argument("--resume", action="store_true")
        parser.add_argument("--publication-order", action="store_true")

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE")
            not in {
                "config.settings_normative_qa",
                "config.settings_normative_container_qa",
            }
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o ambiente QA normativo isolado.")
        batch_size = options["batch_size"]
        if not 1 <= batch_size <= 10:
            raise CommandError("--batch-size deve estar entre 1 e 10.")
        if options["resume"] and not (options["apply"] or options["dry_run"]):
            raise CommandError("--resume exige --apply ou --dry-run.")

        publication_order = options["publication_order"]
        ordering = (
            "SAPL:data_publicacao-desc;fallback=ano,numero"
            if publication_order
            else "public_id"
        )
        checkpoint_name = SAPL_DATE_CHECKPOINT_NAME if publication_order else CHECKPOINT_NAME
        checkpoint_path = _checkpoint_path(checkpoint_name)
        exists = checkpoint_path.exists()
        if options["apply"] and exists != options["resume"]:
            raise CommandError(
                "Checkpoint existente exige --resume; sem checkpoint, inicie sem --resume."
            )
        if options["resume"] and not exists:
            raise CommandError("Não existe checkpoint QA para retomar.")

        qa_root = Path(getattr(settings, "QA_ROOT", os.environ["JURIX_QA_ROOT"])).resolve()
        ordering_summary = None
        if publication_order:
            rows, ordering_fingerprint_fields, ordering_summary = _publication_ordered_candidate_rows(qa_root)
            fingerprint = _universe_fingerprint(
                [(*row, order_field) for row, order_field in zip(rows, ordering_fingerprint_fields, strict=True)]
            )
        else:
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
                or checkpoint.get("ordering", "public_id") != ordering
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
                "failed_attempts": 0,
                "status": "pending",
                "ordering": ordering,
            }
        checkpoint.setdefault("failed_attempts", 0)

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
            document_id = DocumentoNormativo.objects.filter(public_id=public_id).values_list(
                "pk", flat=True
            ).first()
            if _has_current_pipeline_extraction(document_id):
                existing_extractions += 1

        if options["dry_run"]:
            self.stdout.write(
                json.dumps(
                    {
                        "mode": "dry-run",
                        "ordering": ordering,
                        "ordering_summary": ordering_summary,
                        "batch_size": batch_size,
                        "cursor": start,
                        "batch_candidates": len(batch),
                        "universe_candidates": len(rows),
                        "current_policy_extractions_in_batch": existing_extractions,
                        "legacy_or_staging_extractions_to_refresh": len(batch) - existing_extractions,
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
            if _has_current_pipeline_extraction(document.pk):
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
                    checkpoint["failed_attempts"] += 1
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
                                "batch_processed_before_failure": index - start,
                                "batch_failure_count": 1,
                                "failed_attempts_total": checkpoint["failed_attempts"],
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

        batch_summary = _batch_extraction_summary(
            [public_id for public_id, _storage_key, _sha256, _size in batch]
        )
        self.stdout.write(
            json.dumps(
                {
                    "mode": "apply",
                    "status": checkpoint["status"],
                    "ordering": ordering,
                    "ordering_summary": ordering_summary,
                    "batch_processed": len(batch),
                    "batch_failure_count": 0,
                    "batch_summary": batch_summary,
                    "cursor": checkpoint["cursor"],
                    "universe_candidates": len(rows),
                    "candidate_extractions_created_total": checkpoint["created"],
                    "skipped_existing_total": checkpoint["skipped_existing"],
                    "failed_attempts_total": checkpoint["failed_attempts"],
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
