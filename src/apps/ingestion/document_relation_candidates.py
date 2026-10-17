"""Build and persist immutable, unreviewed relations from frozen source PDFs."""

from __future__ import annotations

import hashlib
import json
import re

from django.core.exceptions import ValidationError
from django.db import transaction

from src.apps.legislation.document_models import EventoNormativoCandidato, ExtracaoDocumento
from src.processing.device_revision import ordered_hierarchy_rows, parsed_device_identities
from src.processing.document_relation_preview import build_document_relation_preview
from src.processing.document_segmentation import (
    _mask_normative_appendices,
    _offset_preserving_text,
    _source_page,
)
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor


def _normalize_pdf_structural_number(
    device_type: str, raw_number: str, target_quote: str
) -> tuple[str, str | None]:
    """Normalize unambiguous ordinal/paragraph glyphs without changing evidence text."""
    number = str(raw_number or "").strip()
    quote = str(target_quote or "")
    resolution = None
    if device_type == "paragrafo":
        source_match = re.search(
            r"(?:§|\ufffd)\s*(\d+)\s*([º°ª\ufffd]?)\s*(?:do|da)\s+art\.?",
            quote,
            re.I,
        )
        if source_match and number.rstrip("º°ª\ufffd") == source_match.group(1):
            ordinal = source_match.group(2)
            normalized = source_match.group(1) + ("º" if ordinal else "")
            if normalized != number:
                number = normalized
                resolution = "normalized_from_verified_pdf_glyph"
    elif device_type == "artigo" and number.endswith("\ufffd"):
        source_match = re.search(r"\barts?\.?\s*(\d+)\s*([º°ª])", quote, re.I)
        if source_match and number[:-1] == source_match.group(1):
            number = source_match.group(1) + "º"
            resolution = "normalized_from_verified_pdf_glyph"
    return number, resolution


def _target_parent_article(target_quote: str) -> str | None:
    """Return an article named by the same literal target quote, if present."""
    match = re.search(
        r"\b(?:do|da|de)\s+art(?:igo)?\.?\s*(\d+[A-Za-z]?(?:-[A-Za-z])?)\s*[º°ª]?",
        str(target_quote or ""),
        re.IGNORECASE,
    )
    return match.group(1) if match else None


def _target_year_from_quote(target_quote: str) -> str | None:
    """Normalize a year only when the literal citation supplies it."""
    match = re.search(
        r"\b(?:lei|decreto|resolu[cç][aã]o)\b[^\n]{0,100}?\b(?:n[º°.]?\s*)?"
        r"\d[\d.]*\s*/\s*(\d{2}|\d{4})\b",
        str(target_quote or ""),
        re.IGNORECASE,
    )
    if not match:
        return None
    year = match.group(1)
    if len(year) == 4:
        return year
    short_year = int(year)
    return str(1900 + short_year if short_year >= 50 else 2000 + short_year)


def _target_reference_json(item: dict) -> dict:
    target_quote = str(item.get("target_quote") or "")
    structural_article_number = item.get("structural_article_number") or (
        item.get("device_number") if item.get("device_type") == "artigo" else None
    )
    if not structural_article_number:
        structural_article_number = _target_parent_article(target_quote)
    year_candidate = (item.get("norma_candidate") or {}).get("ano")
    if not year_candidate:
        # Some NER spans stop before the year suffix (e.g. ``Lei nº 3.882``),
        # while the enclosing literal inciso still contains ``/89``. Use only
        # that same source-device quote as a fallback, never neighboring text.
        year_candidate = _target_year_from_quote(target_quote) or _target_year_from_quote(
            str(item.get("item_quote") or "")
        )
    result = {
        "schema_version": 1,
        "resolution_status": "candidate",
        "type_candidate": (item.get("norma_candidate") or {}).get("tipo"),
        "number_candidate": (item.get("norma_candidate") or {}).get("numero"),
        "year_candidate": year_candidate,
        "structural_type": item.get("device_type"),
        "structural_number": item.get("device_number"),
    }
    if structural_article_number:
        result["structural_article_number"] = structural_article_number
    if item.get("device_number_resolution"):
        result["structural_number_raw"] = item.get("device_number_raw")
        result["structural_number_resolution"] = item.get("device_number_resolution")
    return result


def prepare_candidate_devices(extraction: ExtracaoDocumento) -> list[dict]:
    """Parse a complete frozen extraction for review-only device previews."""
    source = extraction.legal_text or ""
    if extraction.status != ExtracaoDocumento.Status.COMPLETE or not source.strip():
        raise ValidationError("Somente extração completa e não vazia pode gerar candidatos.")
    article_text, appendix_start = _mask_normative_appendices(source)
    parse_text = _offset_preserving_text(article_text)
    hierarchy = LegalTextParser.build_hierarchy(
        LegalTextParser.parse_legal_text(parse_text, preserve_offsets=True)
    )
    identities = parsed_device_identities(hierarchy)
    ordered = ordered_hierarchy_rows(hierarchy)
    prepared = []
    for position, row in enumerate(ordered):
        start = row["start_pos"]
        end = ordered[position + 1]["start_pos"] if position + 1 < len(ordered) else len(source)
        if appendix_start is not None and start < appendix_start < end:
            end = appendix_start
        if (
            not isinstance(start, int)
            or not isinstance(end, int)
            or not 0 <= start < end <= len(source)
        ):
            raise ValidationError("Parser produziu dispositivo fora dos limites da extração.")
        parent_index = row.get("parent_index")
        key, revision = identities[row["index"]]
        source_device_text = source[start:end]
        device_number = str(row["numero"])
        if row["tipo"] == "artigo":
            device_number, _ = _normalize_pdf_structural_number(
                "artigo", device_number, source_device_text
            )
        prepared.append(
            {
                "structural_key": key,
                "revision_fingerprint": revision,
                "parent_key": identities[parent_index][0] if parent_index is not None else None,
                "tipo": row["tipo"],
                "numero": device_number,
                "texto": source_device_text,
                "start_offset": start,
                "end_offset": end,
                "page_index": _source_page(extraction, start),
            }
        )
    return prepared


def _candidate_fingerprint(extraction: ExtracaoDocumento, item: dict) -> str:
    payload = {
        "extraction_sha256": extraction.extraction_sha256,
        "source_structural_key": item["source_structural_key"],
        "action_structural_key": item["action_structural_key"],
        "action": item["action"],
        "action_span": [item["action_start_offset"], item["action_end_offset"]],
        "target_span": [item["target_start_offset"], item["target_end_offset"]],
        "target_reference": {
            "norma": item["norma_candidate"],
            "device_type": item["device_type"],
            "device_number": item["device_number"],
        },
    }
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _single_device_amendment_candidates(devices: list[dict]) -> list[dict]:
    """Find explicit one-device amendments embedded in an article's own text.

    This covers the common form “o § 2º do Art. 18 da LC ... passa a vigorar
    com a seguinte redação”, which is not a parent action followed by a list.
    The candidate retains the complete source article as evidence and does not
    assert that the target identity or legal effect has been reviewed.
    """
    extractor = LegalNERExtractor()
    rows = []
    for row in devices:
        if row.get("tipo") != "artigo" or not isinstance(row.get("start_offset"), int):
            continue
        source_text = str(row.get("texto") or "")
        events = extractor.extract_events(texto=source_text)
        selected = {}
        for event in events:
            if event.get("acao") not in {"ALTERA", "SUBSTITUI", "ADICIONA"}:
                continue
            reference = event.get("norma_referenciada")
            evidence = event.get("evidence")
            if not isinstance(reference, dict) or not isinstance(evidence, dict):
                continue
            target_quote = str(evidence.get("target_quote") or "").strip()
            action_quote = str(evidence.get("action_quote") or "").strip()
            target_start = evidence.get("target_start_offset")
            target_end = evidence.get("target_end_offset")
            action_start = evidence.get("action_start_offset")
            action_end = evidence.get("action_end_offset")
            if (
                not target_quote
                or not action_quote
                or not all(isinstance(value, int) for value in (
                    target_start, target_end, action_start, action_end
                ))
                or source_text[target_start:target_end] != target_quote
                or source_text[action_start:action_end] != action_quote
            ):
                continue
            reference_type = str(reference.get("tipo") or "").strip()
            reference_number = str(reference.get("numero") or "").strip()
            reference_year = str(reference.get("ano") or "").strip()
            if not reference_type or not reference_number or not reference_year.isdecimal():
                continue
            structural_type = str(event.get("referencia_tipo") or "").strip().casefold()
            structural_number = str(event.get("referencia_numero") or "").strip()
            if not structural_type or not structural_number:
                continue
            raw_structural_number = structural_number
            structural_number, number_resolution = _normalize_pdf_structural_number(
                structural_type, raw_structural_number, target_quote
            )
            article_match = re.search(
                r"\barts?\.?\s*(\d+[A-Za-z]?(?:-[A-Za-z])?)",
                target_quote,
                re.IGNORECASE,
            )
            # The NER emits one event per article in plural enumerations, while
            # every event shares the complete literal quote. Prefer that event's
            # own structural number; taking the first number from the shared quote
            # silently cross-links the entire list to its first article.
            article_number = (
                structural_number
                if structural_type == "artigo"
                else article_match.group(1) if article_match else ""
            )
            # A device header such as ``Art. 1º`` can be misread as the first
            # target when a later list says that several articles of another
            # act will be amended. It is the source device itself, not a target.
            source_article_number = re.sub(
                r"[^0-9A-Za-z-]", "", str(row.get("numero") or "")
            ).casefold()
            normalized_article_number = re.sub(
                r"[^0-9A-Za-z-]", "", article_number
            ).casefold()
            if (
                structural_type == "artigo"
                and normalized_article_number
                and normalized_article_number == source_article_number
                and not source_text[:target_start].strip()
                and target_end <= action_start
            ):
                continue
            key = (
                action_start,
                action_end,
                reference_type.casefold(),
                reference_number,
                reference_year,
                article_number.casefold(),
            )
            specificity = {
                "artigo": 1,
                "paragrafo": 2,
                "inciso": 3,
                "alinea": 4,
                "item": 5,
            }.get(structural_type, 0)
            if key in selected and selected[key][0] >= specificity:
                continue
            selected[key] = (
                specificity,
                {
                    "action": event["acao"],
                    "action_quote": action_quote,
                    "action_device": f"Artigo {row.get('numero', '')}".strip(),
                    "action_structural_key": row["structural_key"],
                    "action_page": row.get("page_index"),
                    "item_device": f"Artigo {row.get('numero', '')}".strip(),
                    "source_structural_key": row["structural_key"],
                    "item_quote": source_text,
                    "item_start_offset": row["start_offset"],
                    "item_end_offset": row["end_offset"],
                    "target_quote": target_quote,
                    "action_start_offset": row["start_offset"] + action_start,
                    "action_end_offset": row["start_offset"] + action_end,
                    "target_start_offset": row["start_offset"] + target_start,
                    "target_end_offset": row["start_offset"] + target_end,
                    "target_page": row.get("page_index"),
                    "norma_candidate": {
                        "tipo": reference_type,
                        "numero": reference_number,
                        "ano": reference_year,
                    },
                    "device_type": structural_type,
                    "device_number": structural_number,
                    "device_number_raw": raw_structural_number,
                    "device_number_resolution": number_resolution,
                    "structural_article_number": article_number,
                    "status": "candidate_unreviewed",
                },
            )
        rows.extend(item for _, item in selected.values())
    return rows


def extract_document_relation_candidates(
    extraction: ExtracaoDocumento, *, source_article: str | None = None
) -> list[dict]:
    """Return derived relation candidates with source offsets, without database writes."""
    devices = prepare_candidate_devices(extraction)
    candidates = [
        *build_document_relation_preview(devices, include_single_article_actions=False),
        *_single_device_amendment_candidates(devices),
    ]
    unique_candidates = {}
    for item in candidates:
        key = (
            item.get("source_structural_key"),
            item.get("action_start_offset"),
            item.get("action_end_offset"),
            item.get("target_start_offset"),
            item.get("target_end_offset"),
            item.get("device_type"),
            item.get("device_number"),
        )
        unique_candidates[key] = item
    candidates = list(unique_candidates.values())
    if source_article is not None:
        def normalize_article_label(value) -> str:
            normalized = re.sub(r"[º°ª]$", "", str(value or "").strip())
            return normalized.lstrip("0") or "0"

        normalized_article = normalize_article_label(source_article)

        def is_source_article(value) -> bool:
            return normalize_article_label(
                re.sub(r"^artigo\s+", "", str(value or ""), flags=re.I)
            ).casefold() == normalized_article.casefold()

        candidates = [
            item
            for item in candidates
            if is_source_article(item.get("item_device"))
            or is_source_article(item.get("action_device"))
        ]
    for item in candidates:
        raw_device_number = str(item.get("device_number") or "")
        normalized_device_number, number_resolution = _normalize_pdf_structural_number(
            str(item.get("device_type") or ""),
            raw_device_number,
            str(item.get("target_quote") or ""),
        )
        if number_resolution:
            item["device_number"] = normalized_device_number
            item["device_number_raw"] = raw_device_number
            item["device_number_resolution"] = number_resolution
            if item.get("device_type") == "artigo":
                item["structural_article_number"] = normalized_device_number
        evidence = extraction.legal_text or ""
        action_start, action_end = item["action_start_offset"], item["action_end_offset"]
        target_start, target_end = item["target_start_offset"], item["target_end_offset"]
        if (
            not isinstance(action_start, int)
            or not isinstance(action_end, int)
            or not isinstance(target_start, int)
            or not isinstance(target_end, int)
            or evidence[action_start:action_end] != item["action_quote"]
            or evidence[target_start:target_end] != item["target_quote"]
        ):
            raise ValidationError("A relação candidata não tem spans literais únicos na extração.")
        item["fingerprint"] = _candidate_fingerprint(extraction, item)
        item["evidence_json"] = {
            "schema_version": 1,
            "status": "candidate_unreviewed",
            "source_extraction_sha256": extraction.extraction_sha256,
            "action_quote": item["action_quote"],
            "action_start_offset": action_start,
            "action_end_offset": action_end,
            "target_quote": item["target_quote"],
            "target_start_offset": target_start,
            "target_end_offset": target_end,
            "item_quote": item["item_quote"],
            "item_start_offset": item["item_start_offset"],
            "item_end_offset": item["item_end_offset"],
            "item_device": item["item_device"],
            "action_device": item["action_device"],
            "action_page": item["action_page"],
            "target_page": item["target_page"],
        }
        item["target_reference_json"] = _target_reference_json(item)
    return candidates


@transaction.atomic
def persist_document_relation_candidates(
    extraction: ExtracaoDocumento, *, source_article: str | None = None
) -> dict:
    """Idempotently add candidate rows; never approve or mutate an existing record."""
    candidates = extract_document_relation_candidates(extraction, source_article=source_article)
    fingerprints = {item["fingerprint"] for item in candidates}
    existing = set(
        EventoNormativoCandidato.objects.filter(fingerprint__in=fingerprints).values_list(
            "fingerprint", flat=True
        )
    )
    created = 0
    for item in candidates:
        if item["fingerprint"] in existing:
            continue
        EventoNormativoCandidato.objects.create(
            extracao=extraction,
            fingerprint=item["fingerprint"],
            source_structural_key=item["source_structural_key"],
            source_device_label=item["item_device"],
            action=item["action"],
            action_quote=item["action_quote"][:500],
            target_text=item["target_quote"][:500],
            target_reference_json=item["target_reference_json"],
            evidence_json=item["evidence_json"],
            extraction_confidence=0.8,
            extraction_method="regex_inherited_list",
        )
        existing.add(item["fingerprint"])
        created += 1
    return {"extraction_id": extraction.pk, "found": len(candidates), "created": created}
