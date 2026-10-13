"""Conservative, review-only act boundary candidates in official gazettes.

The detector finds typographic headings, not legally adjudicated acts. Every
result is explicitly a candidate and retains page-local offsets so a reviewer
can return to the source PDF. It has no database, filesystem, or network access.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable
from dataclasses import asdict, dataclass

from src.processing.normative_reference import canonical_type

_LABELS = (
    ("LEI COMPLEMENTAR", "lei_complementar"),
    ("LEI ORGÂNICA", "lei_organica"),
    ("LEI ORDINÁRIA", "lei"),
    ("LEI PROMULGADA", "lei_promulgada"),
    ("DECRETO LEGISLATIVO", "decreto_legislativo"),
    ("DECRETO EXECUTIVO", "decreto"),
    ("DECRETO-LEI", "decreto_lei"),
    ("DECRETO", "decreto"),
    ("RESOLUÇÃO", "resolucao"),
    ("PORTARIA", "portaria"),
    ("EDITAL", "edital"),
    ("AVISO", "aviso"),
    ("EXTRATO", "extrato"),
    ("LEI", "lei"),
)
_LABEL_PATTERN = "|".join(re.escape(label) for label, _ in _LABELS)
_HEADING = re.compile(
    rf"^\s*(?P<label>{_LABEL_PATTERN})"
    r"\s+(?:(?:[A-ZÀ-ÿ0-9-]{2,24}\s+){1,4})?"
    r"(?:N\s*(?:(?:[º°O]\s*\.?|\.?\s*[º°]|\.)\s*)?)?"
    r"(?P<number>\d+(?:\s*\.\s*\d+)*)"
    r"(?:\s*-\s*(?P<suffix>[A-Z]))?"
    r"(?:\s*/\s*(?P<year>(?:19|20)\d{2}))?"
    r"(?=\s|[,.:;()\-]|$)",
    re.IGNORECASE,
)
_UNNUMBERED_NOTICE = re.compile(
    r"^\s*(?P<label>EDITAL|AVISO|EXTRATO)(?=\s+(?:DE|DO|DA|DOS|DAS)\b)",
    re.IGNORECASE,
)
_YEAR_IN_DATE = re.compile(r"\bDE\s+((?:19|20)\d{2})\b", re.IGNORECASE)
_DATE_TAIL = re.compile(
    r"\s*,?\s*DE\s+\d{1,2}\s+DE\s+[A-ZÀ-ÿ]+\s+DE\s+(?:19|20)\d{2}\.?\s*$",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GazettePageSpan:
    """Half-open character range within one extracted source page."""

    page: int
    start_offset: int
    end_offset: int


@dataclass(frozen=True)
class GazetteActCandidate:
    """A provisional heading and the text range up to the next candidate."""

    status: str
    review_required: bool
    type_key_candidate: str
    number_candidate: str | None
    year_candidate: int | None
    heading_page: int
    heading_start_offset: int
    heading_end_offset: int
    heading_text: str
    spans: tuple[GazettePageSpan, ...]
    repeated_heading_count: int = 1

    def as_dict(self) -> dict:
        result = asdict(self)
        # The heading line can include a person's name in administrative acts.
        # Keep full text in the in-memory result for verification, not metadata.
        result.pop("heading_text", None)
        result["spans"] = [asdict(span) for span in self.spans]
        return result


@dataclass(frozen=True)
class GazetteSegmentationCandidates:
    status: str
    pages_scanned: int
    truncated: bool
    candidates: tuple[GazetteActCandidate, ...]

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "pages_scanned": self.pages_scanned,
            "truncated": self.truncated,
            "offset_basis": "normalized page text; zero-based half-open offsets",
            "candidates": [candidate.as_dict() for candidate in self.candidates],
        }


@dataclass(frozen=True)
class _Heading:
    page: int
    start: int
    end: int
    type_key: str
    number: str | None
    year: int | None
    text: str


def _is_heading_case(line: str) -> bool:
    stripped = line.strip()
    structural_match = _HEADING.match(stripped)
    if structural_match:
        remainder = stripped[structural_match.end() :]
        has_no_trailing_prose = not any(char.isalpha() for char in remainder)
        has_only_epigraph_date = bool(_DATE_TAIL.fullmatch(remainder))
        if has_no_trailing_prose or has_only_epigraph_date:
            return True
    without_number_marker = re.sub(
        r"(?<!\w)N\s*(?:[º°O]\s*\.?|\.?\s*[º°]|\.)?\s*(?=\d)",
        "",
        line,
        count=1,
        flags=re.IGNORECASE,
    )
    letters = [char for char in without_number_marker if char.isalpha() and char not in "ºª"]
    return bool(letters) and sum(char.isupper() for char in letters) / len(letters) >= 0.82


def _parse_heading(line: str, *, page: int, start: int) -> _Heading | None:
    candidate = line.strip()
    if not candidate or len(candidate) > 180 or not _is_heading_case(candidate):
        return None
    match = _HEADING.match(candidate)
    if not match:
        unnumbered = _UNNUMBERED_NOTICE.match(candidate)
        if not unnumbered or not _is_heading_case(candidate):
            return None
        label = unnumbered.group("label")
        heading_start = start + len(line) - len(line.lstrip())
        return _Heading(
            page=page,
            start=heading_start,
            end=heading_start + len(candidate.rstrip("\r\n")),
            type_key=canonical_type(label),
            number=None,
            year=None,
            text=candidate,
        )

    label = match.group("label")
    number = re.sub(r"\D", "", match.group("number"))
    suffix = (match.group("suffix") or "").strip()
    if suffix:
        number = f"{number}-{suffix.upper()}"
    year_text = match.group("year")
    if year_text is None:
        date_match = _YEAR_IN_DATE.search(candidate)
        year_text = date_match.group(1) if date_match else None
    type_key = canonical_type(label)
    heading_start = start + len(line) - len(line.lstrip())
    return _Heading(
        page=page,
        start=heading_start,
        end=heading_start + len(candidate.rstrip("\r\n")),
        type_key=type_key,
        number=number,
        year=int(year_text) if year_text else None,
        text=candidate,
    )


def _spans_between(
    pages: list[str], start_page: int, start_offset: int, end_page: int, end_offset: int
) -> tuple[GazettePageSpan, ...]:
    spans = []
    for page_index in range(start_page, end_page + 1):
        page_text = pages[page_index]
        span_start = start_offset if page_index == start_page else 0
        span_end = end_offset if page_index == end_page else len(page_text)
        if span_end > span_start:
            spans.append(
                GazettePageSpan(
                    page=page_index + 1,
                    start_offset=span_start,
                    end_offset=span_end,
                )
            )
    return tuple(spans)


def find_gazette_act_candidates(
    pages: Iterable[str], *, max_pages: int = 500
) -> GazetteSegmentationCandidates:
    """Find conservative numbered and notice headings as review-only spans.

    Each span starts at a detected heading and ends immediately before the next
    detected heading. That is a navigation aid, not a claim that the PDF's
    legal-act boundary has been proven. Text before the first heading is left
    unassigned. Page numbers are one-based; offsets are zero-based and half-open.
    """
    if max_pages < 1:
        raise ValueError("max_pages must be positive")

    scanned_pages = []
    headings: list[_Heading] = []
    truncated = False
    iterator = iter(pages)
    for page_index in range(max_pages):
        try:
            page_text = next(iterator) or ""
        except StopIteration:
            break
        scanned_pages.append(page_text)
        offset = 0
        for line in page_text.splitlines(keepends=True):
            heading = _parse_heading(line, page=page_index + 1, start=offset)
            if heading:
                headings.append(heading)
            offset += len(line)
    else:
        truncated = next(iterator, None) is not None

    heading_counts = Counter(
        (
            heading.type_key,
            heading.number,
            heading.year,
            " ".join(heading.text.split()).casefold(),
        )
        for heading in headings
    )
    results = []
    for index, heading in enumerate(headings):
        if index + 1 < len(headings):
            following = headings[index + 1]
            end_page, end_offset = following.page - 1, following.start
        else:
            end_page = len(scanned_pages) - 1
            end_offset = len(scanned_pages[end_page]) if scanned_pages else 0
        spans = _spans_between(
            scanned_pages,
            heading.page - 1,
            heading.start,
            end_page,
            end_offset,
        )
        results.append(
            GazetteActCandidate(
                status="candidate",
                review_required=True,
                type_key_candidate=heading.type_key,
                number_candidate=heading.number,
                year_candidate=heading.year,
                heading_page=heading.page,
                heading_start_offset=heading.start,
                heading_end_offset=heading.end,
                heading_text=heading.text,
                repeated_heading_count=heading_counts[
                    (
                        heading.type_key,
                        heading.number,
                        heading.year,
                        " ".join(heading.text.split()).casefold(),
                    )
                ],
                spans=spans,
            )
        )

    status = "truncated" if truncated else ("candidates_found" if results else "no_candidates")
    return GazetteSegmentationCandidates(
        status=status,
        pages_scanned=len(scanned_pages),
        truncated=truncated,
        candidates=tuple(results),
    )
