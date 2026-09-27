"""Strict, deterministic evidence validation for generated legal answers.

The original grounding service is intentionally conservative, but its lexical
support threshold is broad enough to accept claims that merely share words with
an evidence chunk. This module adds a second gate without pretending to perform
full legal reasoning. It validates claim-level invariants that are observable
from the answer and the retrieved evidence:

* every claim must map to at least one evidence item;
* citations mentioned by the model must occur in the evidence;
* numeric/date facts must be present in the supporting evidence;
* negated claims cannot be supported only by positive evidence and vice versa;
* the lexical overlap must exceed a stricter configurable threshold;
* the final report records exactly why a claim was rejected.

The result is a production guardrail, not a substitute for legal review or a
semantic entailment model. A future semantic verifier can be layered on top
without changing the public contract of this module.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

from django.conf import settings

from src.processing.grounding_service import build_evidence, extract_claims

_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{3,}", re.UNICODE)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_YEAR_RE = re.compile(r"\b(?:19|20)\d{2}\b")
_NEGATION_RE = re.compile(
    r"\b(?:não|nunca|jamais|sem|nenhum|nenhuma|proibid[oa]s?|vedad[oa]s?|ved[aa]m?|pro[íi]b[ea]m?|proibi[çc][ãa]o|veda[çc][ãa]o|impede|impedir|impossibilita|impossibilitar)\b",
    re.IGNORECASE,
)
_PROHIBITION_CERTAINTY_RE = re.compile(
    r"\b(?:é\s+proibid[oa]|fica\s+proibid[oa]|ficam\s+proibid[oa]s|é\s+vedad[oa]|fica\s+vedad[oa]|ficam\s+vedad[oa]s|proibid[oa]s?|vedad[oa]s?|proibi[çc][ãa]o|veda[çc][ãa]o|nunca|jamais)\b",
    re.IGNORECASE,
)
_OBLIGATION_CERTAINTY_RE = re.compile(
    r"\b(?:deve|devem|obrigatoriamente|sempre|obrigat[óo]ri[oa]s?|necessariamente)\b",
    re.IGNORECASE,
)
_PERMISSION_CERTAINTY_RE = re.compile(
    r"\b(?:é\s+permitid[oa]|fica\s+permitid[oa]|permitid[oa]s?|facultad[oa]s?|autorizad[oa]s?)\b",
    re.IGNORECASE,
)
_CONDITION_RE = re.compile(
    r"\b(?:somente|apenas|exceto|salvo|específico|específica|específicos|específicas|ressalvado|ressalvada)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "para",
    "como",
    "sobre",
    "entre",
    "essa",
    "este",
    "esta",
    "esse",
    "isso",
    "que",
    "uma",
    "por",
    "dos",
    "das",
    "com",
    "sem",
    "nos",
    "nas",
    "aos",
    "pelos",
    "pelas",
    "qual",
    "quais",
    "onde",
    "quando",
    "quem",
    "porque",
    "são",
    "ser",
    "tem",
    "mais",
    "menos",
    "muito",
    "muita",
    "muitas",
    "muitos",
    "pelo",
    "pela",
    "e",
    "ou",
    "uns",
    "umas",
    "portanto",
    "assim",
    "disso",
    "dessa",
    "dessas",
    "desse",
    "desses",
    "desta",
    "destas",
    "deste",
    "destes",
    "essas",
    "esses",
    "estas",
    "estes",
    "aquele",
    "aquela",
    "aqueles",
    "aquelas",
    "aquilo",
    "ademais",
    "outrossim",
    "sendo",
    "diante",
    "conforme",
    "segundo",
    "dispositivo",
    "dispositivos",
}


def _stem(word: str) -> str:
    w = word.lower()
    for suffix in (
        "imentos",
        "imento",
        "ações",
        "ação",
        "acoes",
        "acao",
        "ições",
        "ição",
        "icoes",
        "icao",
        "idades",
        "idade",
        "amente",
        "mente",
        "tórios",
        "tório",
        "torios",
        "torio",
        "ativos",
        "ativo",
        "ativas",
        "ativa",
        "áveis",
        "ável",
        "aveis",
        "avel",
        "íveis",
        "ível",
        "iveis",
        "ivel",
        "âncias",
        "ância",
        "encias",
        "ência",
        "ismos",
        "ismo",
        "istas",
        "ista",
        "ados",
        "adas",
        "ado",
        "ada",
        "idos",
        "idas",
        "ido",
        "ida",
        "ando",
        "endo",
        "indo",
        "arem",
        "erem",
        "irem",
        "asse",
        "esse",
        "isse",
        "avam",
        "avas",
        "ava",
        "aria",
        "eria",
        "iria",
        "ores",
        "oras",
        "ora",
        "or",
        "ais",
        "eis",
        "al",
        "el",
        "ões",
        "oes",
        "ãos",
        "aos",
        "am",
        "em",
        "os",
        "as",
        "es",
        "o",
        "a",
        "e",
    ):
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            return w[: -len(suffix)]
    return w


@dataclass(frozen=True)
class EvidenceMatch:
    evidence_index: int
    lexical_overlap: float
    numeric_ok: bool
    negation_ok: bool
    citation_ok: bool
    certainty_ok: bool

    @property
    def accepted(self) -> bool:
        minimum = float(getattr(settings, "RAG_STRICT_MIN_LEXICAL_OVERLAP", 0.45))
        return (
            self.lexical_overlap >= minimum
            and self.numeric_ok
            and self.negation_ok
            and self.citation_ok
            and self.certainty_ok
        )


def _tokens(text: str) -> set[str]:
    raw_tokens = [
        token.lower() for token in _WORD_RE.findall(text or "") if token.lower() not in _STOPWORDS
    ]
    return {_stem(token) for token in raw_tokens}


def _numbers(text: str) -> set[str]:
    values = {match.replace(",", ".") for match in _NUMBER_RE.findall(text or "")}
    values.update(_YEAR_RE.findall(text or ""))
    return values


def _negated(text: str) -> bool:
    return bool(_NEGATION_RE.search(text or ""))


def _certainty(text: str) -> set[str]:
    c = set()
    if _PROHIBITION_CERTAINTY_RE.search(text or ""):
        c.add("prohibition")
    if _OBLIGATION_CERTAINTY_RE.search(text or ""):
        c.add("obligation")
    if _PERMISSION_CERTAINTY_RE.search(text or ""):
        c.add("permission")
    return c


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def _normalise_citation_text(text: str) -> str:
    norm = _normalise(text)
    norm = re.sub(r"\bn[º°o.]*\s*", "", norm)
    return re.sub(r"/(?:19|20)(\d{2})\b", r"/\1", norm)


def _citation_ok(claim, evidence) -> bool:
    if not claim.citation_refs:
        return True
    haystack = _normalise_citation_text(
        f"{evidence.norma_ref} {evidence.identifier} {evidence.text}"
    )
    for ref in claim.citation_refs:
        norm_ref = _normalise_citation_text(ref)
        if norm_ref in haystack:
            continue
        match = re.search(r"(\d[\d.]*)/(\d{2,4})", ref)
        if match:
            num = match.group(1).replace(".", "")
            year_short = match.group(2)[-2:]
            year_full = match.group(2)
            if (
                f"{num}/{year_short}" in haystack
                or f"{num}/{year_full}" in haystack
                or f"{num}" in haystack
            ):
                continue
        return False
    return True


def _match_claim(claim, evidence) -> EvidenceMatch:
    evidence_text = f"{evidence.norma_ref} {evidence.identifier} {evidence.text}".strip()
    claim_tokens = _tokens(claim.text)
    evidence_tokens = _tokens(evidence_text)
    overlap = len(claim_tokens & evidence_tokens) / max(len(claim_tokens), 1)
    claim_numbers = _numbers(claim.text)
    evidence_numbers = _numbers(evidence_text)
    numeric_ok = claim_numbers.issubset(evidence_numbers)
    negation_ok = not _negated(claim.text) or _negated(evidence_text)
    citation_ok = _citation_ok(claim, evidence)
    claim_certainty = _certainty(claim.text)
    evidence_certainty = _certainty(evidence_text)
    has_claim_condition = bool(_CONDITION_RE.search(claim.text))
    has_evidence_condition = bool(_CONDITION_RE.search(evidence_text))
    condition_mismatch = has_evidence_condition and not has_claim_condition
    certainty_ok = (
        not claim_certainty or bool(claim_certainty & evidence_certainty)
    ) and not condition_mismatch
    return EvidenceMatch(
        evidence_index=-1,
        lexical_overlap=round(overlap, 4),
        numeric_ok=numeric_ok,
        negation_ok=negation_ok,
        citation_ok=citation_ok,
        certainty_ok=certainty_ok,
    )


def evaluate_strict_grounding(
    answer: str,
    sources: Iterable[dict[str, Any]],
    *,
    require_source_diversity: bool | None = None,
) -> dict[str, Any]:
    """Evaluate claims with a stricter deterministic evidence contract."""
    evidence = build_evidence(sources)
    claims = extract_claims(answer)
    require_diversity = (
        bool(getattr(settings, "RAG_STRICT_REQUIRE_SOURCE_DIVERSITY", False))
        if require_source_diversity is None
        else require_source_diversity
    )

    claim_reports: list[dict[str, Any]] = []
    failed_claims: list[str] = []
    matched_source_ids: set[Any] = set()

    for claim in claims:
        matches: list[dict[str, Any]] = []
        for index, item in enumerate(evidence):
            match = _match_claim(claim, item)
            match = EvidenceMatch(
                evidence_index=index,
                lexical_overlap=match.lexical_overlap,
                numeric_ok=match.numeric_ok,
                negation_ok=match.negation_ok,
                citation_ok=match.citation_ok,
                certainty_ok=match.certainty_ok,
            )
            if match.accepted:
                matched_source_ids.add(item.dispositivo_id or index)
                matches.append(
                    {
                        "evidence_index": index,
                        "dispositivo_id": item.dispositivo_id,
                        "lexical_overlap": match.lexical_overlap,
                        "numeric_ok": match.numeric_ok,
                        "negation_ok": match.negation_ok,
                        "citation_ok": match.citation_ok,
                        "certainty_ok": match.certainty_ok,
                    }
                )

        supported = bool(matches)
        if not supported:
            failed_claims.append(claim.text)
        claim_reports.append(
            {
                "claim": claim.text,
                "supported": supported,
                "matches": matches,
                "citation_refs": list(claim.citation_refs),
            }
        )

    total = len(claims)
    supported_count = sum(1 for item in claim_reports if item["supported"])
    diversity_ok = (not require_diversity) or len(matched_source_ids) >= min(2, len(evidence))
    grounded = bool(claims) and supported_count == total and diversity_ok
    return {
        "grounded": grounded,
        "score": round(supported_count / total, 4) if total else 0.0,
        "strict": True,
        "min_lexical_overlap": float(getattr(settings, "RAG_STRICT_MIN_LEXICAL_OVERLAP", 0.55)),
        "claims": claim_reports,
        "failed_claims": failed_claims,
        "evidence_count": len(evidence),
        "matched_source_count": len(matched_source_ids),
        "source_diversity_ok": diversity_ok,
    }
