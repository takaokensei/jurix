"""Classify explicit normative queries before semantic retrieval."""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.processing.normative_reference import NormativeReference, parse_normative_references

_WHOLE_NORMA_INTENT = re.compile(
    r"(?:\bo\s+que\s+(?:prev[eê]|estabelece|disp[oõ]e|determina|diz)\b|"
    r"\b(?:fa[cç]a\s+)?(?:um\s+)?(?:resumo|s[ií]ntese|vis[aã]o\s+geral)\b|"
    r"\b(?:resuma|explique|descreva|apresente|conte)\b|"
    r"\b(?:quais?|principais)\b[^?\n]{0,100}\b"
    r"(?:eixos?|temas?\s+centrais|objetivos?|conte[uú]do|disposi[cç][oõ]es)\b)"
    r"[^?\n]{0,100}\b(?:lei|norma|decreto|resolu[cç][aã]o|portaria|lc)\b",
    re.IGNORECASE,
)
_ARTICLE_TARGET = re.compile(r"\bart(?:igo)?\.?\s*\d+\s*[ºª°o]?", re.IGNORECASE)
_RELATION_INTENT = (
    ("modification", re.compile(
        r"\b(?:quem|qual\s+norma|quais\s+normas|o\s+que)\b.{0,80}\b"
        r"(?:alterou|altera|modificou|modifica|revogou|revoga|acrescentou|adicionou)\b|"
        r"\b(?:altera[cç][aã]o|revoga[cç][aã]o)\b.{0,80}\b(?:art|lei|norma)",
        re.IGNORECASE,
    )),
    ("reference", re.compile(
        r"\b(?:faz\s+refer[eê]ncia|refer[eê]ncias?|remiss[aã]o|remete|menciona)\b",
        re.IGNORECASE,
    )),
)


@dataclass(frozen=True)
class NormativeQueryPlan:
    kind: str
    reference: NormativeReference | None = None
    relation_intent: str | None = None

    @property
    def is_norma_overview(self) -> bool:
        return self.kind == "norma_overview"


def classify_normative_query(question: str) -> NormativeQueryPlan:
    """Distinguish whole-norm overviews from provision-level and general asks.

    An explicit provision always wins over broad wording. A whole-norm plan is
    activated only when exactly one unambiguous typed reference is present.
    """
    references = parse_normative_references(question or "")
    relation_intent = next(
        (name for name, pattern in _RELATION_INTENT if pattern.search(question or "")),
        None,
    )
    if len(references) != 1 or references[0].ambiguous or references[0].year is None:
        return NormativeQueryPlan("general", relation_intent=relation_intent)

    reference = references[0]
    if reference.article or _ARTICLE_TARGET.search(question or ""):
        return NormativeQueryPlan("provision", reference, relation_intent)

    if _WHOLE_NORMA_INTENT.search(question or ""):
        return NormativeQueryPlan("norma_overview", reference, relation_intent)
    return NormativeQueryPlan("general", reference, relation_intent)
