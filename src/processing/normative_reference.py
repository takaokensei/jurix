"""Conservative parsing and normalization of Brazilian normative references."""

from __future__ import annotations

import re
from dataclasses import dataclass

_REFERENCE_RE = re.compile(
    r"\b(?P<type>lei(?:\s+(?:complementar|ordin[áa]ria|org[âa]nica))?|"
    r"decreto(?:-lei|\s+legislativo)?|resolu[çc][ãa]o|portaria|"
    r"emenda(?:\s+constitucional)?)\s*"
    r"(?:n[º°o.]?\s*)?(?P<number>\d[\d.]*)"
    r"(?:\s*(?:/|de)\s*(?P<year>(?:19|20)\d{2}))?",
    re.IGNORECASE,
)
_ARTICLE_RE = re.compile(r"\bart(?:igo)?\.?\s*(\d+)\s*[ºª°o]?", re.IGNORECASE)
_PARAGRAPH_RE = re.compile(r"§\s*(único|\d+\s*[ºª°o]?)", re.IGNORECASE)
_ITEM_RE = re.compile(r"\binciso\s+([IVXLCDM]+)\b", re.IGNORECASE)
_ALINEA_RE = re.compile(r"\balínea\s+([a-z])\b", re.IGNORECASE)


def canonical_type(raw_type: str) -> str:
    """Return a stable type key without conflating different kinds of norms."""
    normalized = " ".join((raw_type or "").lower().split())
    normalized = normalized.replace("ordinária", "ordinaria").replace("orgânica", "organica")
    normalized = normalized.replace("resolução", "resolucao").replace("resolucão", "resolucao")
    normalized = normalized.replace("emenda constitucional", "emenda_constitucional")
    return {
        "lei ordinaria": "lei",
        "lei complementar": "lei_complementar",
        "lei organica": "lei_organica",
        "decreto-lei": "decreto_lei",
        "decreto legislativo": "decreto_legislativo",
        "resolucao": "resolucao",
    }.get(normalized, normalized.replace(" ", "_"))


def normalize_number(raw_number: str) -> str:
    """Normalize numeric separators without converting the identifier to an int."""
    return re.sub(r"\D", "", raw_number or "")


@dataclass(frozen=True)
class NormativeReference:
    type_key: str
    number: str
    year: int | None
    article: str | None = None
    paragraph: str | None = None
    item: str | None = None
    alinea: str | None = None
    ambiguous: bool = False

    @property
    def identity(self) -> tuple[str, str, int | None]:
        return self.type_key, self.number, self.year


def parse_normative_references(text: str) -> tuple[NormativeReference, ...]:
    """Parse explicit typed citations; leave yearless references marked ambiguous.

    A single hierarchy is attached only when the input contains exactly one
    article reference. Multiple norms or articles are intentionally not paired
    by proximity because that association requires sentence-level legal parsing.
    """
    raw = text or ""
    articles = _ARTICLE_RE.findall(raw)
    paragraphs = _PARAGRAPH_RE.findall(raw)
    items = _ITEM_RE.findall(raw)
    alíneas = _ALINEA_RE.findall(raw)
    one_hierarchy = len(articles) == 1
    matches = list(_REFERENCE_RE.finditer(raw))
    result = []
    for match in matches:
        number = normalize_number(match.group("number"))
        if not number:
            continue
        year_text = match.group("year")
        result.append(
            NormativeReference(
                type_key=canonical_type(match.group("type")),
                number=number,
                year=int(year_text) if year_text else None,
                article=articles[0] if one_hierarchy else None,
                paragraph=paragraphs[0] if one_hierarchy and len(paragraphs) == 1 else None,
                item=items[0].upper() if one_hierarchy and len(items) == 1 else None,
                alinea=alíneas[0].lower() if one_hierarchy and len(alíneas) == 1 else None,
                ambiguous=year_text is None or len(articles) > 1 or len(matches) > 1,
            )
        )
    return tuple(result)
