"""Read-only timeline of documentary relation candidates for CTM Art. 20."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.document_models import (
    DocumentoNormativo,
    EventoNormativoCandidato,
)
from src.processing.document_metadata import (
    is_natal_municipal_jurisdiction,
    normalize_document_number,
)
from src.processing.normative_reference import canonical_type


def _candidate_row(candidate: EventoNormativoCandidato) -> dict | None:
    document = candidate.extracao.documento
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
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
        return None
    if not is_natal_municipal_jurisdiction(str(identity.get("jurisdiction") or "")):
        return None

    target = candidate.target_reference_json
    target = target if isinstance(target, dict) else {}
    if (
        normalize_document_number(str(target.get("number_candidate") or "")) != "3882"
        or str(target.get("year_candidate") or "") != "1989"
        or canonical_type(str(target.get("type_candidate") or "")) != "lei"
        or str(target.get("structural_article_number") or "") != "20"
    ):
        return None

    evidence = candidate.evidence_json if isinstance(candidate.evidence_json, dict) else {}
    edition = metadata.get("edition_candidate")
    edition = edition if isinstance(edition, dict) else {}
    return {
        "source_document_id": str(document.public_id),
        "source_kind": document.source_kind,
        "source_identity": {
            "type": identity.get("type"),
            "number": identity.get("number"),
            "year": identity.get("year"),
        },
        "source_edition": edition.get("declared_value_year"),
        "source_article": candidate.source_device_label,
        "action_candidate": candidate.action,
        "action_quote": str(evidence.get("action_quote") or "")[:300],
        "target_quote": str(evidence.get("target_quote") or "")[:300],
        "action_page": evidence.get("action_page"),
        "target_page": evidence.get("target_page"),
        "source_review_status": document.review_status,
        "source_extraction_status": candidate.extracao.status,
        "relation_review_count": candidate.revisoes.count(),
    }


class Command(BaseCommand):
    help = "Lista menções candidatas ao Art. 20 do CTM no QA, sem alterar registros."

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
        ):
            raise CommandError("Esta inspeção exige o banco isolado do QA normativo.")

        candidates = (
            EventoNormativoCandidato.objects.select_related("extracao", "extracao__documento")
            .filter(
                extracao__documento__source_kind__in=(
                    DocumentoNormativo.SourceKind.ARCHIVE,
                    DocumentoNormativo.SourceKind.SAPL,
                    DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
                )
            )
            .order_by("extracao__documento__collected_at", "pk")
        )
        rows = [row for candidate in candidates if (row := _candidate_row(candidate))]
        rows.sort(
            key=lambda row: (
                str(row["source_identity"].get("year") or ""),
                str(row["source_identity"].get("number") or ""),
                str(row["source_article"]),
                str(row["source_document_id"]),
            )
        )
        self.stdout.write(json.dumps({
            "target": "Lei nº 3.882/1989, Art. 20",
            "candidate_count": len(rows),
            "source_document_count": len({row["source_document_id"] for row in rows}),
            "candidates": rows,
            "interpretation": (
                "Documentary mentions only. Candidate action, identity, text, date and legal effect "
                "remain unadjudicated; no records were changed."
            ),
        }, ensure_ascii=False, sort_keys=True))
