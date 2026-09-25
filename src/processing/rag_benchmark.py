"""Deterministic offline evaluator for the Jurix legal RAG benchmark.

The benchmark consumes recorded system outputs. It does not invent labels or
call an LLM, making regressions reproducible once a gold corpus is versioned.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    expected_devices: frozenset[str]
    expected_citations: frozenset[str]


@dataclass(frozen=True)
class BenchmarkResult:
    case_id: str
    retrieved_device_ids: tuple[str, ...]
    citations: frozenset[str]
    grounded: bool


def recall_at_k(expected: set[str], retrieved: Iterable[str], k: int) -> float:
    if not expected:
        return 1.0
    top = list(retrieved)[:k]
    return len(expected.intersection(top)) / len(expected)


def precision_at_k(expected: set[str], retrieved: Iterable[str], k: int) -> float:
    top = list(retrieved)[:k]
    if not top:
        return 0.0
    return len(expected.intersection(top)) / len(top)


def reciprocal_rank(expected: set[str], retrieved: Iterable[str]) -> float:
    for index, value in enumerate(retrieved, 1):
        if value in expected:
            return 1.0 / index
    return 0.0


def citation_precision(expected: set[str], actual: set[str]) -> float:
    if not actual:
        return 0.0
    return len(expected.intersection(actual)) / len(actual)


def citation_recall(expected: set[str], actual: set[str]) -> float:
    if not expected:
        return 1.0
    return len(expected.intersection(actual)) / len(expected)


def evaluate(
    cases: Iterable[BenchmarkCase], results: Iterable[BenchmarkResult]
) -> dict[str, float | int]:
    case_map = {item.case_id: item for item in cases}
    metrics = {
        name: []
        for name in (
            "recall@1",
            "recall@3",
            "recall@5",
            "recall@10",
            "precision@1",
            "precision@3",
            "precision@5",
            "precision@10",
            "mrr",
            "citation_precision",
            "citation_recall",
            "groundedness",
        )
    }
    matched = 0
    for result in results:
        case = case_map.get(result.case_id)
        if not case:
            continue
        matched += 1
        expected = set(case.expected_devices)
        retrieved = result.retrieved_device_ids
        for k in (1, 3, 5, 10):
            metrics[f"recall@{k}"].append(recall_at_k(expected, retrieved, k))
            metrics[f"precision@{k}"].append(precision_at_k(expected, retrieved, k))
        metrics["mrr"].append(reciprocal_rank(expected, retrieved))
        metrics["citation_precision"].append(
            citation_precision(set(case.expected_citations), set(result.citations))
        )
        metrics["citation_recall"].append(
            citation_recall(set(case.expected_citations), set(result.citations))
        )
        metrics["groundedness"].append(1.0 if result.grounded else 0.0)

    def avg(values):
        return round(sum(values) / len(values), 6) if values else 0.0

    return {"cases_matched": matched, **{key: avg(value) for key, value in metrics.items()}}
