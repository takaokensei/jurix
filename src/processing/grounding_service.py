"""Claim-to-evidence grounding for Jurix RAG responses.

The service maps individual claims to the specific evidence items retrieved for
the answer. It does not expose similarity as calibrated answer confidence.
"""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass
from typing import Any

_CLAUSE_RE = re.compile(r"(?<=[.!?])\s+|\n{2,}")
_CITATION_RE = re.compile(
    r"\b(lei(?:\s+complementar|\s+ordinária|\s+orgânica)?|decreto(?:-lei|\s+legislativo)?|"
    r"resolução|emenda(?:\s+constitucional)?|portaria)\s+n?[º°o.]*\s*([\d.]+)\s*[/,]\s*(\d{2,4})",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(r"\b\d+(?:[.,]\d+)?\b")
_WORD_RE = re.compile(r"[A-Za-zÀ-ÿ]{4,}", re.UNICODE)

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
}
_NUMBER_WORDS = {
    "zero",
    "um",
    "uma",
    "dois",
    "duas",
    "três",
    "quatro",
    "cinco",
    "seis",
    "sete",
    "oito",
    "nove",
    "dez",
    "onze",
    "doze",
    "treze",
    "quatorze",
    "catorze",
    "quinze",
    "dezesseis",
    "dezessete",
    "dezoito",
    "dezenove",
    "vinte",
    "trinta",
    "quarenta",
    "cinquenta",
    "sessenta",
    "setenta",
    "oitenta",
    "noventa",
    "cem",
    "cento",
    "mil",
}


@dataclass(frozen=True)
class Claim:
    text: str
    citation_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class Evidence:
    dispositivo_id: int | None
    text: str
    norma_ref: str
    identifier: str = ""
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class ClaimEvidence:
    claim: str
    supported: bool
    evidence: tuple[Evidence, ...] = ()


@dataclass(frozen=True)
class GroundingResult:
    grounded: bool
    score: float
    claims: tuple[ClaimEvidence, ...]
    failed_claims: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "grounded": self.grounded,
            "score": self.score,
            "claims": [
                {
                    "claim": item.claim,
                    "supported": item.supported,
                    "evidence": [asdict(ev) for ev in item.evidence],
                }
                for item in self.claims
            ],
            "failed_claims": list(self.failed_claims),
        }


def _normalise(text: str) -> str:
    return " ".join((text or "").lower().split())


def _tokens(text: str) -> set[str]:
    return {token for token in _WORD_RE.findall((text or "").lower()) if token not in _STOPWORDS}


def extract_claims(answer: str) -> tuple[Claim, ...]:
    """Split a generated answer into independently auditable claims."""
    claims: list[Claim] = []
    for raw in _CLAUSE_RE.split((answer or "").strip()):
        text = " ".join(raw.split())
        if not text:
            continue
        refs = tuple(
            f"{m.group(1).lower()} {m.group(2)}/{m.group(3)[-2:]}"
            for m in _CITATION_RE.finditer(text)
        )
        claims.append(Claim(text=text, citation_refs=refs))
    return tuple(claims)


def _norma_ref_from_source(source: dict[str, Any]) -> str:
    value = source.get("norma") or source.get("norma_ref")
    if isinstance(value, dict):
        tipo = value.get("tipo") or ""
        numero = value.get("numero") or ""
        ano = value.get("ano") or ""
        return " ".join(part for part in (tipo, f"{numero}/{ano}".strip("/")) if part).strip()
    if value:
        return str(value)

    dispositivo = source.get("dispositivo")
    norma = getattr(dispositivo, "norma", None)
    if norma is not None:
        tipo = getattr(norma, "tipo", "") or ""
        numero = getattr(norma, "numero", "") or ""
        ano = getattr(norma, "ano", "") or ""
        return " ".join(part for part in (tipo, f"{numero}/{ano}".strip("/")) if part).strip()
    return ""


def _identifier_from_source(source: dict[str, Any]) -> str:
    value = source.get("identifier") or source.get("referencia") or source.get("label")
    if value:
        return str(value)
    dispositivo = source.get("dispositivo")
    getter = getattr(dispositivo, "get_full_identifier", None)
    if callable(getter):
        return str(getter())
    return ""


def build_evidence(sources: Iterable[dict[str, Any]]) -> tuple[Evidence, ...]:
    result: list[Evidence] = []
    for source in sources:
        dispositivo = source.get("dispositivo")
        text = str(
            source.get("text") or source.get("full_text") or getattr(dispositivo, "texto", "") or ""
        )
        if not text:
            continue
        result.append(
            Evidence(
                dispositivo_id=source.get("dispositivo_id")
                or source.get("id")
                or getattr(dispositivo, "id", None),
                text=text,
                norma_ref=_norma_ref_from_source(source),
                identifier=_identifier_from_source(source),
                start=source.get("start"),
                end=source.get("end"),
            )
        )
    return tuple(result)


def _citation_matches(claim: Claim, evidence: Evidence) -> bool:
    if not claim.citation_refs:
        return True
    haystack = _normalise(f"{evidence.norma_ref} {evidence.text}")
    return all(_normalise(ref) in haystack for ref in claim.citation_refs)


def _numeric_tokens(text: str) -> set[str]:
    digits = {token.replace(",", ".") for token in _NUMBER_RE.findall(text or "")}
    words = {
        token.lower()
        for token in re.findall(r"[A-Za-zÀ-ÿ]+", (text or "").lower())
        if token in _NUMBER_WORDS
    }
    return digits | words


def _supports_claim(claim: Claim, evidence: Evidence) -> bool:
    if not _citation_matches(claim, evidence):
        return False

    full_ev_text = f"{evidence.norma_ref} {evidence.identifier} {evidence.text}".strip()
    claim_numbers = _numeric_tokens(claim.text)
    evidence_numbers = _numeric_tokens(full_ev_text)
    if claim_numbers - evidence_numbers:
        return False

    claim_words = _tokens(claim.text)
    if not claim_words:
        return True
    evidence_words = _tokens(full_ev_text)
    overlap = len(claim_words & evidence_words) / max(len(claim_words), 1)
    return overlap >= 0.35


def evaluate_grounding(
    answer: str,
    sources: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """Return a serializable claim -> evidence grounding report."""
    evidence = build_evidence(sources)
    claims = extract_claims(answer)

    matched: list[ClaimEvidence] = []
    failed: list[str] = []
    supported_count = 0

    for claim in claims:
        claim_evidence = tuple(item for item in evidence if _supports_claim(claim, item))
        supported = bool(claim_evidence)
        if supported:
            supported_count += 1
        else:
            failed.append(claim.text)
        matched.append(
            ClaimEvidence(
                claim=claim.text,
                supported=supported,
                evidence=claim_evidence,
            )
        )

    total = len(claims)
    score = supported_count / total if total else 0.0
    return GroundingResult(
        grounded=bool(claims) and supported_count == total,
        score=round(score, 4),
        claims=tuple(matched),
        failed_claims=tuple(failed),
    ).to_dict()
