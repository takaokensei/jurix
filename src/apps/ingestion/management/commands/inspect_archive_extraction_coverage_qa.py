"""Read-only, count-only audit of QA archive extraction coverage."""

from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from statistics import median

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, OuterRef, Subquery

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.archive_inventory import sha256_file


def _inventory_content_hashes(qa_root: Path) -> set[str] | None:
    """Load only verified PDF hashes from QA inventory files; never expose names."""
    hashes: set[str] = set()
    paths = [
        path for path in qa_root.glob("archive-inventory-*.jsonl")
        if "pdf-identity" not in path.name and path.is_file()
    ]
    if not paths:
        return None
    for path in paths:
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                try:
                    row = json.loads(line)
                except (json.JSONDecodeError, UnicodeDecodeError):
                    continue
                digest = row.get("content_sha256")
                if (
                    row.get("record_type") == "entry"
                    and row.get("extension") == ".pdf"
                    and row.get("hash_status") == "hashed"
                    and isinstance(digest, str)
                    and len(digest) == 64
                ):
                    hashes.add(digest)
    return hashes


def _incomplete_storage_coverage(
    rows, qa_root: Path, inventory_hashes: set[str] | None
) -> dict[str, int]:
    """Summarize incomplete-document blob integrity without IDs or filenames."""
    result = Counter()
    archive_root = (qa_root / "normative-archive").resolve()
    for storage_key, expected_sha256 in rows:
        result["documents"] += 1
        if inventory_hashes is not None:
            if expected_sha256 in inventory_hashes:
                result["hashes_in_archive_inventory"] += 1
            else:
                result["hashes_absent_from_archive_inventory"] += 1
        path = (archive_root / storage_key).resolve()
        if not path.is_relative_to(archive_root) or not path.is_file():
            result["storage_missing_or_unsafe"] += 1
        elif sha256_file(path) == expected_sha256:
            result["storage_hash_verified"] += 1
        else:
            result["storage_hash_mismatch"] += 1
    return dict(result)


def _incomplete_reason(status: str, quality: object, page_count: object) -> str:
    """Classify incomplete QA extraction metadata without exposing document data."""
    details = quality if isinstance(quality, dict) else {}
    skipped_pages = details.get("ocr_budget_skipped_pages")
    if isinstance(skipped_pages, list) and skipped_pages:
        return "ocr_page_budget_exceeded"
    if details.get("extraction_error"):
        return "pdf_or_extractor_error"
    unreadable_pages = details.get("unreadable_pages")
    methods = details.get("page_methods")
    try:
        unreadable_method_count = int(methods.get("unreadable", 0) or 0) if isinstance(methods, dict) else 0
    except (TypeError, ValueError):
        unreadable_method_count = 0
    if (
        (isinstance(unreadable_pages, list) and unreadable_pages)
        or unreadable_method_count > 0
    ):
        return "unreadable_page_or_ocr_failure"
    if not isinstance(page_count, int) or page_count == 0:
        return "empty_or_unreadable_pdf"
    if status == ExtracaoDocumento.Status.PARTIAL:
        return "other_partial_extraction"
    return "unclassified_incomplete"


def _ocr_budget_workload(skipped_page_counts: list[int]) -> dict[str, object]:
    """Summarize per-document OCR backlog without exposing document identifiers."""
    values = sorted(value for value in skipped_page_counts if value > 0)
    if not values:
        return {
            "documents_with_ocr_backlog": 0,
            "skipped_pages_total": 0,
            "per_document_min": None,
            "per_document_median": None,
            "per_document_p90": None,
            "per_document_max": None,
            "document_buckets": {"1_10": 0, "11_25": 0, "26_50": 0, "51_plus": 0},
        }

    p90_index = max(0, (9 * len(values) + 9) // 10 - 1)
    bucket_counts = Counter(
        "1_10" if value <= 10 else
        "11_25" if value <= 25 else
        "26_50" if value <= 50 else
        "51_plus"
        for value in values
    )
    return {
        "documents_with_ocr_backlog": len(values),
        "skipped_pages_total": sum(values),
        "per_document_min": values[0],
        "per_document_median": median(values),
        "per_document_p90": values[p90_index],
        "per_document_max": values[-1],
        "document_buckets": {
            key: bucket_counts.get(key, 0)
            for key in ("1_10", "11_25", "26_50", "51_plus")
        },
    }


class Command(BaseCommand):
    help = "Compara documentos únicos e versões de extração no acervo QA sem expor conteúdo."

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") not in {
                "config.settings_normative_qa",
                "config.settings_normative_container_qa",
            }
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este diagnóstico somente-leitura exige o ambiente QA normativo isolado.")

        candidates = DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        ).exclude(storage_key="").exclude(content_sha256="")

        per_document = list(
            candidates.annotate(extraction_count=Count("extracoes", distinct=True))
            .values_list("extraction_count", flat=True)
        )
        extraction_count_distribution = Counter(per_document)
        records_by_status = dict(
            ExtracaoDocumento.objects.filter(documento__in=candidates)
            .values("status")
            .annotate(count=Count("pk"))
            .order_by("status")
            .values_list("status", "count")
        )
        latest_extraction = ExtracaoDocumento.objects.filter(
            documento_id=OuterRef("pk")
        ).order_by("-created_at", "-pk")
        latest_by_status = dict(
            candidates.annotate(
                latest_extraction_status=Subquery(latest_extraction.values("status")[:1])
            )
            .values("latest_extraction_status")
            .annotate(count=Count("pk"))
            .order_by("latest_extraction_status")
            .values_list("latest_extraction_status", "count")
        )

        incomplete_rows = candidates.annotate(
            latest_extraction_status=Subquery(latest_extraction.values("status")[:1]),
            latest_quality_json=Subquery(latest_extraction.values("quality_json")[:1]),
            latest_page_count=Subquery(latest_extraction.values("page_count")[:1]),
            latest_policy_fingerprint=Subquery(latest_extraction.values("policy_fingerprint")[:1]),
        ).filter(
            latest_extraction_status__in=(
                ExtracaoDocumento.Status.PARTIAL,
                ExtracaoDocumento.Status.UNREADABLE,
            )
        ).values_list(
            "latest_extraction_status",
            "latest_quality_json",
            "latest_page_count",
            "latest_policy_fingerprint",
            "storage_key",
            "content_sha256",
        )
        incomplete_reason_counts: Counter[str] = Counter()
        incomplete_policy_fingerprints: set[str] = set()
        incomplete_documents_with_ocr_attempts = 0
        incomplete_ocr_budget_skipped_pages = 0
        incomplete_unreadable_pages = 0
        ocr_budget_skipped_counts: list[int] = []
        incomplete_storage_rows = []
        for (
            status,
            quality,
            page_count,
            policy_fingerprint,
            storage_key,
            content_sha256,
        ) in incomplete_rows.iterator(chunk_size=250):
            incomplete_storage_rows.append((storage_key, content_sha256))
            details = quality if isinstance(quality, dict) else {}
            incomplete_reason_counts[_incomplete_reason(status, details, page_count)] += 1
            if policy_fingerprint:
                incomplete_policy_fingerprints.add(str(policy_fingerprint))
            attempted = details.get("ocr_pages_attempted")
            skipped = details.get("ocr_budget_skipped_pages")
            unreadable = details.get("unreadable_pages")
            incomplete_documents_with_ocr_attempts += int(
                isinstance(attempted, list) and bool(attempted)
            )
            incomplete_ocr_budget_skipped_pages += (
                len(skipped) if isinstance(skipped, list) else 0
            )
            if isinstance(skipped, list) and skipped:
                ocr_budget_skipped_counts.append(len(skipped))
            incomplete_unreadable_pages += (
                len(unreadable) if isinstance(unreadable, list) else 0
            )

        document_count = len(per_document)
        documents_with_extractions = sum(
            count for extraction_count, count in extraction_count_distribution.items()
            if extraction_count > 0
        )
        documents_with_multiple_extractions = sum(
            count for extraction_count, count in extraction_count_distribution.items()
            if extraction_count > 1
        )
        extraction_records = sum(records_by_status.values())
        qa_root = Path(
            getattr(settings, "QA_ROOT", os.environ.get("JURIX_QA_ROOT", ""))
        ).resolve()
        inventory_hashes = _inventory_content_hashes(qa_root) if qa_root.is_dir() else None

        self.stdout.write(json.dumps({
            "scope": "pending_archive_candidates_without_accepted_extraction",
            "document_count": document_count,
            "documents_with_extractions": documents_with_extractions,
            "documents_without_extractions": document_count - documents_with_extractions,
            "documents_with_multiple_extractions": documents_with_multiple_extractions,
            "extraction_count_distribution": {
                str(count): documents
                for count, documents in sorted(extraction_count_distribution.items())
            },
            "extraction_record_count": extraction_records,
            "extraction_records_by_status": records_by_status,
            "documents_by_latest_extraction_status": latest_by_status,
            "incomplete_extractions_by_reason": dict(sorted(incomplete_reason_counts.items())),
            "incomplete_documents_with_ocr_attempts": incomplete_documents_with_ocr_attempts,
            "incomplete_ocr_budget_skipped_page_count": incomplete_ocr_budget_skipped_pages,
            "ocr_budget_workload": _ocr_budget_workload(ocr_budget_skipped_counts),
            "incomplete_unreadable_page_count": incomplete_unreadable_pages,
            "incomplete_document_storage_reconciliation": _incomplete_storage_coverage(
                incomplete_storage_rows, qa_root, inventory_hashes
            ),
            "incomplete_policy_variant_count": len(incomplete_policy_fingerprints),
            "records_minus_documents_with_extractions": (
                extraction_records - documents_with_extractions
            ),
            "document_ids_or_content_included": False,
        }, ensure_ascii=False, sort_keys=True))
