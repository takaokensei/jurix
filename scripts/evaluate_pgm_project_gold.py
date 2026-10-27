#!/usr/bin/env python3
"""Score RAG predictions against the adopted AI-adjudicated Jurix project gold.

This report is technical project evaluation, not a human-reviewed scientific
result. It deliberately does not call or modify the human adjudication evaluator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    from scripts.collect_normative_rag_experiment import ARMS
    from scripts.pgm_project_gold import DEFAULT_GOLD, validate_gold
except ModuleNotFoundError:
    from collect_normative_rag_experiment import ARMS
    from pgm_project_gold import DEFAULT_GOLD, validate_gold


def _read_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metrics(rows: list[dict]) -> dict:
    recall_hits = 0
    expected_sources = 0
    citation_tp = citation_predicted = citation_expected = 0
    version_correct = version_total = 0
    abstain_correct = abstain_total = 0
    for row in rows:
        expected = set(row["expected_source_ids"])
        retrieved = set(row["retrieved_source_ids"][:5])
        recall_hits += len(expected & retrieved)
        expected_sources += len(expected)
        expected_citations = set(row["expected_citation_ids"])
        cited = set(row.get("cited_gold_citation_ids", []))
        citation_tp += len(expected_citations & cited)
        citation_expected += len(expected_citations)
        cited_records = row.get("cited_source_records", [])
        # Precision's denominator must include every distinct citation emitted,
        # including citations that cannot be mapped to a gold document/article.
        # Otherwise unresolved or out-of-gold citations silently disappear.
        unique_cited_ids = {
            str(record.get("citation_id") or f"unidentified:{index}")
            for index, record in enumerate(cited_records)
        }
        citation_predicted += max(len(unique_cited_ids), len(cited))
        versions = row["expected_versions"]
        actual_versions = row.get("cited_gold_versions", {})
        version_total += len(versions)
        version_correct += sum(actual_versions.get(key) == value for key, value in versions.items())
        if "expected_abstain" in row:
            abstain_total += 1
            abstain_correct += bool(row["abstained"]) == bool(row["expected_abstain"])
    return {
        "cases": len(rows),
        "source_recall_at_5": _ratio(recall_hits, expected_sources),
        "source_relevant_items": expected_sources,
        "citation_precision": _ratio(citation_tp, citation_predicted),
        "citation_recall": _ratio(citation_tp, citation_expected),
        "citation_f1": _ratio(2 * citation_tp, citation_predicted + citation_expected),
        "citation_expected_count": citation_expected,
        "version_exact_accuracy": _ratio(version_correct, version_total),
        "version_cases": version_total,
        "abstention_accuracy": _ratio(abstain_correct, abstain_total),
        "abstention_cases": abstain_total,
    }


def _source_identity_diagnostics(rows: list[dict]) -> dict:
    records = [record for row in rows for record in row.get("retrieved_source_records", [])]
    expected_hashes = {
        source_id.removeprefix("sha256:").lower()
        for row in rows
        for source_id in row.get("expected_source_ids", [])
    }
    hashes = [
        str(record.get("document_sha256") or "").lower()
        for record in records
    ]
    return {
        "retrieved_source_records": len(records),
        "sources_with_document_hash": sum(bool(value) for value in hashes),
        "sources_matching_any_gold_pdf_hash": sum(value in expected_hashes for value in hashes if value),
        "sources_without_gold_hash_match": sum(value not in expected_hashes for value in hashes if value),
        "sources_missing_document_hash": sum(not value for value in hashes),
        "sources_labeled_synthetic": sum(record.get("synthetic_fixture") is True for record in records),
        "gold_document_identity_coverage": _ratio(
            sum(value in expected_hashes for value in hashes if value), len(records)
        ),
    }


def evaluate(gold_path: Path, predictions_path: Path, summary_path: Path) -> dict:
    gold_validation = validate_gold(gold_path)
    if not gold_validation["valid"]:
        raise ValueError("adopted gold failed integrity validation")
    gold = json.loads(gold_path.read_text(encoding="utf-8"))
    reference = (gold_path.parent / gold["reference"]["path"]).resolve()
    query_rows = _read_jsonl(reference / "queries.ai.jsonl")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    adoption_digest = hashlib.sha256(gold_path.read_bytes()).hexdigest()
    if (
        summary.get("project_gold_id") != gold["gold_id"]
        or summary.get("project_gold_adoption_sha256") != adoption_digest
        or summary.get("evaluation_reference_kind") != "project_gold_ai"
        or summary.get("human_gold_present") is not False
    ):
        raise ValueError("collector summary does not match this AI-adjudicated project gold")

    by_case = {row["case_id"]: row for row in query_rows}
    if len(by_case) != gold["expected_counts"]["queries"]:
        raise ValueError("gold query IDs are not unique or expected query count differs")
    predictions = _read_jsonl(predictions_path)
    groups: dict[str, dict[str, dict]] = defaultdict(dict)
    for row in predictions:
        case_id, arm = row.get("case_id"), row.get("arm")
        if case_id not in by_case or arm not in ARMS:
            raise ValueError("prediction contains an unknown gold case or RAG arm")
        if row.get("cache_state") != "cold" or row.get("repeat") != 0:
            continue
        if row.get("evaluation_reference_kind") != "project_gold_ai":
            raise ValueError("prediction row has incorrect evaluation-reference provenance")
        if row.get("human_evidence_review") is not False:
            raise ValueError("AI project-gold predictions must not claim human review")
        if row.get("human_review", {}).get("review_kind") != "ai_project_gold":
            raise ValueError("prediction row lost AI project-gold provenance")
        expected = by_case[case_id]
        for field in ("expected_source_ids", "expected_citation_ids", "expected_versions", "expected_abstain"):
            if row.get(field) != expected.get(field, False if field == "expected_abstain" else None):
                raise ValueError(f"prediction gold labels differ from the frozen reference: {field}")
        if arm in groups[case_id]:
            raise ValueError("duplicate cold prediction for case/arm")
        groups[case_id][arm] = row

    if set(groups) != set(by_case) or any(set(arms) != set(ARMS) for arms in groups.values()):
        raise ValueError("complete paired cold predictions for all adopted gold queries are required")

    per_arm = {
        arm: _metrics([groups[case_id][arm] for case_id in by_case])
        for arm in ARMS
    }
    source_identity = {
        arm: _source_identity_diagnostics([groups[case_id][arm] for case_id in by_case])
        for arm in ARMS
    }
    paired = {}
    for candidate in ARMS[1:]:
        deltas = defaultdict(list)
        for case_id in by_case:
            candidate_metrics = _metrics([groups[case_id][candidate]])
            baseline_metrics = _metrics([groups[case_id]["baseline"]])
            for metric in ("source_recall_at_5", "citation_f1", "version_exact_accuracy", "abstention_accuracy"):
                left, right = candidate_metrics[metric], baseline_metrics[metric]
                if left is not None and right is not None:
                    deltas[metric].append(left - right)
        paired[candidate + "_vs_baseline"] = {
            metric: {
                "paired_case_count": len(values),
                "mean_delta": sum(values) / len(values) if values else None,
                "confidence_interval": None,
                "inference": "descriptive_only_ai_adjudicated_project_gold",
            }
            for metric, values in deltas.items()
        }
    source_identity_usable = all(
        source_identity[arm]["sources_matching_any_gold_pdf_hash"] > 0
        for arm in ARMS
    )
    source_metadata_present = all(
        all(isinstance(groups[case_id][arm].get("retrieved_source_records"), list) for case_id in by_case)
        for arm in ARMS
    )
    return {
        "schema_version": "jurix-pgm-project-gold-evaluation-v1",
        "status": "technical_evaluation_against_ai_adjudicated_project_gold",
        "gold_id": gold["gold_id"],
        "gold_adoption_sha256": adoption_digest,
        "gold_validation": {
            "valid": gold_validation["valid"],
            "review_kind": gold_validation["review_kind"],
            "independent_review": gold_validation["independent_review"],
            "scientific_human_gold_ready": gold_validation["scientific_human_gold_ready"],
        },
        "prediction_sha256": hashlib.sha256(predictions_path.read_bytes()).hexdigest(),
        "collection_summary_sha256": hashlib.sha256(summary_path.read_bytes()).hexdigest(),
        "query_count": len(by_case),
        "paired_cold_groups": len(groups),
        "arms": per_arm,
        "source_identity_diagnostics": source_identity,
        "collection_complete": True,
        "source_metadata_present": source_metadata_present,
        "source_quality_comparison_usable": source_metadata_present and source_identity_usable,
        "source_quality_comparison_blockers": [
            arm for arm in ARMS
            if source_identity[arm]["sources_matching_any_gold_pdf_hash"] == 0
        ],
        "paired_descriptive_deltas": paired,
        "scientific_claim_allowed": False,
        "limitations": [
            "Reference adjudication was performed by AI and was not independently reviewed by humans.",
            "This is a retrospective, development-exposed, focal gold; it is not exhaustive segmentation or a measure of whole-corpus legal accuracy.",
            "Unannotated relation events are not automatically false positives.",
            "No confidence intervals or population-level claims are produced.",
        ],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", type=Path, default=DEFAULT_GOLD)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--summary", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        report = evaluate(args.gold, args.predictions, args.summary)
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            with args.output.open("x", encoding="utf-8", newline="\n") as target:
                target.write(serialized)
        else:
            print(serialized, end="")
        return 0
    except (OSError, ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
        print(f"project-gold evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
