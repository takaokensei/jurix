import pytest

from scripts.evaluate_normative_graph import evaluate


def _row(*, review_kind="synthetic", split="test", target="norma-b"):
    return {
        "case_id": "case-1",
        "norma_key": "norma-a",
        "document_key": "document-a",
        "revision": {"source_text_sha256": "a" * 64},
        "review": {"review_kind": review_kind, "status": "adjudicated" if review_kind == "human" else "pending"},
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

    result = evaluate([first], [reordered], min_human_norms=1)

    assert result["status"] == "evaluated"
    assert result["events_by_action"]["ALTERA"]["f1"] == 1.0
    assert result["resolved_target_ids"]["f1"] == 1.0


def test_wrong_target_is_false_positive_and_false_negative_not_abstention_credit():
    result = evaluate([_row(review_kind="human")], [_row(review_kind="human", target="wrong")], min_human_norms=1)

    assert result["resolved_target_ids"]["false_positive"] == 1
    assert result["resolved_target_ids"]["false_negative"] == 1
    assert result["resolved_target_ids"]["f1"] == 0.0


def test_synthetic_fixture_cannot_pass_human_gate():
    result = evaluate([_row()], [_row()], min_human_norms=1)

    assert result["status"] == "not_evaluated"
    assert result["human_adjudicated_normas"] == 0


def test_relation_chain_may_not_leak_between_splits():
    train = _row(review_kind="human", split="train")
    test = {**train, "case_id": "case-2", "split": "test"}

    with pytest.raises(ValueError, match="leakage"):
        evaluate([train, test], [train, test], min_human_norms=1)


def test_hash_mismatch_blocks_evaluation():
    gold = _row(review_kind="human")
    prediction = _row(review_kind="human")
    prediction["revision"]["source_text_sha256"] = "b" * 64

    with pytest.raises(ValueError, match="source hash mismatch"):
        evaluate([gold], [prediction], min_human_norms=1)
