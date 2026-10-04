"""Immutable, source-offset-preserving segmentation of accepted extractions."""

from __future__ import annotations

import re
from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from src.apps.legislation.document_models import DocumentoDispositivo, ExtracaoDocumento
from src.apps.legislation.models import Dispositivo
from src.processing.device_hierarchy import validate_hierarchy
from src.processing.device_revision import (
    legacy_device_identity_map,
    ordered_hierarchy_rows,
    parsed_device_identities,
)
from src.processing.legal_parser import (
    _PAGE_HEADER_LINE_RE,
    _PAGE_SEPARATOR_RE,
    LegalTextParser,
    classify_closing_segments,
)


class SegmentationConflict(ValidationError):
    """A frozen extraction already has different persisted segments."""


@dataclass(frozen=True)
class DocumentSegmentation:
    extraction_id: int
    created: int
    unchanged: bool
    devices: tuple[dict, ...]
    diagnostics: tuple[str, ...]
    legacy_device_map: dict[str, int]


def _mask_match(match: re.Match, chars: list[str]) -> None:
    for position in range(match.start(), match.end()):
        if chars[position] not in "\r\n":
            chars[position] = " "


def _offset_preserving_text(source: str) -> str:
    """Mask parser artifacts without shifting character offsets in source text."""
    chars = list(source)
    for pattern in (_PAGE_SEPARATOR_RE, _PAGE_HEADER_LINE_RE):
        for match in pattern.finditer(source):
            _mask_match(match, chars)
    masked = "".join(chars)
    # The legacy parser collapses 3+ newlines, which shifts offsets. Keep the
    # same length while avoiding that transformation by padding the middle.
    chars = list(masked)
    for match in re.finditer(r"\n{3,}", masked):
        for position in range(match.start() + 1, match.end() - 1):
            chars[position] = " "
    return "".join(chars)


def _source_page(extraction: ExtracaoDocumento, offset: int) -> int | None:
    for span in extraction.page_map_json or []:
        if span.get("start", 0) <= offset < span.get("end", 0):
            page = span.get("page")
            return page if isinstance(page, int) and page > 0 else None
    return None


def _review_reasons(row: dict, source: str, extraction: ExtracaoDocumento) -> list[str]:
    reasons = []
    epigraph = (extraction.metadata_candidates_json or {}).get("epigraph", {})
    if epigraph.get("status") == "multi_norm_document":
        reasons.append("multiple_epigraph_candidates")
    before = source[: row["start_pos"]]
    quote_chars = ('"', "“", "”", "‘", "’")
    if sum(before.count(char) for char in quote_chars) % 2:
        reasons.append("marker_inside_unbalanced_quoted_text")
    return reasons


def segment_document_extraction(extraction_id: int) -> DocumentSegmentation:
    extraction = ExtracaoDocumento.objects.select_related("documento", "documento__norma").get(pk=extraction_id)
    document = extraction.documento
    if document.accepted_extraction_id != extraction.pk:
        raise SegmentationConflict("Somente a extração explicitamente aceita pode ser segmentada.")
    if not document.norma_id or document.norma.documento_base_id != document.pk:
        raise SegmentationConflict("Documento ainda não foi selecionado como base revisada da Norma.")
    if extraction.status != ExtracaoDocumento.Status.COMPLETE:
        raise SegmentationConflict("Extração incompleta não pode alimentar segmentação operativa.")
    source = extraction.legal_text or ""
    parser = LegalTextParser()
    parse_text = _offset_preserving_text(source)
    elements = parser.parse_legal_text(parse_text)
    hierarchy = parser.build_hierarchy(elements)
    validate_hierarchy(hierarchy)
    identities = parsed_device_identities(hierarchy)
    ordered = ordered_hierarchy_rows(hierarchy)
    closing = classify_closing_segments(source)
    editorial = [segment for segment in closing if segment["kind"] == "editorial_colophon"]
    markers = {"vetado": re.compile(r"\bvetad[oa]s?\b", re.IGNORECASE), "revogado": re.compile(r"\brevogad[oa]s?\b", re.IGNORECASE)}

    prepared = []
    for position, row in enumerate(ordered):
        start = row["start_pos"]
        end = ordered[position + 1]["start_pos"] if position + 1 < len(ordered) else len(source)
        next_colophon = next((item["start"] for item in editorial if start < item["start"] < end), None)
        if next_colophon is not None:
            end = next_colophon
        if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(source):
            raise SegmentationConflict("Parser produziu span fora do texto congelado.")
        exact_text = source[start:end]
        if not exact_text.strip():
            raise SegmentationConflict("Dispositivo sem texto-fonte verificável.")
        key, _fingerprint = identities[row["index"]]
        parent_index = row.get("parent_index")
        parent_key = identities[parent_index][0] if parent_index is not None else None
        marker = DocumentoDispositivo.Marker.NONE
        for marker_value, pattern in markers.items():
            if pattern.search(exact_text):
                marker = marker_value
                break
        reasons = _review_reasons(row, source, extraction)
        if reasons and marker == DocumentoDispositivo.Marker.NONE:
            marker = DocumentoDispositivo.Marker.UNKNOWN
        prepared.append({
            "structural_key": key, "parent_key": parent_key,
            "tipo": row["tipo"], "numero": row["numero"], "ordem": len(prepared) + 1,
            "texto": exact_text, "start_offset": start, "end_offset": end,
            "page_index": _source_page(extraction, start), "marker": marker,
            "review_reasons": reasons, "caminho": row.get("caminho", ""),
        })

    legacy_rows = list(
        Dispositivo.objects.select_related("dispositivo_pai").filter(norma_id=document.norma_id)
    )
    legacy_map = legacy_device_identity_map(legacy_rows)
    for row in prepared:
        row["legacy_device_id"] = legacy_map.get(row["structural_key"])

    diagnostics = []
    existing = list(extraction.dispositivos_documentais.order_by("ordem"))
    if existing:
        same = len(existing) == len(prepared) and all(
            old.structural_key == new["structural_key"]
            and old.parent_key == new["parent_key"]
            and old.texto == new["texto"]
            and old.start_offset == new["start_offset"]
            and old.end_offset == new["end_offset"]
            for old, new in zip(existing, prepared, strict=True)
        )
        if not same:
            raise SegmentationConflict("Extração já segmentada com outro resultado; crie nova extração versionada.")
        diagnostics.extend(reason for row in prepared for reason in row["review_reasons"])
        return DocumentSegmentation(
            extraction.pk, 0, True, tuple(prepared), tuple(sorted(set(diagnostics))), legacy_map
        )

    created = 0
    with transaction.atomic():
        for row in prepared:
            DocumentoDispositivo.objects.create(
                extracao=extraction,
                structural_key=row["structural_key"], parent_key=row["parent_key"],
                tipo=row["tipo"], numero=row["numero"], ordem=row["ordem"], texto=row["texto"],
                start_offset=row["start_offset"], end_offset=row["end_offset"],
                page_index=row["page_index"], marker=row["marker"],
            )
            created += 1
    diagnostics.extend(reason for row in prepared for reason in row["review_reasons"])
    return DocumentSegmentation(
        extraction.pk, created, False, tuple(prepared), tuple(sorted(set(diagnostics))), legacy_map
    )
