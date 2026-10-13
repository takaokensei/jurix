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
    r"(?:eixos?|temas?(?:\s+(?:centrais|tratad[oa]s?|abordad[oa]s?|previst[oa]s?))?|"
    r"assuntos?|mat[eé]rias?|objetivos?|conte[uú]do|disposi[cç][oõ]es)\b)"
    r"[^?\n]{0,100}\b(?:lei|norma|decreto|resolu[cç][aã]o|portaria|lc)\b",
    re.IGNORECASE,
)
_WHOLE_NORMA_ORGANIZATION_INTENT = re.compile(
    r"\b(?:como|de\s+que\s+forma)\b[^?\n]{0,100}"
    r"\b(?:lei|norma|decreto|resolu[cç][aã]o|portaria|lc)\b[^?\n]{0,100}"
    r"\b(?:organiza|organizam|regula|regulam|disciplina|disciplinam|estrutura|estruturam)\b",
    re.IGNORECASE,
)
_WHOLE_NORMA_TOPICAL_INVENTORY_INTENT = re.compile(
    r"\b(?:quais?|que)\b[^?\n]{0,120}\b"
    r"(?:etapas?|fases?|procedimentos?|medidas?|requisitos?|cr[it][eé]rios?|"
    r"obriga[cç][oõ]es?|direitos?|compet[eê]ncias?|instrumentos?)\b"
    r"[^?\n]{0,180}\b(?:lei(?:\s+complementar)?|norma|decreto|resolu[cç][aã]o|"
    r"portaria|lc)\b",
    re.IGNORECASE,
)
_ARTICLE_TARGET = re.compile(r"\bart(?:igo)?\.?\s*\d+\s*[ºª°o]?", re.IGNORECASE)
_ARTICLE_NUMBER = r"\d{1,4}(?:\s*[ºª°o])?(?:\s*-\s*[A-Za-z])?"
_PLURAL_ARTICLE_LIST = re.compile(
    rf"\barts\.?\s*(?P<targets>{_ARTICLE_NUMBER}"
    rf"(?:\s*,\s*inciso\s+[ivxlcdm]+)?"
    rf"(?:\s*(?:,\s*(?:e\s+|ou\s+)?|\be\s+|\bou\s+|\ba\s+|\baté\s+)"
    rf"\s*(?:inciso\s+[ivxlcdm]+\s*,\s*)?{_ARTICLE_NUMBER})*)",
    re.IGNORECASE,
)
_ARTICLE_NUMBER_CAPTURE = re.compile(_ARTICLE_NUMBER, re.IGNORECASE)
_SINGLE_ARTICLE_TARGETS = re.compile(rf"\bart(?:igo)?\.?\s*({_ARTICLE_NUMBER})", re.IGNORECASE)
_RELATION_INTENT = (
    ("mixed", re.compile(
        r"\brela[cç][aã]o\s+normativa\b.{0,180}\b(?:altera[cç][aã]o|revoga[cç][aã]o)\b"
        r".{0,100}\b(?:refer[eê]ncia|remiss[aã]o)\b",
        re.IGNORECASE,
    )),
    ("modification", re.compile(
        r"\b(?:plc|projeto\s+de\s+lei(?:\s+complementar)?|"
        r"emenda\s+(?:supressiva|modificativa|aditiva))\b.{0,160}\b"
        r"(?:alteraram|revogaram|modificaram|suprimiram|acrescentaram|adicionaram)\b|"
        r"\b(?:quem|qual\s+norma|quais\s+normas|o\s+que)\b.{0,80}\b"
        r"(?:alterou|altera|modificou|modifica|revogou|revoga|acrescentou|adicionou)\b|"
        r"\b(?:altera[cç][aã]o|revoga[cç][aã]o)\b.{0,80}\b(?:art|lei|norma)|"
        r"\b(?:lei|norma)\b.{0,80}\b(?:alterou|altera|modificou|modifica|revogou|revoga|"
        r"acrescentou|adicionou)\b.{0,100}\b(?:art|dispositivo|lei|norma)|"
        r"\b(?:foi|foram|est[aá]|est[aã]o|houve|teve|tiveram|sofreu|sofreram)\b"
        r".{0,50}\b(?:alterad[oa]s?|revogad[oa]s?|modificad[oa]s?|"
        r"altera[cç][õo]es?|revoga[cç][õo]es?|modifica[cç][õo]es?)\b|"
        r"\b(?:altera[cç][õo]es?|revoga[cç][õo]es?|modifica[cç][õo]es?)\b"
        r".{0,80}\b(?:posterior(?:es)?|depois|ap[oó]s|dispositivo|artigo|lei|norma)\b|"
        r"\b(?:proposi[cç][aã]o|proposta|projeto)\b.{0,100}"
        r"\b(?:posterior(?:es)?|sobre\s+(?:o\s+)?(?:artigo|dispositivo)|"
        r"(?:altera|modifica|revoga))\b|"
        r"\b(?:ainda\s+vigora|red[aã]c[aã]o\s+(?:atual|vigente|em\s+\d{4})|"
        r"vig[eê]ncia\s+(?:atual|em\s+\d{4}))\b|"
        r"\b(?:vigente|vig[eê]ncia)\b.{0,60}\b(?:hoje|atual|atualmente)\b|"
        r"\b(?:posso|pode|podemos)\s+(?:considerar|tratar|aplicar)\b.{0,100}\bvigente\b",
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
    article_targets: tuple[str, ...] = ()
    broad_topical_scope: bool = False

    @property
    def is_norma_overview(self) -> bool:
        return self.kind == "norma_overview"


def classify_normative_query(question: str) -> NormativeQueryPlan:
    """Distinguish whole-norm overviews from provision-level and general asks.

    An explicit provision always wins over broad wording. A whole-norm plan is
    activated only when exactly one unambiguous typed reference is present.
    """
    question = question or ""
    references = parse_normative_references(question)
    relation_intent = next(
        (name for name, pattern in _RELATION_INTENT if pattern.search(question)),
        None,
    )
    targets = []
    for plural_list in _PLURAL_ARTICLE_LIST.finditer(question):
        targets.extend(
            _canonical_article_target(value)
            for value in _ARTICLE_NUMBER_CAPTURE.findall(plural_list.group("targets"))
        )
    targets.extend(
        _canonical_article_target(match.group(1))
        for match in _SINGLE_ARTICLE_TARGETS.finditer(question)
    )
    targets = tuple(dict.fromkeys(target for target in targets if target))

    if len(references) != 1 or references[0].year is None:
        # Keep provision targets even when the user has not named the act.
        # They are still useful retrieval constraints for discovery queries
        # such as "which norm institutes X, and what does Art. 18 say?".
        return NormativeQueryPlan(
            "general",
            relation_intent=relation_intent,
            article_targets=targets,
        )

    reference = references[0]
    # A single, explicit law reference plus one or more explicitly named
    # article targets is narrower than an overview. The parser marks a law
    # citation ambiguous when several article numbers occur, so rely on this
    # dedicated list only after confirming the query contains exactly one law.
    if targets:
        return NormativeQueryPlan("provision", reference, relation_intent, targets)
    if reference.ambiguous:
        return NormativeQueryPlan("general", relation_intent=relation_intent)
    if reference.article or _ARTICLE_TARGET.search(question):
        return NormativeQueryPlan("provision", reference, relation_intent)

    if (
        _WHOLE_NORMA_ORGANIZATION_INTENT.search(question)
        or _WHOLE_NORMA_TOPICAL_INVENTORY_INTENT.search(question)
    ):
        return NormativeQueryPlan(
            "norma_overview",
            reference,
            relation_intent,
            broad_topical_scope=True,
        )
    if _WHOLE_NORMA_INTENT.search(question or ""):
        return NormativeQueryPlan("norma_overview", reference, relation_intent)
    return NormativeQueryPlan("general", reference, relation_intent)


def _canonical_article_target(value: str) -> str:
    folded = value.casefold().replace("º", "").replace("ª", "").replace("°", "")
    return re.sub(r"[^a-z0-9]", "", folded)
