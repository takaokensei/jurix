"""Fail when protected RAG quality metrics regress beyond a tolerance."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

DEFAULT_METRICS = (
    "recall@1",
    "recall@3",
    "recall@5",
    "recall@10",
    "mrr",
    "citation_precision",
    "citation_recall",
    "groundedness",
)


def load_metrics(path: Path) -> dict[str, float]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {key: float(value) for key, value in payload.items() if isinstance(value, int | float)}


def compare(
    baseline: dict[str, float],
    current: dict[str, float],
    metrics: tuple[str, ...],
    max_regression: float,
) -> list[str]:
    failures: list[str] = []
    for metric in metrics:
        before = baseline.get(metric)
        after = current.get(metric)
        if before is None or after is None:
            raise KeyError(f"Métrica ausente: {metric}")
        drop = before - after
        print(
            f"{metric}: baseline={before:.6f} " f"current={after:.6f} delta={after - before:+.6f}"
        )
        if drop > max_regression:
            failures.append(f"{metric}: regression={drop:.6f} " f"> allowed={max_regression:.6f}")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--current", type=Path, required=True)
    parser.add_argument("--max-regression", type=float, default=0.03)
    parser.add_argument("--metrics", nargs="*", default=list(DEFAULT_METRICS))
    args = parser.parse_args()

    failures = compare(
        load_metrics(args.baseline),
        load_metrics(args.current),
        tuple(args.metrics),
        args.max_regression,
    )
    if failures:
        print("Benchmark regression detected:")
        for failure in failures:
            print(f"  - {failure}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
