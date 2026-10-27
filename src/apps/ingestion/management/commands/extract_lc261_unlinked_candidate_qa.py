"""Extract the exact, unlinked LC 261/2025 SAPL candidate in isolated QA."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.normative_tasks import _extract_archive_candidate
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma

_IDENTITY = "BR-RN-NATAL|lei_complementar|municipal_lc|261|2025"
_PDF_URL = "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2025/8823/lei_complementar_no_261_2025.pdf"


class Command(BaseCommand):
    help = "Extrai a LC 261/2025 oficial sem associar, aceitar ou consolidar o conteúdo."

    def handle(self, *args, **options):
        database = settings.DATABASES.get("default", {})
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or database.get("HOST") != "127.0.0.1"
            or str(database.get("PORT")) != "55432"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("extração disponível somente no PostgreSQL QA isolado :55432")

        candidates = list(
            DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.SAPL,
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
                accepted_extraction__isnull=True,
                norma__isnull=True,
                source_ref__startswith="sapl-unlinked-v2:8823:sha256:",
                metadata_json__sapl_id=8823,
                metadata_json__identity_status="candidate",
                metadata_json__identity_key=_IDENTITY,
                metadata_json__identity_key_candidate=_IDENTITY,
                metadata_json__source_provenance__kind="sapl_norma_pdf",
                metadata_json__source_provenance__official_url=_PDF_URL,
                metadata_json__association_status="identity_conflict_unlinked",
            ).order_by("-created_at", "-pk")[:2]
        )
        if len(candidates) != 1:
            raise CommandError("esperava exatamente um PDF QA pendente e desacoplado da LC 261/2025")
        document = candidates[0]
        if not document.storage_key:
            raise CommandError("o candidato SAPL não possui PDF armazenado no QA")

        norma = Norma.objects.filter(sapl_id=8823).first()
        if (
            norma is None
            or norma.identity_key == _IDENTITY
            or norma.tipo != "Lei Complementar"
            or norma.numero != "261"
            or norma.ano != 2025
            or norma.pdf_url != _PDF_URL
            or norma.status != Norma.Status.PENDING
            or norma.documento_base_id is not None
            or norma.texto_original
            or norma.texto_consolidado
        ):
            raise CommandError("o registro Norma não corresponde ao conflito QA previamente inspecionado")

        extraction = (
            document.extracoes.filter(status=ExtracaoDocumento.Status.COMPLETE)
            .order_by("-created_at", "-pk")
            .first()
        )
        if extraction is None:
            extraction = _extract_archive_candidate(
                document,
                max_pages=400,
                max_ocr_pages=0,
                ocr_timeout_seconds=15,
            )
        document.refresh_from_db()
        if (
            extraction.status != ExtracaoDocumento.Status.COMPLETE
            or document.norma_id is not None
            or document.accepted_extraction_id is not None
            or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
        ):
            raise CommandError("a extração falhou ou deixou o estado de revisão pendente")

        self.stdout.write(
            json.dumps(
                {
                    "document_id": str(document.public_id),
                    "extraction_id": extraction.pk,
                    "extraction_status": extraction.status,
                    "page_count": extraction.page_count,
                    "review_status": document.review_status,
                    "norma_linked": document.norma_id is not None,
                    "text_accepted": document.accepted_extraction_id == extraction.pk,
                    "consolidation_created": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
