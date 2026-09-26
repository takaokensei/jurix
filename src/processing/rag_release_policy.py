"""
Second-stage production policy for Jurix RAG release decisions.

This module intentionally stays deterministic. It does not claim to perform legal
reasoning; it checks the machine-verifiable invariants that should hold before an
answer is allowed to leave the RAG pipeline or be cached as a release artifact.

The runtime RAG service already has strict grounding. This module is deliberately
separate so CI, offline benchmark jobs, and future review tooling can use the same
acceptance contract without importing the HTTP layer.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ReleaseThresholds:
    min_grounded_score: float = 1.0
    min_source_recall: float = 1.0
    min_citation_precision: float = 1.0
    min_citation_recall: float = 1.0
    max_answer_chars: int = 24_000
    min_sources_when_grounded: int = 1
    require_policy_acceptance: bool = True
    require_grounded_flag: bool = True
    require_source_ids: bool = True
    require_answer: bool = True
    allow_unanswerable: bool = True


@dataclass(frozen=True)
class ReleaseDecision:
    accepted: bool
    reasons: tuple[str, ...] = ()
    warnings: tuple[str, ...] = ()
    facts: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "accepted": self.accepted,
            "reasons": list(self.reasons),
            "warnings": list(self.warnings),
            "facts": self.facts,
        }


def _number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _non_empty_str(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _source_id(source: Any) -> Any:
    if not isinstance(source, dict):
        return None
    return source.get("dispositivo_id") or source.get("id") or source.get("identifier")


def evaluate_result(
    result: dict[str, Any],
    *,
    thresholds: ReleaseThresholds | None = None,
    answerability: str | None = None,
) -> ReleaseDecision:
    policy = thresholds or ReleaseThresholds()
    reasons: list[str] = []
    warnings: list[str] = []

    answer = result.get("answer", "")
    grounded = bool(result.get("grounded", False))
    grounding = result.get("grounding") or {}
    policy_report = grounding.get("policy") if isinstance(grounding, dict) else None
    sources = result.get("sources") or []

    facts = {
        "answer_chars": len(answer) if isinstance(answer, str) else 0,
        "grounded": grounded,
        "grounding_score": _number(grounding.get("score")),
        "source_count": len(sources) if isinstance(sources, list) else 0,
        "policy_accepted": bool(
            isinstance(policy_report, dict) and policy_report.get("accepted")
        ),
    }

    if policy.require_answer and not _non_empty_str(answer):
        reasons.append("answer_empty")

    if facts["answer_chars"] > policy.max_answer_chars:
        reasons.append("answer_too_long")

    if policy.require_grounded_flag and not grounded:
        if answerability != "unanswerable" or not policy.allow_unanswerable:
            reasons.append("grounded_flag_false")

    if not isinstance(sources, list):
        reasons.append("sources_not_list")
        sources = []

    source_ids = {_source_id(source) for source in sources}
    source_ids.discard(None)
    if grounded and len(sources) < policy.min_sources_when_grounded:
        reasons.append("insufficient_sources")
    if grounded and policy.require_source_ids and len(source_ids) == 0:
        reasons.append("missing_source_identifiers")

    score = facts["grounding_score"]
    if grounded and score < policy.min_grounded_score:
        reasons.append("grounding_score_below_release_threshold")

    if policy.require_policy_acceptance and grounded:
        if not facts["policy_accepted"]:
            reasons.append("rag_policy_not_accepted")

    metrics = result.get("metrics") or {}
    if _number(metrics.get("citation_precision"), 1.0) < policy.min_citation_precision:
        reasons.append("citation_precision_below_threshold")
    if _number(metrics.get("citation_recall"), 1.0) < policy.min_citation_recall:
        reasons.append("citation_recall_below_threshold")
    if _number(metrics.get("source_recall"), 1.0) < policy.min_source_recall:
        reasons.append("source_recall_below_threshold")

    if result.get("cached") and not grounded:
        reasons.append("ungrounded_result_must_not_be_cached")

    if result.get("interrupted"):
        warnings.append("stream_was_interrupted")

    if result.get("confidence_calibrated") is False and grounded:
        warnings.append("confidence_is_not_calibrated")

    return ReleaseDecision(
        accepted=not reasons,
        reasons=tuple(dict.fromkeys(reasons)),
        warnings=tuple(dict.fromkeys(warnings)),
        facts=facts,
    )


def evaluate_batch(
    results: Iterable[dict[str, Any]],
    *,
    thresholds: ReleaseThresholds | None = None,
) -> dict[str, Any]:
    decisions: list[ReleaseDecision] = []
    for result in results:
        decisions.append(evaluate_result(result, thresholds=thresholds))

    accepted = sum(1 for item in decisions if item.accepted)
    rejected = len(decisions) - accepted
    reason_counts: dict[str, int] = {}
    for decision in decisions:
        for reason in decision.reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1

    return {
        "total": len(decisions),
        "accepted": accepted,
        "rejected": rejected,
        "acceptance_rate": round(accepted / len(decisions), 4) if decisions else 0.0,
        "reason_counts": dict(sorted(reason_counts.items())),
        "decisions": [item.as_dict() for item in decisions],
    }
