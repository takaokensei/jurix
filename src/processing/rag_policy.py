"""Central policy decisions for legal RAG responses.

Keeping production policy outside the monolithic RAG service makes it easier to
review and test the safety boundary independently from prompt construction or
Ollama transport details.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.conf import settings


@dataclass(frozen=True)
class RAGPolicyDecision:
    accepted: bool
    reason: str
    cacheable: bool
    report: dict[str, Any]


def decide_grounding(report: dict[str, Any], source_only: bool) -> RAGPolicyDecision:
    if not source_only:
        return RAGPolicyDecision(False, "source_boundary_failed", False, report)
    if report.get("strict") is False:
        return RAGPolicyDecision(False, "strict_contract_missing", False, report)
    if not bool(report.get("grounded")):
        return RAGPolicyDecision(False, "grounding_failed", False, report)
    if report.get("failed_claims"):
        return RAGPolicyDecision(False, "unsupported_claims", False, report)
    if not bool(report.get("source_diversity_ok", True)):
        return RAGPolicyDecision(False, "source_diversity_failed", False, report)
    minimum_score = float(getattr(settings, "RAG_MIN_ACCEPTED_SCORE", 1.0))
    score = float(report.get("score", 0.0) or 0.0)
    if score < minimum_score:
        return RAGPolicyDecision(False, "insufficient_support_score", False, report)
    return RAGPolicyDecision(True, "verified_grounded", True, report)


def response_metadata(policy: RAGPolicyDecision) -> dict[str, Any]:
    return {
        "policy": "strict-grounding-v2",
        "accepted": policy.accepted,
        "reason": policy.reason,
        "cacheable": policy.cacheable,
        "contract": "claim-support+numeric+negation+citation+certainty+source-boundary",
    }
