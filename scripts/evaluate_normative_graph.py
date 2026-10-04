#!/usr/bin/env python3
"""Offline, hash-bound evaluation of normative extraction and relation predictions."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from collections import defaultdict
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


def evaluate(gold_rows: list[dict], predicted_rows: list[dict], *, min_human_norms: int = 20) -> dict:
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
    train_chains, test_chains = set(), set()

    for case_id, expected in gold.items():
        actual = predicted[case_id]
        if expected["norma_key"] != actual.get("norma_key") or expected["document_key"] != actual.get("document_key"):
            raise ValueError(f"{case_id}: norma/document identity mismatch")
        if expected["revision"].get("source_text_sha256") != (actual.get("revision") or {}).get("source_text_sha256"):
            raise ValueError(f"{case_id}: source hash mismatch")
        review = expected.get("review") or {}
        if review.get("review_kind") == "human" and review.get("status") == "adjudicated":
            human_normas.add(expected["norma_key"])
        chains = set(expected.get("relation_chain_keys", []))
        if expected.get("split") == "train":
            train_chains |= chains
        elif expected.get("split") == "test":
            test_chains |= chains
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
    evaluated = len(human_normas) >= max(1, int(min_human_norms))
    result = {
        "status": "evaluated" if evaluated else "not_evaluated",
        "metrics_scope": "human_adjudicated_only" if evaluated else "synthetic_fixture_smoke_not_scientific",
        "human_adjudicated_normas": len(human_normas),
        "required_human_normas": max(1, int(min_human_norms)),
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
    args = parser.parse_args(argv)
    try:
        report = evaluate(_read_jsonl(args.gold), _read_jsonl(args.predictions), min_human_normas=args.min_human_normas)
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
