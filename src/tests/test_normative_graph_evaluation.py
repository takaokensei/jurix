import json

import pytest

from scripts.evaluate_normative_graph import evaluate, main


def _row(*, review_kind="synthetic", split="test", target="norma-b"):
    return {
        "case_id": "case-1",
        "norma_key": "norma-a",
        "document_key": "document-a",
        "revision": {"source_text_sha256": "a" * 64},
        "review": {
            "review_kind": review_kind,
            "status": "adjudicated" if review_kind == "human" else "pending",
            "reviewer_id": "reviewer-qa" if review_kind == "human" else None,
            "reviewed_at": "2026-10-08T12:00:00+00:00" if review_kind == "human" else None,
        },
        "split": split,
        "relation_chain_keys": ["chain-1"],
        "spans": [{"label": "artigo", "start": 0, "end": 10, "quote": "Art. 1º ..."}],
        "events": [{
            "source_span_id": "span-a",
            "action": "ALTERA",
            "target_norma_key": target,
            "target_device_key": "device-5",
            "resolution": "resolved",
            "effective_date": {"status": "confirmed", "value": "2026-01-01"},
        }],
    }


def test_event_scoring_is_invariant_to_prediction_order():
    first = _row(review_kind="human")
    reordered = {**first, "events": list(reversed(first["events"]))}

    result = evaluate([first], [reordered], min_human_norms=1, min_human_chains=1)

    assert result["status"] == "evaluated"
    assert result["events_by_action"]["ALTERA"]["f1"] == 1.0
    assert result["resolved_target_ids"]["f1"] == 1.0


def test_wrong_target_is_false_positive_and_false_negative_not_abstention_credit():
    result = evaluate(
        [_row(review_kind="human")],
        [_row(review_kind="human", target="wrong")],
        min_human_norms=1,
        min_human_chains=1,
    )

    assert result["resolved_target_ids"]["false_positive"] == 1
    assert result["resolved_target_ids"]["false_negative"] == 1
    assert result["resolved_target_ids"]["f1"] == 0.0


def test_synthetic_fixture_cannot_pass_human_gate():
    result = evaluate([_row()], [_row()], min_human_norms=1)

    assert result["status"] == "not_evaluated"
    assert result["human_adjudicated_normas"] == 0
    assert result["synthetic_or_unreviewed_rows_counted_as_gold"] == 0


def test_cli_exits_three_and_reports_not_evaluated_without_adjudicated_gold(tmp_path, capsys):
    gold_path = tmp_path / "gold.jsonl"
    prediction_path = tmp_path / "predictions.jsonl"
    row = _row()
    gold_path.write_text(json.dumps(row) + "\n", encoding="utf-8")
    prediction_path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    exit_code = main([
        "--gold", str(gold_path),
        "--predictions", str(prediction_path),
        "--min-human-normas", "1",
        "--min-human-chains", "1",
    ])

    output = json.loads(capsys.readouterr().out)
    assert exit_code == 3
    assert output["status"] == "not_evaluated"
    assert output["human_adjudicated_normas"] == 0
    assert output["synthetic_or_unreviewed_rows_counted_as_gold"] == 0


def test_relation_chain_may_not_leak_between_splits():
    train = _row(review_kind="human", split="train")
    test = {**train, "case_id": "case-2", "split": "test"}

    with pytest.raises(ValueError, match="leakage"):
        evaluate([train, test], [train, test], min_human_norms=1, min_human_chains=1)


def test_hash_mismatch_blocks_evaluation():
    gold = _row(review_kind="human")
    prediction = _row(review_kind="human")
    prediction["revision"]["source_text_sha256"] = "b" * 64

    with pytest.raises(ValueError, match="source hash mismatch"):
        evaluate([gold], [prediction], min_human_norms=1, min_human_chains=1)


def test_synthetic_case_cannot_change_metrics_for_adjudicated_cases():
    reviewed_gold = _row(review_kind="human")
    reviewed_prediction = _row(review_kind="human")
    synthetic_gold = {**_row(), "case_id": "synthetic-case", "norma_key": "norma-synthetic"}
    synthetic_prediction = {
        **_row(target="different-target"),
        "case_id": "synthetic-case",
        "norma_key": "norma-synthetic",
    }

    result = evaluate(
        [reviewed_gold, synthetic_gold],
        [reviewed_prediction, synthetic_prediction],
        min_human_norms=1,
        min_human_chains=1,
    )

    assert result["events_by_action"]["ALTERA"]["f1"] == 1.0
    assert result["included_human_adjudicated_cases"] == 1
    assert result["excluded_synthetic_or_incomplete_review_cases"] == 1
    assert result["synthetic_or_unreviewed_rows_counted_as_gold"] == 0


@pytest.mark.parametrize(
    "field,value",
    [("reviewer_id", None), ("reviewed_at", "2026-10-08"), ("reviewed_at", "2026-10-08T12:00:00")],
)
def test_adjudication_without_reviewer_and_timezone_aware_timestamp_is_excluded(field, value):
    gold = _row(review_kind="human")
    gold["review"][field] = value

    result = evaluate(
        [gold], [_row(review_kind="human")], min_human_norms=1, min_human_chains=1
    )

    assert result["status"] == "not_evaluated"
    assert result["human_adjudicated_normas"] == 0
    assert result["included_human_adjudicated_cases"] == 0


def test_minimum_relation_chain_gate_is_reported_separately():
    gold = _row(review_kind="human")

    result = evaluate([gold], [_row(review_kind="human")], min_human_norms=1)

    assert result["status"] == "not_evaluated"
    assert result["human_adjudicated_normas"] == 1
    assert result["human_adjudicated_relation_chains"] == 1
    assert result["required_human_relation_chains"] == 3


def test_approved_is_an_adjudicated_status_when_reviewer_provenance_is_complete():
    gold = _row(review_kind="human")
    gold["review"]["status"] = "approved"

    result = evaluate([gold], [_row(review_kind="human")], min_human_norms=1, min_human_chains=1)

    assert result["included_human_adjudicated_cases"] == 1
    assert result["status"] == "evaluated"
