"""Single deterministic assurance boundary for generated legal answers."""

from __future__ import annotations

import re
from typing import Any

from django.conf import settings

from src.processing.rag_policy import decide_grounding, response_metadata
from src.processing.strict_grounding import evaluate_strict_grounding

_CITATION_PATTERN = re.compile(
    r"\b(?:Lei|Decreto|Resolução|Portaria|Emenda Constitucional)\s*" r"(?:n[ºo.]?\s*)?\d[\d./-]+",
    re.IGNORECASE,
)


def answer_contains_legal_citation(answer: str) -> bool:
    return bool(_CITATION_PATTERN.search(answer or ""))


def assess_answer(answer: str, sources: list[dict[str, Any]]) -> dict[str, Any]:
    max_chars = int(getattr(settings, "RAG_MAX_ANSWER_CHARS", 24000))
    if not answer or len(answer) > max_chars:
        return {
            "grounded": False,
            "strict": True,
            "score": 0.0,
            "claims": [],
            "failed_claims": ["A resposta está vazia ou excede o limite operacional."],
            "policy": {
                "policy": "strict-grounding-v2",
                "accepted": False,
                "reason": "answer_size_or_empty",
                "cacheable": False,
            },
        }
    report = evaluate_strict_grounding(
        answer,
        sources,
        require_source_diversity=getattr(
            settings, "RAG_STRICT_REQUIRE_SOURCE_DIVERSITY", not settings.DEBUG
        ),
    )
    if getattr(settings, "RAG_REQUIRE_SOURCE_CITATIONS", True) and sources:
        if not answer_contains_legal_citation(answer):
            report["grounded"] = False
            report.setdefault("failed_claims", []).append(
                "A resposta não contém citação legal explícita compatível com as fontes."
            )
            report["citation_contract"] = "failed"
        else:
            report["citation_contract"] = "passed"
    else:
        report["citation_contract"] = "disabled_or_no_sources"
    policy = decide_grounding(report, True)
    report["grounded"] = policy.accepted
    report["policy"] = response_metadata(policy)
    return report
