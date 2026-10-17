"""Immutable, source-offset-preserving segmentation of accepted extractions."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.models import Dispositivo, Norma
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
    find_normative_appendix_start,
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


_EXPLICIT_STATUS_PREFIX_RE = re.compile(
    r"^\s*(?:\(\s*(?P<parenthetical>vetad[oa]s?|revogad[oa]s?)\s*\)"
    r"|(?P<plain>vetad[oa]s?|revogad[oa]s?)"
    r"(?=\s*(?:[.;:]|$|pela\b|por\b)))",
    re.IGNORECASE,
)
_EXPLICIT_STATUS_SUFFIX_RE = re.compile(
    r"(?:\(|\[)\s*(?P<status>vetad[oa]s?|revogad[oa]s?)\b"
    r"(?:\s+(?:pela|por)\b[^)\]\r\n]*)?\s*(?:\)|\])\s*[.;]?\s*$",
    re.IGNORECASE,
)


def _explicit_device_status(text: str) -> str | None:
    """Detect a status attached to this device, not a repeal it declares of others."""
    source = text or ""
    prefix = _EXPLICIT_STATUS_PREFIX_RE.match(source)
    if prefix:
        status = prefix.group("parenthetical") or prefix.group("plain")
        return "vetado" if status.casefold().startswith("vetad") else "revogado"
    suffix = _EXPLICIT_STATUS_SUFFIX_RE.search(source)
    if suffix:
        status = suffix.group("status")
        return "vetado" if status.casefold().startswith("vetad") else "revogado"
    return None


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


def _mask_normative_appendices(source: str) -> tuple[str, int | None]:
    """Keep annex text and offsets intact while excluding it from main-law parsing."""
    appendix_start = find_normative_appendix_start(source)
    if appendix_start is None:
        return source, None
    chars = list(source)
    for position in range(appendix_start, len(chars)):
        if chars[position] not in "\r\n":
            chars[position] = " "
    return "".join(chars), appendix_start


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


def _eligible_for_candidate_segmentation_preview(document) -> bool:
    """Allow a no-write preview for an unlinked archive or empty pending SAPL record."""
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity_key = str(metadata.get("identity_key") or "")
    identity_candidate = metadata.get("identity_candidate")
    if (
        document.source_kind not in {
            DocumentoNormativo.SourceKind.ARCHIVE,
            DocumentoNormativo.SourceKind.SAPL,
        }
        or document.review_status not in {
            DocumentoNormativo.ReviewStatus.PENDING,
            DocumentoNormativo.ReviewStatus.IN_REVIEW,
        }
        or document.role not in {
            DocumentoNormativo.Role.UNDETERMINED,
            # A staging adapter may record a source's intended edition as
            # "original" before a reviewer confirms its identity. It remains
            # eligible for this non-persisted preview while pending and unlinked.
            DocumentoNormativo.Role.ORIGINAL,
        }
        or document.accepted_extraction_id is not None
        or document.conflicts_json
        or metadata.get("synthetic")
        or not identity_key
        or not isinstance(identity_candidate, dict)
    ):
        return False

    if document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE:
        return document.norma_id is None

    norma = document.norma
    return bool(
        norma
        and norma.sapl_id
        and norma.status == Norma.Status.PENDING
        and norma.identity_key == identity_key
        and norma.documento_base_id is None
        and not norma.texto_original.strip()
        and not norma.texto_consolidado.strip()
        and not norma.dispositivos.exists()
    )


def segment_document_extraction(
    extraction_id: int, *, preview_only: bool = False, reviewer=None
) -> DocumentSegmentation:
    extraction = ExtracaoDocumento.objects.select_related("documento", "documento__norma").get(pk=extraction_id)
    document = extraction.documento
    if preview_only:
        if not (
            getattr(settings, "DEBUG", False)
            and getattr(settings, "NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED", False)
            and os.environ.get("JURIX_QA_ONLY") == "1"
        ):
            raise PermissionDenied("A prévia de candidato só está disponível no ambiente QA isolado.")
        if not (
            getattr(reviewer, "is_authenticated", False)
            and getattr(reviewer, "is_active", False)
            and getattr(reviewer, "is_staff", False)
            and reviewer.has_perm("legislation.view_documentonormativo")
        ):
            raise PermissionDenied("A prévia de segmentação exige acesso de leitura autorizado.")
        if not _eligible_for_candidate_segmentation_preview(document):
            raise SegmentationConflict(
                "Somente candidato público pendente, sem conflito e sem base consolidada pode receber prévia isolada."
            )
        if extraction.documento_id != document.pk:
            raise SegmentationConflict("Extração não pertence ao candidato selecionado.")
        if extraction.dispositivos_documentais.exists():
            raise SegmentationConflict("Candidato já possui segmentação persistida; prévia isolada bloqueada.")
    else:
        if document.role != document.Role.ORIGINAL:
            raise SegmentationConflict("Somente o documento original pode alimentar a segmentação da Norma.")
        if document.accepted_extraction_id != extraction.pk:
            raise SegmentationConflict("Somente a extração explicitamente aceita pode ser segmentada.")
        if not document.norma_id or document.norma.documento_base_id != document.pk:
            raise SegmentationConflict("Documento ainda não foi selecionado como base revisada da Norma.")
    if extraction.status != ExtracaoDocumento.Status.COMPLETE:
        raise SegmentationConflict("Extração incompleta não pode alimentar segmentação operativa.")
    source = extraction.legal_text or ""
    parser = LegalTextParser()
    article_text, appendix_start = _mask_normative_appendices(source)
    parse_text = _offset_preserving_text(article_text)
    elements = parser.parse_legal_text(parse_text)
    hierarchy = parser.build_hierarchy(elements)
    validate_hierarchy(hierarchy)
    identities = parsed_device_identities(hierarchy)
    ordered = ordered_hierarchy_rows(hierarchy)
    closing = classify_closing_segments(source)
    editorial = [segment for segment in closing if segment["kind"] == "editorial_colophon"]
    prepared = []
    for position, row in enumerate(ordered):
        start = row["start_pos"]
        end = ordered[position + 1]["start_pos"] if position + 1 < len(ordered) else len(source)
        if appendix_start is not None and start < appendix_start < end:
            end = appendix_start
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
        explicit_status = _explicit_device_status(row.get("texto", ""))
        marker = (
            explicit_status
            if explicit_status
            else DocumentoDispositivo.Marker.NONE
        )
        reasons = _review_reasons(row, source, extraction)
        if reasons:
            marker = DocumentoDispositivo.Marker.UNKNOWN
        prepared.append({
            "structural_key": key, "parent_key": parent_key,
            "tipo": row["tipo"], "numero": row["numero"], "ordem": len(prepared) + 1,
            "texto": exact_text, "start_offset": start, "end_offset": end,
            "page_index": _source_page(extraction, start), "marker": marker,
            "review_reasons": reasons, "caminho": row.get("caminho", ""),
        })

    legacy_rows = [] if preview_only else list(
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

    if preview_only:
        diagnostics.extend(reason for row in prepared for reason in row["review_reasons"])
        return DocumentSegmentation(
            extraction.pk, 0, False, tuple(prepared), tuple(sorted(set(diagnostics))), legacy_map
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
