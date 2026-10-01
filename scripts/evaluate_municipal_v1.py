#!/usr/bin/env python3
"""Evaluate frozen municipal parser, event, or retrieval predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path


def _load_jsonl(path: Path) -> list[dict]:
    rows = []
    for number, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not raw.strip():
            continue
        try:
            item = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{number}: JSON inválido") from exc
        if not isinstance(item, dict) or not isinstance(item.get("case_id"), str):
            raise ValueError(f"{path.name}:{number}: objeto deve conter case_id")
        rows.append(item)
    if not rows:
        raise ValueError(f"{path.name}: conjunto vazio")
    return rows


def _index(gold: list[dict], predictions: list[dict]) -> tuple[dict, dict]:
    gold_by_id = {row["case_id"]: row for row in gold}
    pred_by_id = {row["case_id"]: row for row in predictions}
    if len(gold_by_id) != len(gold) or len(pred_by_id) != len(predictions):
        raise ValueError("case_id duplicado")
    if gold_by_id.keys() != pred_by_id.keys():
        missing = sorted(gold_by_id.keys() - pred_by_id.keys())
        extra = sorted(pred_by_id.keys() - gold_by_id.keys())
        raise ValueError(f"casos incompatíveis: ausentes={missing}; extras={extra}")
    return gold_by_id, pred_by_id


def _prf(tp: int, predicted: int, expected: int) -> dict[str, float | int]:
    precision = tp / predicted if predicted else 0.0
    recall = tp / expected if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": tp,
        "predicted": predicted,
        "expected": expected,
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def evaluate_parser(gold: list[dict], predictions: list[dict]) -> dict:
    gold_by_id, pred_by_id = _index(gold, predictions)
    counts = defaultdict(lambda: [0, 0, 0])
    for case_id, expected in gold_by_id.items():
        actual = pred_by_id[case_id]
        expected_spans = {
            (item["label"], item["start"], item["end"]) for item in expected.get("spans", [])
        }
        predicted_spans = {
            (item["label"], item["start"], item["end"]) for item in actual.get("spans", [])
        }
        for label in {item[0] for item in expected_spans | predicted_spans}:
            target = {item for item in expected_spans if item[0] == label}
            candidate = {item for item in predicted_spans if item[0] == label}
            counts[label][0] += len(target & candidate)
            counts[label][1] += len(candidate)
            counts[label][2] += len(target)
    return {"by_label": {label: _prf(*values) for label, values in sorted(counts.items())}}


def evaluate_events(gold: list[dict], predictions: list[dict]) -> dict:
    gold_by_id, pred_by_id = _index(gold, predictions)
    matrix = defaultdict(Counter)
    target = {"correct": 0, "evaluated": 0}
    for case_id, expected in gold_by_id.items():
        expected_events = expected.get("events", [])
        predicted_events = pred_by_id[case_id].get("events", [])
        for index in range(max(len(expected_events), len(predicted_events))):
            gold_event = expected_events[index] if index < len(expected_events) else {}
            pred_event = predicted_events[index] if index < len(predicted_events) else {}
            gold_action = gold_event.get("action", "missing")
            pred_action = pred_event.get("action", "missing")
            matrix[gold_action][pred_action] += 1
            if "target_key" in gold_event:
                target["evaluated"] += 1
                target["correct"] += gold_event.get("target_key") == pred_event.get("target_key")
    return {
        "confusion_matrix": {label: dict(counts) for label, counts in sorted(matrix.items())},
        "target_accuracy": target["correct"] / target["evaluated"] if target["evaluated"] else None,
        "target_cases": target["evaluated"],
    }


def evaluate_rag(gold: list[dict], predictions: list[dict]) -> dict:
    gold_by_id, pred_by_id = _index(gold, predictions)
    ranks = []
    recall_hits = {1: 0, 3: 0, 5: 0}
    recall_expected = 0
    citation_tp = citation_total = citation_expected = 0
    abstention_correct = abstention_total = temporal_errors = temporal_cases = 0
    latencies = defaultdict(list)
    support_reviewed = True
    for case_id, expected in gold_by_id.items():
        actual = pred_by_id[case_id]
        relevant = set(expected.get("expected_source_ids", []))
        retrieved = actual.get("retrieved_source_ids", [])
        if relevant:
            recall_expected += len(relevant)
            for k in recall_hits:
                recall_hits[k] += len(set(retrieved[:k]) & relevant)
            ranks.append(
                next((1 / (i + 1) for i, source in enumerate(retrieved) if source in relevant), 0.0)
            )
        citations = set(actual.get("cited_source_ids", []))
        citation_tp += len(citations & relevant)
        citation_total += len(citations)
        citation_expected += len(relevant)
        if "answerable" in expected:
            abstention_total += 1
            abstention_correct += bool(actual.get("abstained")) == (not expected["answerable"])
        if expected.get("temporal_reviewed"):
            temporal_cases += 1
            temporal_errors += actual.get("temporal_result") != expected.get("temporal_expected")
        if expected.get("support_reviewed") is not True:
            support_reviewed = False
        for field in ("ttft_ms", "final_ms"):
            value = actual.get(field)
            if isinstance(value, int | float) and value >= 0:
                latencies[field].append(value)
    sorted_latency = {
        field: {"n": len(values), "median_ms": sorted(values)[len(values) // 2]}
        for field, values in latencies.items()
    }
    return {
        "retrieval": {
            f"recall@{k}": recall_hits[k] / recall_expected if recall_expected else None
            for k in recall_hits
        },
        "mrr": sum(ranks) / len(ranks) if ranks else None,
        "citation_precision": citation_tp / citation_total if citation_total else 0.0,
        "citation_recall": citation_tp / citation_expected if citation_expected else None,
        "abstention_accuracy": abstention_correct / abstention_total if abstention_total else None,
        "temporal_error_rate": temporal_errors / temporal_cases if temporal_cases else None,
        "human_claim_support": "evaluated"
        if support_reviewed
        else "not_evaluated: human review absent",
        "latency": sorted_latency,
        "cases_without_expected_sources_excluded": sum(
            not bool(row.get("expected_source_ids")) for row in gold_by_id.values()
        ),
    }


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="mode", required=True)
    for mode in ("parser", "events", "rag"):
        sub = subparsers.add_parser(mode)
        sub.add_argument("--gold", type=Path, required=True)
        sub.add_argument("--predictions", type=Path, required=True)
        sub.add_argument("--output", type=Path, required=True)
        sub.add_argument("--corpus-hash", required=True)
        sub.add_argument("--system-version", required=True)
    args = parser.parse_args(argv)
    gold = _load_jsonl(args.gold)
    predictions = _load_jsonl(args.predictions)
    result = {
        "schema_version": 1,
        "mode": args.mode,
        "generated_at": datetime.now(UTC).isoformat(),
        "evidence_status": "frozen synthetic/manual inputs; not a municipal quality certification",
        "inputs": {
            "gold_sha256": _sha256(args.gold),
            "predictions_sha256": _sha256(args.predictions),
            "corpus_hash": args.corpus_hash,
            "system_version": args.system_version,
            "case_count": len(gold),
        },
        "metrics": {
            "parser": evaluate_parser(gold, predictions),
            "events": evaluate_events(gold, predictions),
            "rag": evaluate_rag(gold, predictions),
        }[args.mode],
    }
    args.output.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
