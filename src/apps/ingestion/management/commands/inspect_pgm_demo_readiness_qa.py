"""Read-only, privacy-minimal readiness report for the PGM CTM demo."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Reports CTM demo source availability without emitting legal text or changing records."

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE")
            not in {"config.settings_normative_qa", "config.settings_normative_container_qa"}
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
            or not getattr(settings, "PGM_CONSOLIDATION_DEMO_ENABLED", False)
        ):
            raise CommandError("A inspeção da demo PGM exige o perfil isolado QA habilitado.")

        from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
        from src.apps.legislation.models import Norma
        from src.apps.legislation.workspace_views import (
            _pgm_ctm_art20_candidate_timeline,
            _pgm_document_pdf_url,
            _pgm_lc55_chain_candidate,
            _pgm_paragraph_evidence,
        )

        timeline = _pgm_ctm_art20_candidate_timeline()
        rows = []
        for item in timeline["rows"]:
            evidence = item.get("evidence")
            evidence = evidence if isinstance(evidence, dict) else {}
            rows.append(
                {
                    "key": item.get("key"),
                    "label": item.get("label"),
                    "state": item.get("state"),
                    "has_article_text": bool(evidence.get("quote")),
                    "page": evidence.get("page"),
                    "has_local_pdf": bool(item.get("pdf_url")),
                    "has_official_pdf": bool(item.get("official_pdf_url")),
                    "has_relation_evidence": bool(item.get("relation_evidence")),
                }
            )

        lc55_identity = "BR-RN-NATAL|lei_complementar|municipal_lc|55|2004"
        lc55_rows = []
        for key, label, role in (
            ("lc55_original", "Original promulgado", DocumentoNormativo.Role.ORIGINAL),
            ("lc55_2019_snapshot", "Compilação julho/2019", DocumentoNormativo.Role.UNDETERMINED),
        ):
            evidence = _pgm_lc55_chain_candidate(
                lc55_identity, "34", label, role=role
            )
            document = evidence.get("document")
            extraction = evidence.get("extraction")
            lc55_rows.append(
                {
                    "key": key,
                    "state": evidence.get("state"),
                    "candidate_count": DocumentoNormativo.objects.filter(
                        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                        metadata_json__identity_key=lc55_identity,
                        review_status=DocumentoNormativo.ReviewStatus.PENDING,
                        accepted_extraction__isnull=True,
                        role=role,
                    ).count(),
                    "has_article_34_text": bool((evidence.get("evidence") or {}).get("quote")),
                    "page": (evidence.get("evidence") or {}).get("page"),
                    "latest_complete_extraction": bool(extraction),
                    "latest_extraction_status": (
                        document.extracoes.order_by("-created_at", "-pk").values_list("status", flat=True).first()
                        if document
                        else None
                    ),
                }
            )

        lc208_identity = "BR-RN-NATAL|lei_complementar|municipal_lc|208|2022"
        lc208_document = (
            DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.SAPL,
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
                accepted_extraction__isnull=True,
                norma__isnull=True,
                metadata_json__sapl_id=1160,
                metadata_json__identity_status="candidate",
                metadata_json__identity_key=lc208_identity,
                metadata_json__identity_key_candidate=lc208_identity,
                metadata_json__source_provenance__kind="sapl_norma_pdf",
                metadata_json__association_status="identity_conflict_unlinked",
            )
            .order_by("created_at", "pk")
            .first()
        )
        lc208_extraction = (
            lc208_document.extracoes.filter(status=ExtracaoDocumento.Status.COMPLETE)
            .order_by("-created_at", "-pk")
            .first()
            if lc208_document
            else None
        )
        lc208_paragraph = _pgm_paragraph_evidence(lc208_extraction, "18", "2")

        self.stdout.write(
            json.dumps(
                {
                    "mode": "read-only",
                    "target": "CTM · Lei nº 3.882/1989, Art. 20 × LC nº 271/2025",
                    "timeline_complete": timeline["complete"],
                    "snapshot_texts_match": timeline["snapshot_texts_match"],
                    "amendment_differs_from_2024": timeline["amendment_differs_from_2024"],
                    "rows": rows,
                    "lc55_chain": lc55_rows,
                    "lc208_unlinked_candidate": {
                        "candidate_count": DocumentoNormativo.objects.filter(
                            source_kind=DocumentoNormativo.SourceKind.SAPL,
                            review_status=DocumentoNormativo.ReviewStatus.PENDING,
                            accepted_extraction__isnull=True,
                            norma__isnull=True,
                            metadata_json__sapl_id=1160,
                            metadata_json__association_status="identity_conflict_unlinked",
                        ).count(),
                        "has_complete_extraction": bool(lc208_extraction),
                        "has_article_18_paragraph_2": bool(lc208_paragraph),
                        "page": lc208_paragraph.get("page") if lc208_paragraph else None,
                        "has_local_pdf_url": bool(
                            _pgm_document_pdf_url(
                                lc208_document,
                                lc208_paragraph["page"] if lc208_paragraph else None,
                            )
                        ) if lc208_document else False,
                        "existing_norma_identity_conflict": Norma.objects.filter(
                            sapl_id=1160
                        ).exclude(identity_key=lc208_identity).exists(),
                    },
                    "legal_review_performed": False,
                    "database_writes_performed": False,
                    "interpretation": (
                        "Availability and extraction-state diagnostics only; no candidate identity, "
                        "vigency, legal effect, or consolidated wording is confirmed."
                    ),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
