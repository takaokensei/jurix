#!/usr/bin/env python3
"""Compare paired exported RAG arms without contacting the app or an LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import sys
from collections import defaultdict
from pathlib import Path

ARMS = ("baseline", "graph", "graph_temporal")
FIXED_CONFIG = ("corpus_revision", "model", "temperature", "token_budget", "hardware")


def load_cases(path: Path) -> list[dict]:
    rows = []
    for index, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        if not isinstance(row, dict) or not row.get("case_id"):
            raise ValueError(f"line {index}: case_id is required")
        if row.get("arm") not in ARMS:
            raise ValueError(f"line {index}: arm must be one of {ARMS}")
        if row.get("cache_state") not in {"cold", "warm"}:
            raise ValueError(f"line {index}: cache_state must be cold or warm")
        rows.append(row)
    if not rows:
        raise ValueError("experiment input is empty")
    return rows


def _rank_metrics(rows: list[dict]) -> dict:
    total_relevant = 0
    recall_hits = {1: 0, 3: 0, 5: 0}
    reciprocal_ranks = []
    citation_tp = citation_predicted = citation_expected = 0
    version_correct = version_cases = 0
    abstain_correct = abstain_cases = 0
    for row in rows:
        expected = set(row.get("expected_source_ids", []))
        retrieved = list(row.get("retrieved_source_ids", []))
        if expected:
            total_relevant += len(expected)
            for cutoff in recall_hits:
                recall_hits[cutoff] += len(set(retrieved[:cutoff]) & expected)
            reciprocal_ranks.append(next((1 / (rank + 1) for rank, source in enumerate(retrieved) if source in expected), 0.0))
        expected_citations = set(row.get("expected_citation_ids", []))
        citations = set(row.get("cited_citation_ids", []))
        citation_tp += len(expected_citations & citations)
        citation_predicted += len(citations)
        citation_expected += len(expected_citations)
        expected_versions = row.get("expected_versions", {})
        actual_versions = row.get("cited_versions", {})
        for source_id, expected_version in expected_versions.items():
            version_cases += 1
            version_correct += actual_versions.get(source_id) == expected_version
        if "expected_abstain" in row:
            abstain_cases += 1
            abstain_correct += bool(row.get("abstained")) == bool(row["expected_abstain"])
    return {
        "cases": len(rows),
        "retrieval_recall": {
            f"at_{cutoff}": count / total_relevant if total_relevant else None
            for cutoff, count in recall_hits.items()
        },
        "mrr": statistics.fmean(reciprocal_ranks) if reciprocal_ranks else None,
        "citation_precision": citation_tp / citation_predicted if citation_predicted else None,
        "citation_recall": citation_tp / citation_expected if citation_expected else None,
        "version_exact_accuracy": version_correct / version_cases if version_cases else None,
        "version_cases": version_cases,
        "abstention_exact_accuracy": abstain_correct / abstain_cases if abstain_cases else None,
        "abstention_cases": abstain_cases,
    }


def _latency(rows: list[dict], field: str) -> dict:
    values = [float(row[field]) for row in rows if isinstance(row.get(field), int | float) and row[field] >= 0]
    return {
        "n": len(values),
        "p50_ms": statistics.median(values) if values else None,
        "p95_ms": statistics.quantiles(values, n=20, method="inclusive")[18] if len(values) >= 20 else None,
        "p95_status": "measured" if len(values) >= 20 else "not_estimated_small_n",
    }


def analyze(rows: list[dict]) -> dict:
    paired: dict[tuple, dict[str, dict]] = defaultdict(dict)
    for row in rows:
        key = (row["case_id"], row.get("repeat", 0), row["cache_state"])
        arm = row["arm"]
        if arm in paired[key]:
            raise ValueError(f"duplicate arm {arm} for paired case {key}")
        paired[key][arm] = row
    for key, arms in paired.items():
        if set(arms) != set(ARMS):
            raise ValueError(f"incomplete paired arms for {key}")
        baseline = arms["baseline"]
        for arm in ARMS[1:]:
            for field in FIXED_CONFIG:
                if arms[arm].get(field) != baseline.get(field):
                    raise ValueError(f"fixed configuration differs for {key}: {field}")

    report = {"arms": {}, "paired_groups": len(paired), "cache_policy": {}}
    for cache_state in ("cold", "warm"):
        report["cache_policy"][cache_state] = {}
        for arm in ARMS:
            subset = [rows_by_arm[arm] for key, rows_by_arm in paired.items() if key[2] == cache_state]
            report["cache_policy"][cache_state][arm] = {
                "quality": _rank_metrics(subset),
                "time_to_first_token": _latency(subset, "ttft_ms"),
                "total_response": _latency(subset, "final_ms"),
            }
    for arm in ARMS:
        subset = [row for row in rows if row["arm"] == arm]
        report["arms"][arm] = _rank_metrics(subset)
    reviewed = all(row.get("human_evidence_review") is True for row in rows)
    report["status"] = "human_reviewed_experiment" if reviewed else "technical_smoke_only"
    report["scientific_claim_allowed"] = reviewed and len({row["case_id"] for row in rows}) >= 20
    report["sample_warning"] = "p95 latencies are reported only for n >= 20; small samples are not population estimates."
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        report = analyze(load_cases(args.input))
        report["input_sha256"] = hashlib.sha256(raw).hexdigest()
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(serialized, encoding="utf-8", newline="\n")
        else:
            print(serialized, end="")
        return 0
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"experiment error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
