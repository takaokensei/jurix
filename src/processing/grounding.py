"""
Deterministic grounding evaluator for legal RAG answers.

Verifies that factual and normative claims in the answer are supported by
retrieved evidence through citations or meaningful lexical overlap.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any

# Pattern for legal norm citations, e.g. "Lei nº 123/2020", "Lei 12.345/2019", "Decreto 456"
_CITATION_PATTERN = re.compile(
    r"\b(Lei(?:\s+Complementar|\s+Delegada)?|Decreto|Emenda\s+Constitucional|Constituição|Resolução|Portaria)"
    r"(?:\s+(?:n[º°]?|número))?\s*(\d+(?:[\.\d]+)?(?:\s*/\s*\d{2,4})?)",
    re.IGNORECASE,
)

# Number tokens written in words or digits that carry factual claims
_NUMERICAL_TOKENS = re.compile(
    r"\b(\d+|um|uma|dois|duas|três|tres|quatro|cinco|seis|sete|oito|nove|dez|"
    r"onze|doze|treze|quatorze|catorze|quinze|dezesseis|dezessete|dezoito|dezenove|"
    r"vinte|trinta|quarenta|cinquenta|sessenta|setenta|oitenta|noventa|cem|cento|mil)\b",
    re.IGNORECASE,
)

_STOPWORDS = {
    "a",
    "o",
    "as",
    "os",
    "um",
    "uma",
    "uns",
    "umas",
    "de",
    "da",
    "do",
    "das",
    "dos",
    "em",
    "na",
    "no",
    "nas",
    "nos",
    "por",
    "pela",
    "pelo",
    "pelas",
    "pelos",
    "para",
    "com",
    "sem",
    "sob",
    "sobre",
    "que",
    "e",
    "ou",
    "se",
    "mas",
    "como",
    "ao",
    "aos",
    "à",
    "às",
    "é",
    "era",
    "foi",
    "são",
    "ser",
    "estar",
    "está",
    "este",
    "esta",
    "estes",
    "estas",
    "esse",
    "essa",
    "esses",
    "essas",
    "aquele",
    "aquela",
    "aqueles",
    "aquelas",
    "seu",
    "sua",
    "seus",
    "suas",
    "qual",
    "quais",
    "onde",
    "quando",
    "muito",
    "muita",
    "mais",
    "menos",
    "não",
    "sim",
    "já",
    "ainda",
    "também",
    "apenas",
    "assim",
}


def _strip_accents(text: str) -> str:
    nfkd = unicodedata.normalize("NFKD", text)
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def _normalize(text: str) -> str:
    return _strip_accents(str(text or "")).lower().strip()


def _normalize_norm_ref(ref: str) -> str:
    """Normalize norma reference, e.g. 'Lei nº 123/2020' -> 'lei 123/2020'."""
    norm = _normalize(ref)
    norm = re.sub(r"\bn[º°\.]?\s*", "", norm)
    norm = re.sub(r"\s+", " ", norm)
    return norm.strip()


def _split_into_claims(text: str) -> list[str]:
    """Split answer into sentence-level claims."""
    raw_sentences = re.split(r"(?<=[.!?])\s+|\n+", text)
    claims = []
    for s in raw_sentences:
        clean = s.strip()
        if len(clean) > 3:
            claims.append(clean)
    return claims


def evaluate_grounding(answer: str, evidence: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Evaluate whether the claims in `answer` are supported by `evidence`.

    Returns:
        dict with:
            - 'grounded': bool
            - 'failed_claims': list[str]
            - 'score': float (0.0 to 1.0)
    """
    claims = _split_into_claims(answer)
    if not claims:
        return {"grounded": True, "failed_claims": [], "score": 1.0}

    if not evidence:
        return {"grounded": False, "failed_claims": claims, "score": 0.0}

    # Aggregate evidence texts and norm refs
    evidence_texts = []
    evidence_norms = []
    for ev in evidence:
        if isinstance(ev, dict):
            text = ev.get("text", "") or ev.get("texto", "")
            if text:
                evidence_texts.append(text)
            norm_ref = ev.get("norma_ref", "") or ev.get("norma", "")
            if norm_ref:
                evidence_norms.append(_normalize_norm_ref(str(norm_ref)))
        elif hasattr(ev, "texto"):
            evidence_texts.append(getattr(ev, "texto", ""))

    all_evidence_raw = " ".join(evidence_texts)
    all_evidence_norm = _normalize(all_evidence_raw)
    all_evidence_numbers = set(_NUMERICAL_TOKENS.findall(all_evidence_norm))

    failed_claims: list[str] = []

    for claim in claims:
        claim_norm = _normalize(claim)

        # 1. Check citation match
        citation_matches = _CITATION_PATTERN.findall(claim)
        has_matching_citation = False
        if citation_matches:
            for kind, number in citation_matches:
                normalized_cit = _normalize_norm_ref(f"{kind} {number}")
                for ev_norm in evidence_norms:
                    if normalized_cit in ev_norm or ev_norm in normalized_cit:
                        has_matching_citation = True
                        break
                if has_matching_citation:
                    break

        if has_matching_citation:
            continue

        # 2. Check numerical/factual constraints
        claim_numbers = set(_NUMERICAL_TOKENS.findall(claim_norm))
        unsupported_numbers = claim_numbers - all_evidence_numbers
        if unsupported_numbers:
            failed_claims.append(claim)
            continue

        # 3. Check content lexical overlap
        claim_words = [
            w for w in re.findall(r"\b\w+\b", claim_norm) if w not in _STOPWORDS and len(w) > 2
        ]
        if claim_words:
            matched_words = [w for w in claim_words if w in all_evidence_norm]
            overlap_ratio = len(matched_words) / len(claim_words)
            if overlap_ratio < 0.35 and not has_matching_citation:
                failed_claims.append(claim)
                continue

    grounded = len(failed_claims) == 0
    score = 1.0 - (len(failed_claims) / len(claims))
    return {
        "grounded": grounded,
        "failed_claims": failed_claims,
        "score": max(0.0, min(1.0, score)),
    }
