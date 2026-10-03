"""Shared answer validation and presentation policy for RAG generation."""

import re
from typing import Any

from django.conf import settings

from src.processing.rag_contract_helpers import grounding_fallback

_UNSUPPORTED_ABSENCE_RE = re.compile(
    r"\b(?:não\s+(?:há|existe|foi\s+encontrad[oa]|se\s+encontram)|"
    r"nenhum(?:a)?\s+(?:outro|outra)|únic[oa]|unico|única|nada\s+mais|"
    r"não\s+se\s+aplica)\b",
    re.IGNORECASE,
)


def ground_answer(answer: str, results: list[dict[str, Any]]) -> dict[str, Any]:
    """Evaluate generated text against the recovered evidence and strict policy."""
    from src.processing.strict_grounding import evaluate_strict_grounding

    from .grounding_service import evaluate_grounding

    baseline = evaluate_grounding(answer, results)
    if not getattr(settings, "RAG_STRICT_GROUNDING", True):
        return baseline
    strict = evaluate_strict_grounding(answer, results)
    from src.processing.rag_policy import decide_grounding, response_metadata

    policy = decide_grounding(strict, True)
    strict["grounded"] = policy.accepted
    strict["policy"] = response_metadata(policy)
    strict["baseline_score"] = baseline.get("score", 0.0)
    strict["baseline_grounded"] = baseline.get("grounded", False)
    return strict


def has_unsupported_absence_claim(answer: str, results: list[dict[str, Any]]) -> bool:
    """Reject absence/completeness assertions unless evidence states them."""
    if not _UNSUPPORTED_ABSENCE_RE.search(answer or ""):
        return False
    evidence = " ".join(
        str(
            item.get("evidence_text")
            if "evidence_text" in item
            else item.get("text") or item.get("full_text") or ""
        )
        for item in results
    )
    return not _UNSUPPORTED_ABSENCE_RE.search(evidence)


def source_relevance(results: list[dict[str, Any]]) -> float:
    """Return the retrieval score summary (not a legal confidence estimate)."""
    if not results:
        return 0.0
    scores = [float(item.get("similarity_score", 0.0) or 0.0) for item in results]
    return round(sum(scores) / len(scores), 4)


def fix_markdown_formatting(text: str) -> str:
    """Repair common malformed bullet-list line breaks from model output."""
    text = re.sub(r"([•\-])\s+([^•\n]+?);\s+([•\-])", r"\1 \2\n\3", text)
    text = re.sub(r"([•\-])\s+([^•\n]+?)\s+([•\-])\s+", r"\1 \2\n\3 ", text)
    text = re.sub(r";\s+([•\-])", r"\n\1", text)
    text = re.sub(r"([^\n])([•\-])\s+", r"\1\n\2 ", text)
    return re.sub(r"\n{3,}", "\n\n", text)


def answer_uses_only_sources(answer: str, results: list[dict[str, Any]]) -> bool:
    """Reject legal citations that were not present in retrieved sources."""
    marker_indexes = [int(value) for value in re.findall(r"\[\[(\d{1,3})\]\]", answer)]
    if any(index < 1 or index > len(results) for index in marker_indexes):
        return False
    if any(result.get("attachment") for result in results):
        return True
    allowed = set()
    for result in results:
        disp = result.get("dispositivo")
        norma = getattr(disp, "norma", None)
        if norma:
            num = str(norma.numero or "").replace(".", "").strip()
            year = str(norma.ano or "").strip()
            if num and year:
                allowed.add(f"{num}/{year}")
                allowed.add(f"{norma.numero}/{year}")
    cited_raw = re.findall(
        r"\b(?:Lei|Decreto|Resolução|Portaria)\s*(?:n[º°o.]*\s*)?(\d[\d.]*/\d{4})",
        answer,
        re.IGNORECASE,
    )
    cited = {citation.replace(".", "") for citation in cited_raw}
    return not cited or cited.issubset(allowed)


def validate_generated_answer(
    answer: str,
    results: list[dict[str, Any]],
    *,
    format_answer=fix_markdown_formatting,
    citation_policy=answer_uses_only_sources,
    absence_policy=has_unsupported_absence_claim,
    grounding_policy=ground_answer,
) -> dict[str, Any]:
    """Apply the same deterministic finalization policy to sync and SSE output."""
    normalized = format_answer(answer).strip()
    source_only = citation_policy(normalized, results) and not absence_policy(normalized, results)
    report = (
        grounding_policy(normalized, results)
        if source_only
        else {
            "grounded": False,
            "score": 0.0,
            "claims": [],
            "failed_claims": [
                "A resposta contém referências ou afirmações que não foram encontradas nas fontes recuperadas."
            ],
        }
    )
    grounded = bool(report.get("grounded")) and source_only
    return {
        "answer": normalized if grounded else grounding_fallback(),
        "grounding": report,
        "grounded": grounded,
        "source_only": source_only,
    }
