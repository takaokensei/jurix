"""Extract exactly one verified archive PDF into a QA-only review candidate."""

from __future__ import annotations

import json
import os
from uuid import UUID

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.normative_tasks import _extract_archive_candidate
from src.apps.legislation.document_models import DocumentoNormativo


class Command(BaseCommand):
    help = "Extrai um único PDF de staging e deixa o resultado aguardando revisão humana no QA."

    def add_arguments(self, parser):
        parser.add_argument("--document-id", required=True, help="UUID do candidato no staging QA.")

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o ambiente QA normativo isolado.")

        try:
            document_id = UUID(options["document_id"])
        except (TypeError, ValueError, AttributeError) as exc:
            raise CommandError("--document-id precisa ser um UUID válido.") from exc

        try:
            document = DocumentoNormativo.objects.select_related("norma").get(public_id=document_id)
        except DocumentoNormativo.DoesNotExist as exc:
            raise CommandError("Documento candidato não encontrado no banco QA.") from exc

        if (
            document.source_kind != DocumentoNormativo.SourceKind.ARCHIVE
            or not document.storage_key
            or not document.content_sha256
            or document.accepted_extraction_id is not None
            or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
        ):
            raise CommandError("A extração exige um PDF staging pendente e ainda não aceito.")

        before = document.extracoes.count()
        extraction = _extract_archive_candidate(document)
        document.refresh_from_db()

        self.stdout.write(
            json.dumps(
                {
                    "document_id": str(document.pk),
                    "extraction_id": extraction.pk,
                    "extraction_status": extraction.status,
                    "candidate_created": document.extracoes.count() > before,
                    "document_review_status": document.review_status,
                    "text_accepted": document.accepted_extraction_id == extraction.pk,
                    "norma_linked": document.norma_id is not None,
                    "queued": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
