"""Conservative, non-persisting boundary proposals for official gazette PDFs.

Detected headings are review candidates only. They do not establish that a
document is a normative act, its legal effect, or the start/end of a complete
act without human comparison to the source PDF.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date

from src.processing.document_metadata import normalize_document_number

_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}
_DATE = re.compile(
    r"(?P<day>\d{1,2})\s+de\s+(?P<month>[a-zçã]+)\s+de\s+(?P<year>\d{4})",
    re.IGNORECASE,
)
_NUMERIC_DATE = re.compile(r"(?P<day>\d{2})/(?P<month>\d{2})/(?P<year>\d{4})")
_HEADING = re.compile(
    r"^(?P<label>lei\s+complementar|lei\s+ordin[áa]ria|lei\s+org[âa]nica|"
    r"lei\s+promulgada|lei|decreto-lei|decreto\s+legislativo|"
    r"decreto\s+executivo|decreto|portaria|edital|resoluç[ãa]o|aviso|extrato)"
    r"\s+(?:municipal\s+)?(?:n(?:[.º°o\uFFFD]|[.][º°])?[.]?\s*)?"
    r"(?P<number>\d[\d.]*(?:\s*/\s*(?:19|20)\d{2})?(?:-[A-Za-z0-9./]+)?)"
    r"(?:\s*,?\s+de\s+(?P<date>(?:\d{2}/\d{2}/\d{4}|\d{1,2}\s+de\s+[a-zçã]+\s+de\s+\d{4}|(?:19|20)\d{2})))?"
    r"\s*[.,;]?\s*$",
    re.IGNORECASE,
)
_INSTRUMENT_PREFIX = re.compile(
    r"^\s*(?P<label>lei\s+complementar|lei\s+ordin[áa]ria|lei\s+org[âa]nica|"
    r"lei\s+promulgada|lei|decreto-lei|decreto\s+legislativo|"
    r"decreto\s+executivo|decreto|portaria|edital|resoluç[ãa]o|aviso|extrato)\b",
    re.IGNORECASE,
)
_IDENTIFIED_NUMBER = re.compile(
    r"\bn(?:[.º°o\uFFFD]|[.][º°])?[.]?\s*"
    r"(?P<number>\d[\d.]*(?:\s*/\s*(?:19|20)\d{2})?(?:[-–—][A-Za-z0-9./]+)?)",
    re.IGNORECASE,
)
_NORMATIVE_LABELS = {
    "lei complementar",
    "lei ordinaria",
    "lei organica",
    "lei promulgada",
    "lei",
    "decreto-lei",
    "decreto legislativo",
    "decreto executivo",
    "decreto",
    "resolucao",
}
_NOTICE_LABELS = {"portaria", "edital", "aviso", "extrato"}


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


@dataclass(frozen=True)
class GazetteBoundaryCandidate:
    instrument_type: str
    number: str | None
    year: int | None
    publication_date: str | None
    document_class: str
    page_index: int
    heading_start_offset: int
    heading_end_offset: int
    heading: str
    review_status: str = "pending"


@dataclass(frozen=True)
class GazetteSegmentationProposal:
    status: str
    page_count: int
    processed_page_count: int
    source_length: int
    candidates: tuple[GazetteBoundaryCandidate, ...]
    issues: tuple[str, ...]


def _candidate_for_line(
    line: str, *, page_index: int, heading_start_offset: int, heading_end_offset: int
) -> GazetteBoundaryCandidate | None:
    heading = " ".join(line.split())
    if not heading or len(heading) > 240:
        return None
    exact_match = _HEADING.fullmatch(heading)
    prefix_match = _INSTRUMENT_PREFIX.match(heading)
    if not exact_match and not prefix_match:
        return None

    label = " ".join(
        (exact_match or prefix_match).group("label").split()
    )
    normalized_label = _fold(label)
    # Legal instruments cited inside a portaria often begin a new PDF text line.
    # Do not turn narrative citations into act boundaries merely because a later
    # number on the same line follows an instrument prefix. Agency-prefixed
    # resolutions are retained only when the entire line is a compact uppercase
    # epigraph (for example, "RESOLUÇÃO CONHABINS N.º 03/2026 – RN").
    if (
        not exact_match
        and normalized_label in _NORMATIVE_LABELS
        and not (normalized_label == "resolucao" and heading == heading.upper())
    ):
        return None

    number_value = exact_match.group("number") if exact_match else None
    raw_date = exact_match.group("date") if exact_match else None
    if not exact_match:
        remainder = heading[prefix_match.end() :]
        identifier_match = _IDENTIFIED_NUMBER.search(remainder)
        if identifier_match:
            number_value = identifier_match.group("number")
            raw_date_match = _DATE.search(remainder)
            numeric_date_match = _NUMERIC_DATE.search(remainder)
            raw_date = (
                raw_date_match.group(0)
                if raw_date_match
                else numeric_date_match.group(0)
                if numeric_date_match
                else None
            )
        elif normalized_label in {"edital", "aviso", "extrato"} and len(heading.split()) <= 16:
            number_value = None
            raw_date = None
        else:
            return None

    year_match = (
        re.search(r"/\s*((?:19|20)\d{2})(?:[-–—]|$)", number_value)
        if number_value
        else None
    )
    year = int(year_match.group(1)) if year_match else None
    raw_date = raw_date or ""
    if raw_date:
        date_match = _DATE.fullmatch(_fold(raw_date))
        numeric_date_match = _NUMERIC_DATE.fullmatch(raw_date)
        if numeric_date_match:
            try:
                parsed_date = date(
                    int(numeric_date_match.group("year")),
                    int(numeric_date_match.group("month")),
                    int(numeric_date_match.group("day")),
                )
            except ValueError:
                parsed_date = None
            if parsed_date:
                raw_date = parsed_date.isoformat()
                year = year or parsed_date.year
            else:
                raw_date = ""
        elif re.fullmatch(r"(?:19|20)\d{2}", raw_date):
            year = year or int(raw_date)
            raw_date = ""
        elif date_match:
            month = _MONTHS.get(date_match.group("month"))
            try:
                parsed_date = date(
                    int(date_match.group("year")), month, int(date_match.group("day"))
                ) if month else None
            except ValueError:
                parsed_date = None
            if parsed_date:
                raw_date = parsed_date.isoformat()
                year = year or parsed_date.year
            else:
                raw_date = ""
        else:
            raw_date = ""

    if normalized_label in _NOTICE_LABELS:
        document_class = "administrative_or_notice_candidate"
    elif normalized_label in _NORMATIVE_LABELS:
        document_class = "normative_or_cited_instrument_candidate"
    else:
        document_class = "unclassified_candidate"

    raw_number = (
        re.sub(r"\s+", "", number_value).split("/", maxsplit=1)[0]
        if number_value
        else None
    )
    return GazetteBoundaryCandidate(
        instrument_type=label,
        number=normalize_document_number(raw_number) if raw_number else None,
        year=year,
        publication_date=raw_date or None,
        document_class=document_class,
        page_index=page_index,
        heading_start_offset=heading_start_offset,
        heading_end_offset=heading_end_offset,
        heading=heading,
    )


def propose_gazette_boundaries(
    pages: Iterable[str], *, max_pages: int = 200
) -> GazetteSegmentationProposal:
    """Propose page/character spans from exact heading-shaped lines only.

    Offsets address a canonical text formed by joining page strings with one
    form-feed (``\f``). A page cap avoids unbounded parsing; truncation is
    reported and the final candidate is not presented as a complete act.
    Nothing is written to the database or filesystem.
    """
    if type(max_pages) is not int or not 1 <= max_pages <= 500:
        raise ValueError("max_pages deve estar entre 1 e 500")
    all_pages = [str(page or "") for page in pages]
    selected_pages = all_pages[:max_pages]
    parts: list[str] = []
    candidates: list[GazetteBoundaryCandidate] = []
    offset = 0

    for page_index, page_text in enumerate(selected_pages):
        if page_index:
            parts.append("\f")
            offset += 1
        parts.append(page_text)
        line_offset = offset
        for line in page_text.splitlines(keepends=True):
            content = line.rstrip("\r\n")
            candidate = _candidate_for_line(
                content,
                page_index=page_index,
                heading_start_offset=line_offset,
                heading_end_offset=line_offset + len(content),
            )
            if candidate:
                candidates.append(candidate)
            line_offset += len(line)
        offset += len(page_text)

    source_length = sum(map(len, parts))
    truncated = len(all_pages) > len(selected_pages)
    issues = ["heading_detection_is_not_exhaustive_or_legal_review"]
    if not candidates:
        issues.append("no_exact_act_heading_found")
    if truncated:
        issues.append("page_limit_reached_final_boundary_incomplete")
    status = "partial" if truncated else "proposed" if candidates else "unresolved"
    return GazetteSegmentationProposal(
        status=status,
        page_count=len(all_pages),
        processed_page_count=len(selected_pages),
        source_length=source_length,
        candidates=tuple(candidates),
        issues=tuple(issues),
    )
