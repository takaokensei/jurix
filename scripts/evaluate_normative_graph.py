#!/usr/bin/env python3
"""Offline, hash-bound evaluation of normative extraction and relation predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path


def _read_jsonl(path: Path) -> list[dict]:
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        value = json.loads(line)
        if not isinstance(value, dict):
            raise ValueError(f"{path.name}:{line_number}: each row must be an object")
        rows.append(value)
    if not rows:
        raise ValueError(f"{path.name}: empty input")
    return rows


def _index(rows: list[dict], label: str) -> dict[str, dict]:
    indexed = {}
    for row in rows:
        case_id = row.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError(f"{label}: case_id is required")
        if case_id in indexed:
            raise ValueError(f"{label}: duplicate case_id {case_id}")
        revision = row.get("revision") or {}
        digest = revision.get("source_text_sha256", "")
        if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
            raise ValueError(f"{label}:{case_id}: invalid source_text_sha256")
        if not row.get("norma_key") or not row.get("document_key"):
            raise ValueError(f"{label}:{case_id}: norma_key/document_key required")
        indexed[case_id] = row
    return indexed


def _prf(expected: set, predicted: set) -> dict:
    true_positive = len(expected & predicted)
    precision = true_positive / len(predicted) if predicted else 0.0
    recall = true_positive / len(expected) if expected else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "true_positive": true_positive,
        "false_positive": len(predicted - expected),
        "false_negative": len(expected - predicted),
        "precision": precision,
        "recall": recall,
        "f1": f1,
    }


def _span_key(row: dict, span: dict) -> tuple:
    return (row["document_key"], span.get("label"), span.get("start"), span.get("end"))


def _event_identity(event: dict) -> tuple:
    return (
        event.get("source_span_id"),
        event.get("action"),
        event.get("target_norma_key"),
        event.get("target_device_key"),
    )


def _is_human_adjudicated(review: dict) -> bool:
    """Require the complete reviewer provenance defined by graph protocol v2."""
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


def evaluate(
    gold_rows: list[dict],
    predicted_rows: list[dict],
    *,
    min_human_norms: int = 20,
    min_human_chains: int = 3,
) -> dict:
    if min_human_norms < 1 or min_human_chains < 1:
        raise ValueError("human norm and chain thresholds must be positive")
    gold = _index(gold_rows, "gold")
    predicted = _index(predicted_rows, "predictions")
    if gold.keys() != predicted.keys():
        raise ValueError("gold and predictions must contain the same case_id set")

    gold_spans, predicted_spans = set(), set()
    gold_events, predicted_events = set(), set()
    action_metrics = defaultdict(lambda: [set(), set()])
    resolved_expected, resolved_predicted = set(), set()
    date_errors = date_cases = 0
    human_normas = set()
    human_chains = set()
    included_cases = 0
    excluded_cases = 0
    train_chains, test_chains = set(), set()

    for case_id, expected in gold.items():
        actual = predicted[case_id]
        if expected["norma_key"] != actual.get("norma_key") or expected["document_key"] != actual.get("document_key"):
            raise ValueError(f"{case_id}: norma/document identity mismatch")
        if expected["revision"].get("source_text_sha256") != (actual.get("revision") or {}).get("source_text_sha256"):
            raise ValueError(f"{case_id}: source hash mismatch")
        review = expected.get("review") or {}
        chains = set(expected.get("relation_chain_keys", []))
        if expected.get("split") == "train":
            train_chains |= chains
        elif expected.get("split") == "test":
            test_chains |= chains
        if not _is_human_adjudicated(review):
            excluded_cases += 1
            continue
        included_cases += 1
        human_normas.add(expected["norma_key"])
        human_chains.update(chain for chain in chains if isinstance(chain, str) and chain.strip())
        gold_spans |= {_span_key(expected, span) for span in expected.get("spans", [])}
        predicted_spans |= {_span_key(actual, span) for span in actual.get("spans", [])}

        expected_events = {_event_identity(event) for event in expected.get("events", [])}
        actual_events = {_event_identity(event) for event in actual.get("events", [])}
        gold_events |= expected_events
        predicted_events |= actual_events
        for action in {event.get("action") for event in expected.get("events", []) + actual.get("events", [])}:
            action_metrics[action][0].update(event for event in expected_events if event[1] == action)
            action_metrics[action][1].update(event for event in actual_events if event[1] == action)
        resolved_expected |= {
            _event_identity(event) for event in expected.get("events", [])
            if event.get("resolution") == "resolved" and event.get("target_norma_key")
        }
        resolved_predicted |= {
            _event_identity(event) for event in actual.get("events", [])
            if event.get("resolution") == "resolved" and event.get("target_norma_key")
        }
        expected_dates = {
            _event_identity(event): (event.get("effective_date") or {}).get("value")
            for event in expected.get("events", [])
            if (event.get("effective_date") or {}).get("status") == "confirmed"
        }
        actual_dates = {
            _event_identity(event): (event.get("effective_date") or {}).get("value")
            for event in actual.get("events", [])
            if (event.get("effective_date") or {}).get("status") == "confirmed"
        }
        for identity, expected_date in expected_dates.items():
            date_cases += 1
            date_errors += actual_dates.get(identity) != expected_date

    leakage = sorted(train_chains & test_chains)
    if leakage:
        raise ValueError("relation chain leakage across train/test split")
    evaluated = (
        len(human_normas) >= min_human_norms
        and len(human_chains) >= min_human_chains
    )
    result = {
        "status": "evaluated" if evaluated else "not_evaluated",
        "metrics_scope": (
            "human_adjudicated_only"
            if evaluated
            else "human_adjudicated_subset_not_scientifically_evaluated"
            if included_cases
            else "no_eligible_human_gold"
        ),
        "human_adjudicated_normas": len(human_normas),
        "human_adjudicated_relation_chains": len(human_chains),
        "required_human_normas": min_human_norms,
        "required_human_relation_chains": min_human_chains,
        "included_human_adjudicated_cases": included_cases,
        "excluded_synthetic_or_incomplete_review_cases": excluded_cases,
        "synthetic_or_unreviewed_rows_counted_as_gold": 0,
        "span_exact": _prf(gold_spans, predicted_spans),
        "events_by_action": {
            action: _prf(*sets) for action, sets in sorted(action_metrics.items())
        },
        "resolved_target_ids": _prf(resolved_expected, resolved_predicted),
        "confirmed_effective_dates": {
            "cases": date_cases,
            "errors": date_errors,
            "exact_accuracy": (date_cases - date_errors) / date_cases if date_cases else None,
        },
        "split_chain_leakage": 0,
    }
    return result


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--predictions", required=True, type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--min-human-normas", type=int, default=20)
    parser.add_argument("--min-human-chains", type=int, default=3)
    args = parser.parse_args(argv)
    try:
        report = evaluate(
            _read_jsonl(args.gold),
            _read_jsonl(args.predictions),
            min_human_norms=args.min_human_normas,
            min_human_chains=args.min_human_chains,
        )
        report["input_sha256"] = {"gold": _file_hash(args.gold), "predictions": _file_hash(args.predictions)}
        serialized = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        if args.output:
            args.output.write_text(serialized, encoding="utf-8", newline="\n")
        else:
            print(serialized, end="")
        return 0 if report["status"] == "evaluated" else 3
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"evaluation error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
