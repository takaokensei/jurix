from pathlib import Path

from scripts.run_legal_benchmark_v1 import DEFAULT_ENDPOINT, extract_answer, load_cases
from scripts.run_rag_contract_benchmark import validate_cases
from src.processing.rag_benchmark import BenchmarkCase, BenchmarkResult, evaluate


def test_benchmark_metrics_are_deterministic():
    cases = [BenchmarkCase("Q1", frozenset({"10", "20"}), frozenset({"10"}))]
    results = [BenchmarkResult("Q1", ("30", "20", "10"), frozenset({"10"}), True)]
    metrics = evaluate(cases, results)
    assert metrics["recall@1"] == 0.0
    assert metrics["recall@3"] == 1.0
    assert metrics["precision@3"] == 0.666667
    assert metrics["mrr"] == 0.5
    assert metrics["citation_precision"] == 1.0
    assert metrics["citation_recall"] == 1.0
    assert metrics["groundedness"] == 1.0


def test_live_benchmark_uses_registered_json_endpoint_and_real_case_schema():
    assert DEFAULT_ENDPOINT == "/api/v1/search/answer/"
    cases = load_cases(Path("benchmarks/rag/legal/v1/cases.jsonl"))
    assert cases
    assert validate_cases(cases) is None


def test_sse_benchmark_uses_final_answer_once_instead_of_duplicating_chunks():
    raw = (
        'data: {"type":"chunk","chunk":"Resposta parcial"}\n\n'
        'data: {"type":"done","answer":"Resposta final"}\n\n'
        'data: {"type":"status","status":"completed"}\n\n'
    )
    assert extract_answer(raw, "text/event-stream") == "Resposta final"


def test_sse_benchmark_rejects_failed_or_incomplete_streams():
    import pytest

    with pytest.raises(ValueError, match="completion event"):
        extract_answer('data: {"type":"chunk","chunk":"draft"}\n\n', "text/event-stream")
    with pytest.raises(ValueError, match="without a successful answer"):
        extract_answer('data: {"type":"error","error":"failed"}\n\n', "text/event-stream")
    with pytest.raises(ValueError, match="malformed JSON"):
        extract_answer("data: {not-json}\n\n", "text/event-stream")


def test_contract_benchmark_rejects_mixed_or_malformed_schemas():
    legal_case = {
        "id": "legal",
        "question": "Question",
        "source": {},
        "expected_citations": ["Art. 1"],
        "must_contain_any": [["texto"]],
    }
    contract_case = {"id": "contract", "answer": "text", "sources": [], "expected_grounded": True}
    assert "mixes" in validate_cases([legal_case, contract_case])
    assert "string answer" in validate_cases(
        [{"answer": 42, "sources": [], "expected_grounded": True}]
    )
