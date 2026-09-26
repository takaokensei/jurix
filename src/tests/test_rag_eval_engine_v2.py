from src.processing.rag_eval_engine import (
    CaseResult,
    evaluate_cases,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)


def test_recall_and_precision():
    predicted = ["a", "b", "c"]
    expected = {"b", "c"}
    assert recall_at_k(predicted, expected, 1) == 0.0
    assert recall_at_k(predicted, expected, 3) == 1.0
    assert precision_at_k(predicted, expected, 2) == 0.5


def test_mrr():
    assert reciprocal_rank(["x", "b"], {"b"}) == 0.5
    assert reciprocal_rank(["x", "y"], {"b"}) == 0.0


def test_evaluate_cases():
    cases = [
        CaseResult(
            case_id="a",
            answerable=True,
            predicted_sources=("s1", "s2"),
            expected_sources=("s2",),
            reciprocal_rank=0.5,
            citations_predicted=("c1",),
            citations_expected=("c1",),
            grounded=True,
        ),
        CaseResult(
            case_id="b",
            answerable=False,
            predicted_sources=(),
            expected_sources=(),
            reciprocal_rank=1.0,
            grounded=True,
        ),
    ]
    report = evaluate_cases(cases)
    assert report["cases"] == 2
    assert report["recall@3"] == 1.0
    assert report["mrr"] > 0
