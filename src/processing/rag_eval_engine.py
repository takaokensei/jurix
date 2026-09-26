"""
Offline RAG evaluation engine for reviewed benchmark cases.

The engine is intentionally model-agnostic. A runner supplies retrieval results
and generated answer metadata; this module computes deterministic metrics that can
be compared between releases without embedding vendor-specific assumptions into
the benchmark format.
"""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CaseResult:
    case_id: str
    answerable: bool
    predicted_sources: tuple[str, ...]
    expected_sources: tuple[str, ...]
    reciprocal_rank: float
    citations_predicted: tuple[str, ...] = ()
    citations_expected: tuple[str, ...] = ()
    grounded: bool = False
    answer: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "answerable": self.answerable,
            "predicted_sources": list(self.predicted_sources),
            "expected_sources": list(self.expected_sources),
            "reciprocal_rank": self.reciprocal_rank,
            "citations_predicted": list(self.citations_predicted),
            "citations_expected": list(self.citations_expected),
            "grounded": self.grounded,
            "answer": self.answer,
        }


def _dedupe(values: Iterable[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    out: list[str] = []
    for value in values:
        normalized = str(value).strip()
        if normalized and normalized not in seen:
            seen.add(normalized)
            out.append(normalized)
    return tuple(out)


def reciprocal_rank(predicted: Sequence[str], expected: set[str]) -> float:
    if not expected:
        return 1.0
    for index, source in enumerate(predicted, start=1):
        if source in expected:
            return 1.0 / index
    return 0.0


def recall_at_k(predicted: Sequence[str], expected: set[str], k: int) -> float:
    if not expected:
        return 1.0
    if k <= 0:
        return 0.0
    found = len(set(predicted[:k]) & expected)
    return found / len(expected)


def precision_at_k(predicted: Sequence[str], expected: set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    top = list(predicted[:k])
    if not top:
        return 0.0
    return len(set(top) & expected) / len(top)


def overlap_precision(predicted: Sequence[str], expected: Sequence[str]) -> float:
    pred = set(_dedupe(predicted))
    exp = set(_dedupe(expected))
    if not pred:
        return 1.0 if not exp else 0.0
    return len(pred & exp) / len(pred)


def overlap_recall(predicted: Sequence[str], expected: Sequence[str]) -> float:
    pred = set(_dedupe(predicted))
    exp = set(_dedupe(expected))
    if not exp:
        return 1.0
    return len(pred & exp) / len(exp)


def evaluate_cases(cases: Sequence[CaseResult]) -> dict[str, Any]:
    if not cases:
        return {
            "cases": 0,
            "recall@1": 0.0,
            "recall@3": 0.0,
            "mrr": 0.0,
            "citation_precision": 0.0,
            "citation_recall": 0.0,
            "groundedness": 0.0,
        }

    recall1 = []
    recall3 = []
    mrr = []
    citation_precision = []
    citation_recall = []
    groundedness = []

    for case in cases:
        expected_sources = set(case.expected_sources)
        recall1.append(recall_at_k(case.predicted_sources, expected_sources, 1))
        recall3.append(recall_at_k(case.predicted_sources, expected_sources, 3))
        mrr.append(reciprocal_rank(case.predicted_sources, expected_sources))
        citation_precision.append(
            overlap_precision(case.citations_predicted, case.citations_expected)
        )
        citation_recall.append(
            overlap_recall(case.citations_predicted, case.citations_expected)
        )
        groundedness.append(1.0 if case.grounded else 0.0)

    def mean(values: Sequence[float]) -> float:
        return round(sum(values) / len(values), 4)

    return {
        "cases": len(cases),
        "recall@1": mean(recall1),
        "recall@3": mean(recall3),
        "mrr": mean(mrr),
        "citation_precision": mean(citation_precision),
        "citation_recall": mean(citation_recall),
        "groundedness": mean(groundedness),
    }
