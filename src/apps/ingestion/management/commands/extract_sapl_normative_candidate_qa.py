"""Extract one pending SAPL PDF candidate from the isolated host QA storage."""

from __future__ import annotations

import json
import os
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.normative_tasks import _extract_archive_candidate
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma


def _quality_summary(extraction: ExtracaoDocumento) -> dict[str, int]:
    quality = extraction.quality_json if isinstance(extraction.quality_json, dict) else {}
    methods = quality.get("page_methods")
    methods = methods if isinstance(methods, dict) else {}
    metadata = (
        extraction.metadata_candidates_json
        if isinstance(extraction.metadata_candidates_json, dict)
        else {}
    )
    tables = metadata.get("layout_tables")
    tables = tables if isinstance(tables, dict) else {}
    unreadable = quality.get("unreadable_pages")
    unreadable_count = len(unreadable) if isinstance(unreadable, list) else 0
    skipped = quality.get("ocr_budget_skipped_pages")
    skipped_count = len(skipped) if isinstance(skipped, list) else 0
    attempted = quality.get("ocr_pages_attempted")
    attempted_count = len(attempted) if isinstance(attempted, list) else 0
    return {
        "native_pages": int(methods.get("native", 0) or 0),
        "ocr_pages": int(methods.get("ocr", 0) or 0),
        "blank_pages": int(methods.get("blank", 0) or 0),
        "unreadable_pages": unreadable_count,
        "ocr_attempted_pages": attempted_count,
        "ocr_budget_skipped_pages": skipped_count,
        "layout_table_candidates": int(tables.get("candidate_count", 0) or 0),
    }


class Command(BaseCommand):
    help = "Extract one pending SAPL PDF candidate stored in the host QA root."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", required=True)
        parser.add_argument("--max-pages", type=int, default=400)
        parser.add_argument("--max-ocr-pages", type=int, default=0)
        parser.add_argument("--ocr-timeout-seconds", type=int, default=15)

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o runner QA normativo do host.")
        try:
            document_id = UUID(options["document_id"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise CommandError("--document-id precisa ser um UUID válido.") from exc
        if not 0 <= options["max_ocr_pages"] <= 10:
            raise CommandError("--max-ocr-pages deve ficar entre 0 e 10.")
        if not 1 <= options["max_pages"] <= 500:
            raise CommandError("--max-pages deve ficar entre 1 e 500.")
        if not 1 <= options["ocr_timeout_seconds"] <= 30:
            raise CommandError("--ocr-timeout-seconds deve ficar entre 1 e 30.")

        try:
            document = DocumentoNormativo.objects.select_related("norma").get(
                public_id=document_id
            )
        except DocumentoNormativo.DoesNotExist as exc:
            raise CommandError("Documento SAPL candidato não encontrado no banco QA.") from exc
        if (
            document.source_kind != DocumentoNormativo.SourceKind.SAPL
            or not document.storage_key
            or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
            or document.accepted_extraction_id is not None
            or not document.norma_id
            or document.norma.status != Norma.Status.PENDING
            or document.norma.documento_base_id is not None
            or document.norma.texto_original
            or document.norma.texto_consolidado
        ):
            raise CommandError("Somente PDF SAPL pendente vinculado a Norma QA vazia pode ser extraído.")

        extraction = _extract_archive_candidate(
            document,
            max_pages=options["max_pages"],
            max_ocr_pages=options["max_ocr_pages"],
            ocr_timeout_seconds=options["ocr_timeout_seconds"],
        )
        document.refresh_from_db()
        self.stdout.write(
            json.dumps(
                {
                    "document_id": str(document.public_id),
                    "extraction_id": extraction.pk,
                    "extraction_status": extraction.status,
                    "page_count": extraction.page_count,
                    "quality_summary": _quality_summary(extraction),
                    "document_review_status": document.review_status,
                    "norma_status": document.norma.status,
                    "text_accepted": document.accepted_extraction_id == extraction.pk,
                    "norma_linked_as_base": document.norma.documento_base_id == document.pk,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
