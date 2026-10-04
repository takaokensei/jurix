"""Deterministic candidate metadata for archived normative documents.

Filename and epigraph values are observations, not verified publication or
effective dates. No LLM, network client, or database is used here.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from datetime import date
from itertools import islice
from pathlib import PurePath
from typing import Any

from src.processing.normative_reference import canonical_type, normalize_number

KNOWN_SERIES = {"municipal_lc", "municipal_lo", "municipal_decreto", "municipal_lp"}
TYPE_SERIES = {
    "lei_complementar": "municipal_lc",
    "lei": "municipal_lo",
    "decreto": "municipal_decreto",
    "lei_promulgada": "municipal_lp",
}
KNOWN_TYPES = set(TYPE_SERIES) | {"lei_organica", "decreto_lei", "decreto_legislativo"}
_DATE_TOKEN = re.compile(r"^\d{8}$")
_NUMBER_TOKEN = re.compile(r"^\d[\d.]*[A-Za-z]?(?:-[A-Za-z0-9]+)?$")
_EPIGRAPH = re.compile(
    r"^\s*(?P<label>lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica|promulgada))?|"
    r"decreto(?:-lei|\s+(?:legislativo|executivo))?)\s+"
    r"(?:municipal\s+)?(?:n[º°o.]?\s*)?(?P<number>\d[\d.]*)"
    r"(?P<year_suffix>\s*/\s*(?:19|20)\d{2})?"
    r"(?:\s*,?\s+de\s+(?P<date>.+?))?\s*\.?\s*$",
    re.IGNORECASE,
)
_PORTUGUESE_DATE = re.compile(
    r"^(?P<day>\d{1,2})\s+de\s+(?P<month>[a-zçã]+)\s+de\s+(?P<year>\d{4})$",
    re.IGNORECASE,
)
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


def _fold(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in decomposed if not unicodedata.combining(char)).casefold()


def normalize_document_number(value: Any) -> str:
    """Normalize numeric formatting/leading zeroes without erasing suffixes."""
    raw = str(value or "").strip()
    if re.fullmatch(r"\d[\d.]*", raw):
        digits = normalize_number(raw)
        return digits.lstrip("0") or "0"
    return re.sub(r"\s+", "", raw).upper()


@dataclass(frozen=True)
class NormativeIdentity:
    identity_key: str | None
    identity_json: dict[str, Any]


def build_normative_identity(
    *,
    jurisdiction: str,
    raw_type: str,
    series: str | None,
    number: Any,
    year: int | str | None,
) -> NormativeIdentity:
    """Build an identity only when jurisdiction, series and year are explicit."""
    type_key = canonical_type(raw_type)
    number_key = normalize_document_number(number)
    try:
        year_value = int(year) if year is not None else None
    except (TypeError, ValueError):
        year_value = None
    jurisdiction_key = re.sub(r"\s+", "-", _fold(jurisdiction).upper())
    normalized_series = (series or "").strip().lower()
    identity_json = {
        "jurisdiction": jurisdiction_key or None,
        "type": type_key or None,
        "series": normalized_series or None,
        "number": number_key or None,
        "year": year_value,
        "nature": None,
        "promulgating_authority": None,
    }
    if (
        not jurisdiction_key
        or type_key not in KNOWN_TYPES
        or normalized_series not in KNOWN_SERIES
        or TYPE_SERIES.get(type_key) != normalized_series
        or not number_key
        or year_value is None
        or not 1000 <= year_value <= 9999
    ):
        return NormativeIdentity(None, identity_json)
    key = "|".join((jurisdiction_key, type_key, normalized_series, number_key, str(year_value)))
    return NormativeIdentity(key, identity_json)


@dataclass(frozen=True)
class MetadataCandidate:
    field: str
    value: str
    source: str
    quote: str
    status: str = "candidate"


@dataclass(frozen=True)
class FilenameMetadata:
    filename: str
    type_key: str | None
    series: str | None
    number: str | None
    role: str
    candidates: tuple[MetadataCandidate, ...]
    unparsed_segments: tuple[str, ...]
    issues: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        result = asdict(self)
        result["candidates"] = [asdict(candidate) for candidate in self.candidates]
        return result


def _filename_type(parts: list[str]) -> tuple[int, str | None, str | None]:
    for width in (1, 2):
        if len(parts) < width:
            continue
        label = " ".join(parts[:width]).replace("-", " ")
        key = canonical_type(label)
        if key in KNOWN_TYPES:
            return width, key, None

    if parts:
        compact = _fold(parts[0]).replace(" ", "")
        aliases = (
            "lei complementar",
            "lei ordinaria",
            "lei organica",
            "lei promulgada",
            "decreto legislativo",
            "decreto executivo",
            "decreto lei",
            "lei",
            "decreto",
        )
        for alias in aliases:
            prefix = alias.replace(" ", "")
            suffix = compact[len(prefix) :]
            if compact.startswith(prefix) and _DATE_TOKEN.fullmatch(suffix):
                key = canonical_type(alias)
                if key in KNOWN_TYPES:
                    return 1, key, suffix
    return 0, None, None


def _parse_iso_filename_date(token: str) -> date | None:
    if not _DATE_TOKEN.fullmatch(token):
        return None
    try:
        return date(int(token[:4]), int(token[4:6]), int(token[6:8]))
    except ValueError:
        return None


def _role_from_parts(parts: Iterable[str]) -> str:
    text = _fold(" ".join(parts))
    if "retificacao" in text or "retificado" in text:
        return "retificacao"
    if "republicacao" in text or "republicado" in text:
        return "republicacao"
    if "anexo" in text:
        return "anexo"
    if "original" in text:
        return "original"
    return "indeterminado"


def parse_filename_metadata(filename: str) -> FilenameMetadata:
    """Parse a conservative type/date/number pattern from a filename stem."""
    basename = PurePath(str(filename).replace("\\", "/")).name
    stem = basename.rsplit(".", 1)[0] if "." in basename else basename
    parts = [part.strip() for part in stem.split("_") if part.strip()]
    width, type_key, embedded_date = _filename_type(parts)
    remaining = parts[width:]
    if embedded_date:
        remaining.insert(0, embedded_date)
    candidates: list[MetadataCandidate] = []
    issues: list[str] = []
    number = None
    invalid_date_token = False

    if remaining and _DATE_TOKEN.fullmatch(remaining[0]):
        date_token = remaining[0]
        parsed_date = _parse_iso_filename_date(date_token)
        if parsed_date:
            # Filename dates have unknown semantics; never map them to
            # publication/effectivity without independent evidence.
            candidates.append(
                MetadataCandidate(
                    field="unclassified_filename_date",
                    value=parsed_date.isoformat(),
                    source="filename",
                    quote=date_token,
                )
            )
            remaining = remaining[1:]
        else:
            issues.append("invalid_filename_date")
            invalid_date_token = True

    if remaining and not invalid_date_token and _NUMBER_TOKEN.fullmatch(remaining[0]):
        number = remaining[0]
        remaining = remaining[1:]

    series = TYPE_SERIES.get(type_key or "")
    if type_key is None:
        issues.append("unknown_filename_type")
    return FilenameMetadata(
        filename=basename,
        type_key=type_key,
        series=series,
        number=number,
        role=_role_from_parts(parts),
        candidates=tuple(candidates),
        unparsed_segments=tuple(remaining),
        issues=tuple(issues),
    )


def _parse_epigraph_date(value: str) -> date | None:
    raw = (value or "").strip().lstrip("/").rstrip(".,;")
    try:
        return date.fromisoformat(raw)
    except ValueError:
        pass
    match = _PORTUGUESE_DATE.fullmatch(_fold(raw))
    if not match:
        return None
    month = _MONTHS.get(match.group("month"))
    if not month:
        return None
    try:
        return date(int(match.group("year")), month, int(match.group("day")))
    except ValueError:
        return None


def _epigraph_year(value: str, parsed_date: date | None) -> int | None:
    if parsed_date:
        return parsed_date.year
    raw = (value or "").strip().lstrip("/").strip().rstrip(".,;")
    if re.fullmatch(r"(?:19|20)\d{2}", raw):
        return int(raw)
    return None


@dataclass(frozen=True)
class EpigraphCandidate:
    type_key: str
    number: str
    year: int | None
    act_date: str | None
    quote: str
    page_index: int


@dataclass(frozen=True)
class EpigraphMetadata:
    status: str
    candidates: tuple[EpigraphCandidate, ...]
    issues: tuple[str, ...]


def parse_initial_epigraphs(pages: Iterable[str], *, max_pages: int = 3) -> EpigraphMetadata:
    """Read only heading-shaped epigraphs from bounded initial PDF pages."""
    found: list[EpigraphCandidate] = []
    for page_index, page in enumerate(islice(pages, max(1, min(max_pages, 3)))):
        for line in (page or "")[:6000].splitlines()[:24]:
            quote = " ".join(line.split())
            if not quote or len(quote) > 240:
                continue
            match = _EPIGRAPH.fullmatch(quote)
            if not match:
                continue
            type_key = canonical_type(match.group("label"))
            if type_key not in KNOWN_TYPES:
                continue
            raw_number = match.group("number")
            normalized_number = normalize_document_number(raw_number)
            raw_date = match.group("date") or ""
            date_value = _parse_epigraph_date(raw_date)
            year_source = raw_date or (match.group("year_suffix") or "").strip()
            found.append(
                EpigraphCandidate(
                    type_key=type_key,
                    number=normalized_number,
                    year=_epigraph_year(year_source, date_value),
                    act_date=date_value.isoformat() if date_value else None,
                    quote=quote,
                    page_index=page_index,
                )
            )

    distinct: dict[tuple[str, str, int | None, str | None], EpigraphCandidate] = {}
    for candidate in found:
        distinct.setdefault(
            (candidate.type_key, candidate.number, candidate.year, candidate.act_date), candidate
        )
    candidates = tuple(distinct.values())
    identities = {(item.type_key, item.number, item.year) for item in candidates}
    if len(identities) > 1:
        return EpigraphMetadata("multi_norm_document", candidates, ("multiple_epigraphs",))
    if not candidates:
        return EpigraphMetadata("unresolved", (), ("epigraph_not_found",))
    issues = []
    if candidates[0].year is None:
        issues.append("epigraph_year_not_found")
    if len({candidate.act_date for candidate in candidates}) > 1:
        issues.append("conflicting_act_date")
    return EpigraphMetadata("candidate", candidates, tuple(issues))
