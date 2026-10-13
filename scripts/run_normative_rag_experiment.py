#!/usr/bin/env python3
"""Compare paired exported RAG arms without contacting the app or an LLM."""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import statistics
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

ARMS = ("baseline", "graph", "graph_temporal")
FIXED_CONFIG = ("corpus_revision", "model", "temperature", "token_budget", "hardware")
MIN_SCIENTIFIC_NORMS = 20
MIN_SCIENTIFIC_CHAINS = 3
BOOTSTRAP_REPLICATES = 2_000
BOOTSTRAP_SEED = 20261008
ALLOWED_REVIEWED_USE = {"licensed", "public_record_reviewed"}
_CI_METRICS = ("retrieval_recall_at_5", "citation_f1", "version_exact_accuracy", "abstention_accuracy")


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


def load_sampling_report(path: Path) -> dict:
    """Load a hash-bound selection report; a row-provided digest is not proof."""
    raw = path.read_bytes()
    report = json.loads(raw)
    if not isinstance(report, dict) or report.get("schema_version") != 1:
        raise ValueError("sampling report must be a schema_version 1 JSON object")
    if not isinstance(report.get("selection_method"), str) or not report["selection_method"].strip():
        raise ValueError("sampling report requires a selection_method")
    if not isinstance(report.get("seed"), str | int) or isinstance(report.get("seed"), bool):
        raise ValueError("sampling report requires a string or integer seed")
    if not isinstance(report.get("strata"), dict) or not report["strata"]:
        raise ValueError("sampling report requires non-empty strata metadata")
    created_at = report.get("created_at")
    if not isinstance(created_at, str):
        raise ValueError("sampling report requires a timezone-aware created_at")
    try:
        timestamp = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("sampling report requires a timezone-aware created_at") from exc
    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("sampling report requires a timezone-aware created_at")

    units = report.get("units")
    if not isinstance(units, list) or not units:
        raise ValueError("sampling report requires a non-empty units list")
    normalized_units = set()
    for unit in units:
        if not isinstance(unit, dict):
            raise ValueError("sampling report units must be objects")
        norma_key = unit.get("norma_key")
        document_key = unit.get("document_key")
        condition = unit.get("condition_of_use")
        if not all(isinstance(value, str) and value.strip() for value in (norma_key, document_key)):
            raise ValueError("sampling report units require stable norma_key and document_key values")
        if condition not in ALLOWED_REVIEWED_USE:
            raise ValueError("sampling report unit has an unresolved condition_of_use")
        identity = (norma_key.strip(), document_key.strip(), condition)
        if identity in normalized_units:
            raise ValueError("sampling report contains duplicate units")
        normalized_units.add(identity)

    chains = report.get("relation_chain_keys")
    if (
        not isinstance(chains, list)
        or any(not isinstance(key, str) or not key.strip() for key in chains)
        or len(set(chains)) != len(chains)
    ):
        raise ValueError("sampling report requires unique non-empty relation_chain_keys")
    return {
        "data": report,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "units": normalized_units,
        "relation_chain_keys": set(chains),
    }


def _is_human_adjudicated(row: dict) -> bool:
    review = row.get("human_review")
    if not isinstance(review, dict):
        return False
    reviewer_id = review.get("reviewer_id")
    reviewed_at = review.get("reviewed_at")
    if (
        review.get("review_kind") != "human"
        or review.get("status") not in {"adjudicated", "approved"}
        or not isinstance(reviewer_id, str)
        or not reviewer_id.strip()
        or not isinstance(reviewed_at, str)
        or not reviewed_at.strip()
    ):
        return False
    try:
        timestamp = datetime.fromisoformat(reviewed_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return timestamp.tzinfo is not None and timestamp.utcoffset() is not None


def _case_metrics(row: dict) -> dict[str, float | None]:
    expected_sources = set(row.get("expected_source_ids", []))
    retrieved_sources = list(row.get("retrieved_source_ids", []))
    expected_citations = set(row.get("expected_citation_ids", []))
    cited = set(row.get("cited_citation_ids", []))
    expected_versions = row.get("expected_versions", {})
    actual_versions = row.get("cited_versions", {})
    citation_denominator = len(cited) + len(expected_citations)
    return {
        "retrieval_recall_at_5": (
            len(set(retrieved_sources[:5]) & expected_sources) / len(expected_sources)
            if expected_sources
            else None
        ),
        "citation_f1": (
            2 * len(cited & expected_citations) / citation_denominator
            if citation_denominator
            else None
        ),
        "version_exact_accuracy": (
            sum(actual_versions.get(key) == value for key, value in expected_versions.items())
            / len(expected_versions)
            if expected_versions
            else None
        ),
        "abstention_accuracy": (
            float(bool(row.get("abstained")) == bool(row["expected_abstain"]))
            if "expected_abstain" in row
            else None
        ),
    }


def _percentile(sorted_values: list[float], fraction: float) -> float:
    index = round((len(sorted_values) - 1) * fraction)
    return sorted_values[index]


def _clustered_paired_intervals(paired: dict, cache_state: str) -> dict:
    """Paired percentile bootstrap over independent legal norms, never token rows."""
    report = {}
    for candidate, reference in (("graph", "baseline"), ("graph_temporal", "baseline")):
        clusters_by_metric: dict[str, dict[str, list[float]]] = {
            metric: defaultdict(list) for metric in _CI_METRICS
        }
        for key, arms in paired.items():
            if key[2] != cache_state:
                continue
            rows = [arms[arm] for arm in (candidate, reference)]
            if not all(_is_human_adjudicated(row) for row in rows):
                continue
            norma_key = str(rows[0].get("norma_key") or "").strip()
            if not norma_key:
                continue
            candidate_metrics = _case_metrics(arms[candidate])
            reference_metrics = _case_metrics(arms[reference])
            for metric in _CI_METRICS:
                left, right = candidate_metrics[metric], reference_metrics[metric]
                if left is not None and right is not None:
                    clusters_by_metric[metric][norma_key].append(left - right)

        comparison = {}
        for metric, clusters in clusters_by_metric.items():
            cluster_deltas = [statistics.fmean(values) for values in clusters.values() if values]
            result = {
                "cluster_unit": "norma_key",
                "n_norm_clusters": len(cluster_deltas),
                "mean_paired_delta": statistics.fmean(cluster_deltas) if cluster_deltas else None,
                "confidence_level": 0.95,
                "bootstrap_replicates": BOOTSTRAP_REPLICATES if len(cluster_deltas) >= MIN_SCIENTIFIC_NORMS else 0,
                "ci_95": None,
                "status": "not_estimated_small_n",
            }
            if len(cluster_deltas) >= MIN_SCIENTIFIC_NORMS:
                rng = random.Random(f"{BOOTSTRAP_SEED}:{cache_state}:{candidate}:{metric}")
                estimates = sorted(
                    statistics.fmean(rng.choices(cluster_deltas, k=len(cluster_deltas)))
                    for _ in range(BOOTSTRAP_REPLICATES)
                )
                result["ci_95"] = {
                    "lower": _percentile(estimates, 0.025),
                    "upper": _percentile(estimates, 0.975),
                }
                result["status"] = "estimated_cluster_bootstrap"
            comparison[metric] = result
        report[f"{candidate}_vs_{reference}"] = comparison
    return report


def _rank_metrics(rows: list[dict]) -> dict:
    rows = [row for row in rows if _is_human_adjudicated(row)]
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
        "reviewed_cases": len(rows),
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


def analyze(rows: list[dict], *, sampling_report: dict | None = None) -> dict:
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
            for field in (
                "expected_source_ids",
                "expected_citation_ids",
                "expected_versions",
                "expected_abstain",
                "norma_key",
                "relation_chain_keys",
                "human_review",
                "condition_of_use",
                "sampling_report_sha256",
                "split",
            ):
                if arms[arm].get(field) != baseline.get(field):
                    raise ValueError(f"paired gold annotation differs between arms for {key}: {field}")

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
    reviewed_rows = [row for row in rows if _is_human_adjudicated(row)]
    reviewed_normas = {
        str(row.get("norma_key") or "").strip()
        for row in reviewed_rows
        if str(row.get("norma_key") or "").strip()
    }
    reviewed_chains = {
        chain
        for row in reviewed_rows
        for chain in row.get("relation_chain_keys", [])
        if isinstance(chain, str) and chain.strip()
    }
    conditions_resolved = bool(reviewed_rows) and all(
        row.get("condition_of_use") in ALLOWED_REVIEWED_USE for row in reviewed_rows
    )
    sampling_report_present = False
    if sampling_report is not None and reviewed_rows:
        expected_hash = sampling_report["sha256"]
        row_hashes_match = all(row.get("sampling_report_sha256") == expected_hash for row in reviewed_rows)
        adjudicated_units = {
            (
                str(row.get("norma_key") or "").strip(),
                str(row.get("document_key") or "").strip(),
                row.get("condition_of_use"),
            )
            for row in reviewed_rows
        }
        adjudicated_chains = {
            chain
            for row in reviewed_rows
            for chain in row.get("relation_chain_keys", [])
            if isinstance(chain, str) and chain.strip()
        }
        sampling_report_present = (
            row_hashes_match
            and adjudicated_units == sampling_report["units"]
            and adjudicated_chains == sampling_report["relation_chain_keys"]
        )
    reviewed_case_groups = {
        (row["case_id"], row.get("repeat", 0), row["cache_state"])
        for row in reviewed_rows
    }
    report["human_review"] = {
        "adjudicated_prediction_rows": len(reviewed_rows),
        "adjudicated_case_groups": len(reviewed_case_groups),
        "distinct_normas": len(reviewed_normas),
        "distinct_relation_chains": len(reviewed_chains),
        "excluded_nonhuman_or_incomplete_rows": len(rows) - len(reviewed_rows),
        "conditions_of_use_resolved": conditions_resolved,
        "sampling_report_present": sampling_report_present,
        "sampling_report_sha256": sampling_report.get("sha256") if sampling_report_present else None,
    }
    report["paired_confidence_intervals"] = {
        state: _clustered_paired_intervals(paired, state) for state in ("cold", "warm")
    }
    report["status"] = "human_reviewed_experiment" if reviewed_rows else "technical_smoke_only"
    report["scientific_claim_allowed"] = (
        len(reviewed_normas) >= MIN_SCIENTIFIC_NORMS
        and len(reviewed_chains) >= MIN_SCIENTIFIC_CHAINS
        and conditions_resolved
        and sampling_report_present
    )
    report["sample_warning"] = "p95 latencies are reported only for n >= 20; small samples are not population estimates."
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--sampling-report", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        raw = args.input.read_bytes()
        sampling_report = load_sampling_report(args.sampling_report) if args.sampling_report else None
        report = analyze(load_cases(args.input), sampling_report=sampling_report)
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
