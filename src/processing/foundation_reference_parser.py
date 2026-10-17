"""Bounded, offset-preserving extraction of normative citations in legal text."""

from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass

from src.processing.normative_reference import canonical_type, normalize_number

MAX_FOUNDATION_CHARS = 50_000
MAX_FOUNDATION_REFERENCES = 100

_NORM_RE = re.compile(
    r"(?P<type>lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica|promulgada))?|"
    r"decreto(?:-lei|\s+(?:legislativo|executivo))?|resolu[çc][ãa]o|portaria|"
    r"emenda(?:\s+constitucional)?|lc)\s*"
    r"(?:municipal(?:\s+de\s+Natal)?|do\s+munic[ií]pio(?:\s+de\s+Natal)?)?\s*"
    r"(?:n[º°o.]?\s*)?(?P<number>\d[\d.]*)"
    r"(?:\s*(?:/|de)\s*(?P<year>(?:19|20)\d{2}))?",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(
    r"\bart(?:igo)?s?\.?\s*(?P<number>\d+)\s*[ºª°o]?"
    r"(?:\s*-\s*(?P<suffix>[A-Z]))?",
    re.IGNORECASE,
)
_ARTICLE_LIST_ITEM_RE = re.compile(
    r"\s*(?:,|e)\s*(?P<number>\d+)\s*[ºª°o]?"
    r"(?:\s*-\s*(?P<suffix>[A-Z]))?",
    re.IGNORECASE,
)
_PARAGRAPH_RE = re.compile(r"§\s*(?P<number>único|\d+\s*[ºª°o]?)", re.IGNORECASE)
_ITEM_RE = re.compile(r"\binciso\s+(?P<number>[IVXLCDM]+)\b", re.IGNORECASE)
_ALINEA_RE = re.compile(r"\balínea\s+(?P<number>[a-z])\b", re.IGNORECASE)
_HIERARCHY_TAIL_RE = re.compile(
    r"(?:\s*,?\s*(?:§\s*(?:único|\d+\s*[ºª°o]?)|"
    r"inciso\s+[IVXLCDM]+|alínea\s+[a-z])){1,3}",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class FoundationReference:
    reference_id: str
    start: int
    end: int
    text: str
    type_key: str | None
    number: str | None
    year: int | None
    article: str | None = None
    paragraph: str | None = None
    item: str | None = None
    alinea: str | None = None
    association: str = "explicit"
    requires_confirmation: bool = False
    ambiguity_reason: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


def _stable_id(start: int, end: int, identity: tuple | None, device: tuple | None) -> str:
    payload = f"{start}:{end}:{identity!r}:{device!r}"
    return "ref_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:24]


def _hierarchies(text: str) -> list[dict]:
    found = []
    for article in _ARTICLE_RE.finditer(text):
        citation_group = article.start()
        entries = [
            (article.start(), article.end(), article.group("number"), article.group("suffix"))
        ]
        cursor = article.end()
        while listed := _ARTICLE_LIST_ITEM_RE.match(text, cursor):
            entries.append(
                (listed.start("number"), listed.end(), listed.group("number"), listed.group("suffix"))
            )
            cursor = listed.end()

        for start, article_end, number, letter_suffix in entries:
            tail = text[article_end : article_end + 80]
            hierarchy = _HIERARCHY_TAIL_RE.match(tail)
            suffix = hierarchy.group(0) if hierarchy else ""
            paragraph = _PARAGRAPH_RE.search(suffix)
            item = _ITEM_RE.search(suffix)
            alinea = _ALINEA_RE.search(suffix)
            end = article_end + (hierarchy.end() if hierarchy else 0)
            found.append(
                {
                    "start": start,
                    "end": end,
                    "citation_group": citation_group,
                    "article": _normalize_article_number(number, letter_suffix),
                    "paragraph": paragraph.group("number").strip().lower() if paragraph else None,
                    "item": item.group("number").upper() if item else None,
                    "alinea": alinea.group("number").lower() if alinea else None,
                }
            )
    return found


def _normalize_article_number(number: str, suffix: str | None = None) -> str:
    """Keep lettered article identity (e.g. 2º-A) distinct from article 2."""
    digits = normalize_number(number)
    return f"{digits}-{suffix.upper()}" if suffix else digits


def parse_foundation_references(text: str) -> list[FoundationReference]:
    """Extract norm/device citations without guessing across competing norms.

    Offsets are Python string offsets into the original input. An abbreviated
    article is linked only when its paragraph has exactly one explicit norm;
    competing norms and article-only paragraphs are returned for confirmation.
    The source text is never stored by this parser.
    """
    if not isinstance(text, str):
        raise TypeError("fundamentação deve ser texto")
    if len(text) > MAX_FOUNDATION_CHARS:
        raise ValueError(f"texto excede o limite de {MAX_FOUNDATION_CHARS} caracteres")
    if not text.strip():
        return []

    records: list[FoundationReference] = []
    paragraphs = re.finditer(r"[^\n]*(?:\n(?!\s*\n)[^\n]*)*", text)
    for paragraph_match in paragraphs:
        paragraph = paragraph_match.group(0)
        if not paragraph.strip():
            continue
        base = paragraph_match.start()
        norms = list(_NORM_RE.finditer(paragraph))
        devices = _hierarchies(paragraph)
        if not norms and not devices:
            continue

        if len(norms) == 1:
            norm_assignments = []
            for device in devices:
                distance = (
                    norms[0].start() - device["end"]
                    if device["end"] <= norms[0].start()
                    else device["start"] - norms[0].end()
                    if norms[0].end() <= device["start"]
                    else 0
                )
                norm_assignments.append(
                    (0, distance > 240, "norma antecedente distante; confirme a associação" if distance > 240 else None)
                )
        elif len(norms) > 1:
            norm_assignments = []
            for device in devices:
                direct_candidates = []
                for index, norm in enumerate(norms):
                    if device["end"] <= norm.start():
                        gap = paragraph[device["end"] : norm.start()]
                    elif norm.end() <= device["start"]:
                        gap = paragraph[norm.end() : device["start"]]
                    else:
                        continue
                    if len(gap) <= 50 and re.fullmatch(
                        r"[\s,():\-]*(?:(?:arts?|artigos?)\.?[\s,():\-]*)?"
                        r"(?:(?:da|do|de|na|no)[\s,():\-]*)?",
                        gap,
                        re.IGNORECASE,
                    ):
                        direct_candidates.append(index)
                if len(direct_candidates) == 1:
                    norm_assignments.append((direct_candidates[0], False, None))
                else:
                    norm_assignments.append(
                        (-1, True, "mais de uma norma explícita no mesmo parágrafo")
                    )
        else:
            norm_assignments = [(-1, True, "artigo sem norma antecedente explícita") for _ in devices]

        # A coordinated citation such as “LC 258/2024, Arts. 260 e 262” has
        # one explicit norm attached to the whole article list. The second
        # list item does not repeat “Arts.”, so its local text gap alone cannot
        # identify that same norm. Propagate only from a uniquely resolved
        # sibling in that syntactic list; never join separate article mentions.
        grouped_devices: dict[int, list[int]] = {}
        for device_index, device in enumerate(devices):
            grouped_devices.setdefault(device["citation_group"], []).append(device_index)
        for device_indices in grouped_devices.values():
            resolved_norms = {
                norm_assignments[index][0]
                for index in device_indices
                if norm_assignments[index][0] >= 0 and not norm_assignments[index][1]
            }
            if len(resolved_norms) != 1:
                continue
            norm_index = next(iter(resolved_norms))
            for index in device_indices:
                assigned_norm, ambiguous, _reason = norm_assignments[index]
                if ambiguous and (assigned_norm < 0 or assigned_norm == norm_index):
                    norm_assignments[index] = (norm_index, False, None)

        attached: set[int] = set()
        for device_index, device in enumerate(devices):
            norm_index, ambiguous, reason = norm_assignments[device_index]
            if norm_index < 0:
                start, end = base + device["start"], base + device["end"]
                records.append(
                    FoundationReference(
                        reference_id=_stable_id(start, end, None, tuple(device.values())),
                        start=start,
                        end=end,
                        text=text[start:end],
                        type_key=None,
                        number=None,
                        year=None,
                        article=device["article"],
                        paragraph=device["paragraph"],
                        item=device["item"],
                        alinea=device["alinea"],
                        association="unresolved_abbreviation",
                        requires_confirmation=True,
                        ambiguity_reason=reason,
                    )
                )
                continue

            norm = norms[norm_index]
            if ambiguous:
                start, end = base + device["start"], base + device["end"]
                records.append(
                    FoundationReference(
                        reference_id=_stable_id(start, end, None, tuple(device.values())),
                        start=start,
                        end=end,
                        text=text[start:end],
                        type_key=None,
                        number=None,
                        year=None,
                        article=device["article"],
                        paragraph=device["paragraph"],
                        item=device["item"],
                        alinea=device["alinea"],
                        association="unresolved_abbreviation",
                        requires_confirmation=True,
                        ambiguity_reason=reason,
                    )
                )
                continue
            attached.add(norm_index)
            start_local = min(device["start"], norm.start())
            end_local = max(device["end"], norm.end())
            start, end = base + start_local, base + end_local
            identity = (
                canonical_type(norm.group("type")),
                normalize_number(norm.group("number")),
                int(norm.group("year")) if norm.group("year") else None,
            )
            hierarchy = tuple(device[key] for key in ("article", "paragraph", "item", "alinea"))
            records.append(
                FoundationReference(
                    reference_id=_stable_id(start, end, identity, hierarchy),
                    start=start,
                    end=end,
                    text=text[start:end],
                    type_key=identity[0],
                    number=identity[1],
                    year=identity[2],
                    article=device["article"],
                    paragraph=device["paragraph"],
                    item=device["item"],
                    alinea=device["alinea"],
                    association=(
                        "explicit" if len(norms) == 1 and (
                            re.search(r"\b(?:da|do|de)\s*$", paragraph[max(0, device["end"] - 24) : norm.start()], re.IGNORECASE)
                            or re.search(r"^\s*,?\s*art", paragraph[norm.end() : device["start"]], re.IGNORECASE)
                        ) else "single_norm_paragraph" if len(norms) == 1 else "nearby_multiple_norms"
                    ),
                    requires_confirmation=ambiguous or identity[2] is None,
                    ambiguity_reason=reason or ("ano da norma ausente" if identity[2] is None else None),
                )
            )

        for index, norm in enumerate(norms):
            if index in attached:
                continue
            identity = (
                canonical_type(norm.group("type")),
                normalize_number(norm.group("number")),
                int(norm.group("year")) if norm.group("year") else None,
            )
            start, end = base + norm.start(), base + norm.end()
            records.append(
                FoundationReference(
                    reference_id=_stable_id(start, end, identity, None),
                    start=start,
                    end=end,
                    text=text[start:end],
                    type_key=identity[0],
                    number=identity[1],
                    year=identity[2],
                    requires_confirmation=identity[2] is None,
                    ambiguity_reason="ano da norma ausente" if identity[2] is None else None,
                )
            )

    records.sort(key=lambda item: (item.start, item.end, item.reference_id))
    if len(records) > MAX_FOUNDATION_REFERENCES:
        raise ValueError(f"texto excede o limite de {MAX_FOUNDATION_REFERENCES} referências")
    return records
