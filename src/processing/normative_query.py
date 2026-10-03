"""Classify explicit normative queries before semantic retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.processing.normative_reference import NormativeReference, parse_normative_references

_WHOLE_NORMA_INTENT = re.compile(
    r"(?:\bo\s+que\s+(?:prev[eê]|estabelece|disp[oõ]e|determina|diz)\b|"
    r"\b(?:fa[cç]a\s+)?(?:um\s+)?(?:resumo|s[ií]ntese|vis[aã]o\s+geral)\b|"
    r"\b(?:resuma|explique|descreva|apresente|conte)\b)"
    r"[^?\n]{0,100}\b(?:lei|norma|decreto|resolu[cç][aã]o|portaria)\b",
    re.IGNORECASE,
)
_ARTICLE_TARGET = re.compile(r"\bart(?:igo)?\.?\s*\d+\s*[ºª°o]?", re.IGNORECASE)


@dataclass(frozen=True)
class NormativeQueryPlan:
    kind: str
    reference: NormativeReference | None = None

    @property
    def is_norma_overview(self) -> bool:
        return self.kind == "norma_overview"


def classify_normative_query(question: str) -> NormativeQueryPlan:
    """Distinguish whole-norm overviews from provision-level and general asks.

    An explicit provision always wins over broad wording. A whole-norm plan is
    activated only when exactly one unambiguous typed reference is present.
    """
    references = parse_normative_references(question or "")
    if len(references) != 1 or references[0].ambiguous or references[0].year is None:
        return NormativeQueryPlan("general")

    reference = references[0]
    if reference.article or _ARTICLE_TARGET.search(question or ""):
        return NormativeQueryPlan("provision", reference)

    if _WHOLE_NORMA_INTENT.search(question or ""):
        return NormativeQueryPlan("norma_overview", reference)
    return NormativeQueryPlan("general", reference)
