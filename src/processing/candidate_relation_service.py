"""Read-only evidence assembly for extracted relations in unreviewed documents.

This service reports candidate text and identity matches only. It deliberately
does not create or confirm normative graph edges.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping

from src.apps.legislation.document_models import DocumentoNormativo, EventoNormativoCandidato
from src.processing.normative_reference import canonical_type, normalize_number
from src.processing.official_urls import safe_official_url


_TYPE_LABELS = {
    "lei": "Lei",
    "lei_complementar": "Lei Complementar",
    "lei_promulgada": "Lei Promulgada",
    "lei_organica": "Lei Orgânica",
}


def classify_identity_candidates(documents, expected_type: str, *, truncated: bool = False) -> dict:
    """Select only a unique exact species; keep conflicting matches visible."""
    exact = [
        document
        for document in documents
        if (document.metadata_json or {}).get("identity_candidate", {}).get("type")
        == expected_type
    ]
    conflicts = [document for document in documents if document not in exact]
    if truncated or len(exact) > 1:
        return {
            "state": "ambiguous",
            "document": None,
            "conflicts": conflicts,
            "ambiguous_candidates": list(documents),
            "candidate_list_truncated": truncated,
        }
    if exact:
        return {
            "state": "candidate",
            "document": exact[0],
            "conflicts": conflicts,
            "ambiguous_candidates": [],
            "candidate_list_truncated": False,
        }
    if conflicts:
        return {
            "state": "identity_conflict",
            "document": None,
            "conflicts": conflicts,
            "ambiguous_candidates": [],
            "candidate_list_truncated": False,
        }
    return {
        "state": "not_found",
        "document": None,
        "conflicts": [],
        "ambiguous_candidates": [],
        "candidate_list_truncated": False,
    }


def build_candidate_relation_evidence(
    extraction,
    *,
    source_pdf_url: str,
    document_pdf_url: Callable,
    pdf_access_required: Callable,
    sapl_registry_records: Mapping | None = None,
) -> list[dict]:
    """Resolve textual targets against candidate identities without asserting effect.

    URL/access policy is injected by the HTTP layer. `sapl_registry_records` is
    optional corroborating catalog metadata, never a substitute for review.
    """
    if extraction is None:
        return []

    candidates = list(
        EventoNormativoCandidato.objects.filter(extracao=extraction, action="REVOGA")
        .order_by("source_structural_key", "pk")
    )
    years = {
        int(candidate.target_reference_json.get("year_candidate"))
        for candidate in candidates
        if str(candidate.target_reference_json.get("year_candidate", "")).isdecimal()
    }
    possible_documents_by_year: dict[int, list[DocumentoNormativo]] = {}
    if years:
        for document in DocumentoNormativo.objects.filter(
            source_kind__in=(
                DocumentoNormativo.SourceKind.ARCHIVE,
                DocumentoNormativo.SourceKind.SAPL,
            ),
            metadata_json__identity_candidate__year__in=sorted(years),
        ).only(
            "id", "public_id", "source_kind", "official_url", "original_filename", "metadata_json"
        ):
            identity = (document.metadata_json or {}).get("identity_candidate") or {}
            try:
                year = int(identity.get("year"))
            except (TypeError, ValueError):
                continue
            possible_documents_by_year.setdefault(year, []).append(document)

    registry_records = sapl_registry_records or {}
    result = []
    for candidate in candidates:
        reference = candidate.target_reference_json or {}
        raw_number = str(reference.get("number_candidate") or "").strip()
        try:
            year = int(reference.get("year_candidate"))
        except (TypeError, ValueError):
            continue
        if not raw_number:
            continue
        number = normalize_number(raw_number)
        expected_type = canonical_type(str(reference.get("type_candidate") or ""))
        matching_documents = [
            document
            for document in possible_documents_by_year.get(year, [])
            if normalize_number(
                str(
                    ((document.metadata_json or {}).get("identity_candidate") or {}).get(
                        "number", ""
                    )
                )
            )
            == number
        ]
        exact_documents = [
            document
            for document in matching_documents
            if canonical_type(
                str(
                    ((document.metadata_json or {}).get("identity_candidate") or {}).get(
                        "type", ""
                    )
                )
            )
            == expected_type
        ]
        conflicting_documents = [
            document for document in matching_documents if document not in exact_documents
        ]
        registry_record = registry_records.get((number.lstrip("0") or "0", year))
        if exact_documents and (len(exact_documents) > 1 or conflicting_documents):
            state = "ambiguous"
        elif exact_documents:
            state = "candidate"
        elif matching_documents or registry_record:
            state = "identity_conflict"
        else:
            state = "not_found"

        structural_type = str(reference.get("structural_type") or "").casefold()
        structural_number = str(
            reference.get("structural_article_number") or reference.get("structural_number") or ""
        ).strip()
        device_label = ""
        if structural_type in {"artigo", "paragrafo", "inciso", "alinea", "item"} and structural_number:
            device_prefix = {
                "artigo": "Art.",
                "paragrafo": "§",
                "inciso": "inciso",
                "alinea": "alínea",
                "item": "item",
            }[structural_type]
            device_label = f"{device_prefix} {structural_number}"
        expected_type_display = _TYPE_LABELS.get(
            expected_type, str(reference.get("type_candidate") or "Ato")
        )
        citation = f"{expected_type_display} nº {raw_number}/{year}"
        if device_label:
            citation = f"{citation}, {device_label}"

        documents = []
        ordered_documents = exact_documents + [
            document
            for document in conflicting_documents
            if document not in exact_documents
        ]
        for document in ordered_documents:
            identity = (document.metadata_json or {}).get("identity_candidate") or {}
            local_pdf = document_pdf_url(document)
            documents.append(
                {
                    "type_display": _TYPE_LABELS.get(
                        canonical_type(str(identity.get("type") or "")),
                        str(identity.get("type") or "Espécie não identificada"),
                    ),
                    "filename": document.original_filename,
                    "pdf_url": local_pdf or "",
                    "pdf_access_required": bool(pdf_access_required(document) and not local_pdf),
                    "official_url": safe_official_url(document.official_url),
                    "matches_expected_type": document in exact_documents,
                }
            )

        result.append(
            {
                "source_device": candidate.source_device_label,
                "target_text": re.sub(
                    r"\s+",
                    " ",
                    str((candidate.evidence_json or {}).get("target_quote") or candidate.target_text),
                ).strip(),
                "citation": citation,
                "expected_type": expected_type_display,
                "state": state,
                "documents": documents,
                "sapl_url": (
                    f"https://sapl.natal.rn.leg.br/norma/{registry_record[0]}"
                    if registry_record
                    else ""
                ),
                "sapl_type_display": _TYPE_LABELS.get(registry_record[1], "")
                if registry_record
                else "",
                "sapl_publication_date": registry_record[2] if registry_record else "",
                "source_pdf_url": source_pdf_url,
            }
        )
    result.sort(key=lambda row: (row["source_device"], row["citation"]))
    return result
