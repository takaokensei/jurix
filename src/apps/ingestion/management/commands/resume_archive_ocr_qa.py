"""Resume a small batch of OCR-skipped or unreadable pages for a pending QA PDF."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import UUID

import fitz
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import OuterRef, Subquery

from src.apps.ingestion.management.commands.extract_archive_candidates_batch_qa import (
    _verified_pdf,
)
from src.apps.ingestion.normative_tasks import _extract_archive_candidate
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.processing.document_extraction import page_has_image, page_is_blank

MAX_BATCH_PAGES = 10
OCR_TIMEOUT_SECONDS = 15
MAX_PDF_PAGES = 500


class Command(BaseCommand):
    help = "Retoma OCR omitido por orçamento em um único PDF pendente do QA, sem aceitar a extração."

    def add_arguments(self, parser):
        selector = parser.add_mutually_exclusive_group(required=True)
        selector.add_argument("--document-id", help="UUID do candidato no staging QA.")
        selector.add_argument(
            "--pick-next",
            action="store_true",
            help="Somente no dry-run: selecionar o menor backlog OCR elegível, sem gravar dados.",
        )
        selector.add_argument(
            "--pick-unreadable",
            action="store_true",
            help="Somente no dry-run: selecionar o menor backlog de páginas ilegíveis, sem gravar dados.",
        )
        parser.add_argument("--batch-pages", type=int, default=MAX_BATCH_PAGES)
        mode = parser.add_mutually_exclusive_group(required=True)
        mode.add_argument("--dry-run", action="store_true")
        mode.add_argument("--apply", action="store_true")
        parser.add_argument(
            "--retry-unreadable",
            action="store_true",
            help="Retenta somente páginas marcadas ilegíveis na última extração QA.",
        )
        parser.add_argument(
            "--reclassify-blank",
            action="store_true",
            help="Reprocessa um PDF QA sem OCR somente se todas as páginas ilegíveis forem realmente vazias.",
        )

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o ambiente QA normativo isolado.")

        batch_pages = options["batch_pages"]
        if not 1 <= batch_pages <= MAX_BATCH_PAGES:
            raise CommandError(f"--batch-pages deve estar entre 1 e {MAX_BATCH_PAGES}.")
        if (options["pick_next"] or options["pick_unreadable"]) and not options["dry_run"]:
            raise CommandError("--pick-next e --pick-unreadable são permitidos somente em --dry-run.")
        if options["pick_next"] and options["retry_unreadable"]:
            raise CommandError("--pick-next seleciona backlog de orçamento; remova --retry-unreadable.")
        if options["pick_unreadable"] and options["retry_unreadable"]:
            raise CommandError("--pick-unreadable já seleciona páginas ilegíveis; remova --retry-unreadable.")
        if options["reclassify_blank"] and (
            options["pick_next"] or options["pick_unreadable"] or options["retry_unreadable"]
        ):
            raise CommandError("--reclassify-blank exige --document-id e não pode combinar opções de retry.")

        if options["pick_next"] or options["pick_unreadable"]:
            latest = ExtracaoDocumento.objects.filter(documento_id=OuterRef("pk")).order_by(
                "-created_at", "-pk"
            )
            pending = DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
                accepted_extraction__isnull=True,
            ).exclude(storage_key="").exclude(content_sha256="")
            choices = []
            for public_id, quality in pending.annotate(
                latest_status=Subquery(latest.values("status")[:1]),
                latest_quality=Subquery(latest.values("quality_json")[:1]),
            ).filter(
                latest_status__in=(ExtracaoDocumento.Status.PARTIAL, ExtracaoDocumento.Status.UNREADABLE)
            ).values_list("public_id", "latest_quality").iterator(chunk_size=100):
                details = quality if isinstance(quality, dict) else {}
                page_field = (
                    "unreadable_pages" if options["pick_unreadable"] else "ocr_budget_skipped_pages"
                )
                skipped = details.get(page_field)
                if isinstance(skipped, list):
                    pages = sorted({page for page in skipped if type(page) is int and page > 0})
                    if pages:
                        choices.append((len(pages), str(public_id), public_id))
            if not choices:
                reason = "páginas ilegíveis" if options["pick_unreadable"] else "backlog de OCR por orçamento"
                raise CommandError(f"Nenhum candidato pendente tem {reason}.")
            _count, _sort_key, document_id = min(choices)
        else:
            try:
                document_id = UUID(options["document_id"])
            except (TypeError, ValueError, AttributeError) as exc:
                raise CommandError("--document-id precisa ser um UUID válido.") from exc

        try:
            document = DocumentoNormativo.objects.get(public_id=document_id)
        except DocumentoNormativo.DoesNotExist as exc:
            raise CommandError("Documento candidato não encontrado no banco QA.") from exc
        if (
            document.source_kind != DocumentoNormativo.SourceKind.ARCHIVE
            or not document.storage_key
            or not document.content_sha256
            or document.accepted_extraction_id is not None
            or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
        ):
            raise CommandError("A retomada exige PDF staging pendente e ainda não aceito.")

        latest = document.extracoes.order_by("-created_at", "-pk").first()
        if latest is None:
            raise CommandError("A retomada exige uma extração incompleta anterior.")
        if latest.status == ExtracaoDocumento.Status.COMPLETE:
            self.stdout.write(json.dumps({
                "mode": "noop",
                "reason": "latest_extraction_complete",
                "document_id": str(document.public_id),
                "extraction_id": latest.pk,
                "review_status": document.review_status,
                "accepted_extraction": document.accepted_extraction_id is not None,
                "norma_linkage_created": False,
            }, ensure_ascii=False, sort_keys=True))
            return
        if latest.status not in {
            ExtracaoDocumento.Status.PARTIAL,
            ExtracaoDocumento.Status.UNREADABLE,
        }:
            raise CommandError("A retomada exige uma extração incompleta anterior.")
        quality = latest.quality_json if isinstance(latest.quality_json, dict) else {}
        retry_unreadable = options["retry_unreadable"] or options["pick_unreadable"] or options["reclassify_blank"]
        page_field = "unreadable_pages" if retry_unreadable else "ocr_budget_skipped_pages"
        page_values = quality.get(page_field)
        if not isinstance(page_values, list):
            page_values = []
        retry_pages = sorted(
            {page for page in page_values if type(page) is int and page > 0}
        )
        if not retry_pages:
            reason = "ilegíveis" if retry_unreadable else "omitidas pelo orçamento OCR"
            raise CommandError(f"A extração mais recente não tem páginas {reason}.")

        qa_root = Path(os.environ.get("JURIX_QA_ROOT", "")).resolve()
        pdf_path = _verified_pdf(
            qa_root,
            document.storage_key,
            document.content_sha256,
        )
        with fitz.open(pdf_path) as pdf:
            page_count = len(pdf)
            if options["reclassify_blank"]:
                for page_number in retry_pages:
                    if page_number > page_count or not page_is_blank(
                        pdf[page_number - 1],
                        pdf[page_number - 1].get_text("text") or "",
                        page_has_image(pdf[page_number - 1]),
                    ):
                        raise CommandError(
                            "Reclassificação cancelada: existe página ilegível com conteúdo; use retry OCR revisável."
                        )
        if page_count > MAX_PDF_PAGES:
            raise CommandError(f"PDF excede o limite seguro de {MAX_PDF_PAGES} páginas.")
        if retry_pages[-1] > page_count:
            raise CommandError("Metadados de páginas para retomada excedem o PDF verificado.")

        selected_pages = [] if options["reclassify_blank"] else retry_pages[:batch_pages]
        if options["dry_run"]:
            self.stdout.write(json.dumps({
                "mode": "dry-run",
                "retry_kind": "blank_reclassification" if options["reclassify_blank"] else "unreadable" if retry_unreadable else "ocr_budget",
                "selection": (
                    "smallest_unreadable_backlog" if options["pick_unreadable"]
                    else "smallest_pending_backlog" if options["pick_next"]
                    else "explicit_document"
                ),
                "document_id": str(document.public_id),
                "source_extraction_sha256": latest.extraction_sha256,
                "pdf_pages": page_count,
                "retry_backlog_pages": len(retry_pages),
                "selected_pages": selected_pages,
                "max_ocr_calls": 0 if options["reclassify_blank"] else batch_pages,
                "ocr_timeout_seconds": OCR_TIMEOUT_SECONDS,
                "checkpoint": "immutable extraction versions in QA database",
                "will_accept_or_promote": False,
            }, ensure_ascii=False, sort_keys=True))
            return

        with transaction.atomic():
            extraction_options = {
                "max_pages": MAX_PDF_PAGES,
                "max_ocr_pages": 0 if options["reclassify_blank"] else batch_pages,
                "ocr_timeout_seconds": OCR_TIMEOUT_SECONDS,
                "reuse_from": latest,
            }
            if not options["reclassify_blank"]:
                extraction_options["ocr_pages_to_process"] = set(selected_pages)
            candidate = _extract_archive_candidate(document, **extraction_options)
        document.refresh_from_db()
        new_quality = candidate.quality_json if isinstance(candidate.quality_json, dict) else {}
        remaining = new_quality.get("ocr_budget_skipped_pages")
        self.stdout.write(json.dumps({
            "mode": "apply",
            "retry_kind": "blank_reclassification" if options["reclassify_blank"] else "unreadable" if retry_unreadable else "ocr_budget",
            "document_id": str(document.public_id),
            "extraction_id": candidate.pk,
            "extraction_status": candidate.status,
            "ocr_pages_attempted": len(new_quality.get("ocr_pages_attempted", [])),
            "ocr_pages_reused": len(new_quality.get("ocr_pages_reused", [])),
            "remaining_budget_skipped_pages": len(remaining) if isinstance(remaining, list) else 0,
            "remaining_unreadable_pages": len(new_quality.get("unreadable_pages", [])),
            "blank_pages": new_quality.get("blank_pages", []),
            "review_status": document.review_status,
            "accepted_extraction": document.accepted_extraction_id is not None,
            "norma_linkage_created": False,
        }, ensure_ascii=False, sort_keys=True))
