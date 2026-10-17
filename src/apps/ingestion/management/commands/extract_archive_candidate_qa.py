"""Extract exactly one verified archive PDF into a QA-only review candidate."""

from __future__ import annotations

import json
import os
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.normative_tasks import _extract_archive_candidate, _reusable_ocr_pages
from src.apps.legislation.document_models import DocumentoNormativo


class Command(BaseCommand):
    help = "Extrai um único PDF de staging e deixa o resultado aguardando revisão humana no QA."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", required=True, help="UUID do candidato no staging QA.")
        parser.add_argument(
            "--max-ocr-pages",
            type=int,
            default=0,
            help="Máximo de páginas OCR nesta extração (0 a 10; padrão 0).",
        )
        parser.add_argument(
            "--ocr-timeout-seconds",
            type=int,
            default=15,
            help="Timeout por página OCR (1 a 30 segundos; padrão 15).",
        )
        parser.add_argument(
            "--layout-pages",
            type=int,
            nargs="+",
            help=(
                "Até 10 páginas com OCR anterior verificável para gerar somente prévias "
                "tabulares raster no staging QA; não reexecuta nem substitui o texto OCR."
            ),
        )
        parser.add_argument(
            "--ocr-page",
            type=int,
            help="Força OCR em uma única página previamente autorizada pelo guard QA.",
        )

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") not in {
                "config.settings_normative_qa",
                "config.settings_normative_container_qa",
            }
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o ambiente QA normativo isolado.")

        try:
            document_id = UUID(options["document_id"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise CommandError("--document-id precisa ser um UUID válido.") from exc
        if not 0 <= options["max_ocr_pages"] <= 10:
            raise CommandError("--max-ocr-pages deve ficar entre 0 e 10.")
        if not 1 <= options["ocr_timeout_seconds"] <= 30:
            raise CommandError("--ocr-timeout-seconds deve ficar entre 1 e 30.")
        layout_pages = options["layout_pages"]
        ocr_page = options.get("ocr_page")
        if ocr_page is not None and (
            document_id != UUID("cb810b42-ecea-4cbc-870a-b2581c30df6c")
            or ocr_page != 7
            or options["max_ocr_pages"] != 1
        ):
            raise CommandError(
                "OCR explícito está restrito à página 7 do PDF QA da LC 271/2025, orçamento 1."
            )
        if layout_pages is not None and (
            options["max_ocr_pages"] != 0
            or len(layout_pages) > 10
            or len(set(layout_pages)) != len(layout_pages)
            or any(page < 1 for page in layout_pages)
        ):
            raise CommandError(
                "--layout-pages exige --max-ocr-pages 0 e até 10 páginas positivas distintas."
            )

        try:
            document = DocumentoNormativo.objects.select_related("norma").get(public_id=document_id)
        except DocumentoNormativo.DoesNotExist as exc:
            raise CommandError("Documento candidato não encontrado no banco QA.") from exc

        if (
            document.source_kind
            not in {
                DocumentoNormativo.SourceKind.ARCHIVE,
                DocumentoNormativo.SourceKind.SAPL,
            }
            or not document.storage_key
            or not document.content_sha256
            or document.accepted_extraction_id is not None
            or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
        ):
            raise CommandError("A extração exige um PDF staging pendente e ainda não aceito.")

        before = document.extracoes.count()
        reuse_from = next(
            (
                prior
                for prior in document.extracoes.order_by("-created_at", "-pk").iterator()
                if _reusable_ocr_pages(prior)
            ),
            None,
        )
        if layout_pages is not None:
            reusable_pages = _reusable_ocr_pages(reuse_from) if reuse_from else {}
            if not set(layout_pages).issubset(reusable_pages):
                raise CommandError(
                    "--layout-pages só pode selecionar páginas com OCR anterior verificável."
                )
        extraction = _extract_archive_candidate(
            document,
            max_ocr_pages=options["max_ocr_pages"],
            ocr_timeout_seconds=options["ocr_timeout_seconds"],
            ocr_pages_to_process={ocr_page} if ocr_page is not None else None,
            raster_table_pages_to_process=set(layout_pages) if layout_pages is not None else None,
            reuse_from=reuse_from,
        )
        document.refresh_from_db()
        quality = extraction.quality_json if isinstance(extraction.quality_json, dict) else {}

        self.stdout.write(
            json.dumps(
                {
                    "document_id": str(document.pk),
                    "extraction_id": extraction.pk,
                    "extraction_status": extraction.status,
                    "candidate_created": document.extracoes.count() > before,
                    "ocr_pages_attempted": len(quality.get("ocr_pages_attempted", [])),
                    "ocr_pages_reused": len(quality.get("ocr_pages_reused", [])),
                    "ocr_budget_skipped_pages": len(quality.get("ocr_budget_skipped_pages", [])),
                    "raster_table_pages_requested": layout_pages or [],
                    "layout_table_candidate_count": (
                        extraction.metadata_candidates_json.get("layout_tables", {}).get(
                            "candidate_count", 0
                        )
                        if isinstance(extraction.metadata_candidates_json, dict)
                        else 0
                    ),
                    "document_review_status": document.review_status,
                    "text_accepted": document.accepted_extraction_id == extraction.pk,
                    "norma_linked": document.norma_id is not None,
                    "queued": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
