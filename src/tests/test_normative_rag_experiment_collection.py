import json
from pathlib import Path

import pytest

from scripts.collect_normative_rag_experiment import (
    _make_options,
    _probe_warm_cache,
    _read_cases,
    _retrieval_trace,
    _warm_cache_bypass_reason,
    validate_cases,
)
from src.processing.adaptive_retrieval import RetrievalOptions


def _case(**overrides):
    return {
        "case_id": "smoke-1",
        "query": "Pergunta jurídica de QA?",
        "expected_source_ids": [],
        "expected_citation_ids": [],
        "expected_versions": {},
        "expected_abstain": False,
        "relation_chain_keys": [],
        "human_evidence_review": False,
        "synthetic_qa_fixture": True,
        **overrides,
    }


def test_collector_enforces_case_limit_and_preserves_technical_only_status():
    cases = validate_cases([_case()])

    assert cases[0]["human_evidence_review"] is False
    with pytest.raises(ValueError, match="case count"):
        validate_cases([_case(case_id=f"case-{index}") for index in range(13)])
    with pytest.raises(ValueError, match="human-reviewed"):
        validate_cases([_case(human_evidence_review=True)])
    with pytest.raises(ValueError, match="synthetic QA fixtures"):
        validate_cases([_case(synthetic_qa_fixture=False)])


def test_versioned_live_smoke_set_contains_twelve_explicitly_synthetic_cases():
    case_path = (
        Path(__file__).resolve().parents[2]
        / "benchmarks"
        / "corpus"
        / "municipal_natal"
        / "rag-experiment-smoke.v1.jsonl"
    )
    rows = [json.loads(line) for line in case_path.read_text(encoding="utf-8").splitlines()]

    validated = validate_cases(rows)

    assert len(validated) == 12
    assert all(row["synthetic_qa_fixture"] is True for row in validated)
    assert all(row["human_evidence_review"] is False for row in validated)


def test_case_limit_selects_a_deterministic_prefix(tmp_path):
    case_path = tmp_path / "cases.jsonl"
    case_path.write_text(
        "\n".join(json.dumps(_case(case_id=f"case-{index}")) for index in range(1, 4)),
        encoding="utf-8",
    )

    selected = _read_cases(case_path, max_cases=1)

    assert [row["case_id"] for row in selected] == ["case-1"]


def test_collector_rejects_invalid_historical_scope():
    with pytest.raises(ValueError, match="ISO date"):
        validate_cases([_case(as_of="2012-13-40")])


def test_arm_cache_namespace_is_a_retrieval_options_subclass_and_distinguishes_arms():
    base = RetrievalOptions(mode="hybrid", source_scope="all", max_sources=12)
    baseline = _make_options(base, "run-1:case-1:baseline")
    graph = _make_options(base, "run-1:case-1:graph")

    assert isinstance(baseline, RetrievalOptions)
    assert baseline.fingerprint() != graph.fingerprint()
    assert baseline.fingerprint().startswith(base.fingerprint())


def test_retrieval_trace_records_graph_provenance_without_copying_evidence_text():
    trace = _retrieval_trace([
        {"retrieval_strategy": "hybrid", "citation_id": "source:1"},
        {
            "retrieval_strategy": "one_hop_reviewed_graph",
            "citation_id": "source:2",
            "graph_relation": {
                "event_id": "event:7:revision",
                "action": "ALTERA",
                "role": "target_device",
                "source_norma_id": 12,
                "target_norma_id": 9,
                "source_device_key": "source-key",
                "target_device_key": "target-key",
                "review_status": "approved",
                "effective_status": "confirmed",
                "effective_on": "2021-03-01",
                "resolution": "resolved",
                "quote": "texto legal que não deve ser exportado",
            },
        },
    ])

    assert trace["retrieval_strategies"] == ["hybrid", "one_hop_reviewed_graph"]
    assert trace["graph_evidence"] == [{
        "citation_id": "source:2",
        "event_id": "event:7:revision",
        "action": "ALTERA",
        "role": "target_device",
        "source_norma_id": 12,
        "target_norma_id": 9,
        "source_device_key": "source-key",
        "target_device_key": "target-key",
        "review_status": "approved",
        "effective_status": "confirmed",
        "effective_on": "2021-03-01",
        "resolution": "resolved",
    }]
    assert "quote" not in trace["graph_evidence"][0]


def test_warm_cache_probe_reports_every_arm_and_embedding_without_query_content():
    class CacheProbe:
        def __init__(self):
            self.answer_calls = []
            self.embedding_calls = []

        def get_answer(self, **kwargs):
            self.answer_calls.append(kwargs["retrieval_fingerprint"])
            return {"answer": "cached"} if kwargs["retrieval_fingerprint"] != "graph" else None

        def get_embedding(self, query, model):
            self.embedding_calls.append((query, model))
            return [0.1, 0.2]

    cache = CacheProbe()
    result = _probe_warm_cache(
        cache,
        kwargs_by_arm={
            "baseline": {"retrieval_fingerprint": "baseline"},
            "graph": {"retrieval_fingerprint": "graph"},
            "graph_temporal": {"retrieval_fingerprint": "graph-temporal"},
        },
        question="consulta sintética confidencial",
        embedding_model="embedding-qa",
    )

    assert result == {
        "answer_cache_hits_by_arm": {
            "baseline": True,
            "graph": False,
            "graph_temporal": True,
        },
        "query_embedding_cached": True,
        "eligible_arms": ["baseline", "graph_temporal"],
        "fully_paired": False,
    }
    assert len(cache.answer_calls) == 3
    assert cache.embedding_calls == [("consulta sintética confidencial", "embedding-qa")]
    assert "consulta sintética confidencial" not in json.dumps(result)


@pytest.mark.parametrize(
    ("case", "expected"),
    [
        ({"query": "O que prevê o art. 5º da Lei nº 9001/2020?"}, "explicit_normative_reference_bypasses_answer_cache"),
        ({"query": "Tema de meio ambiente?", "as_of": "2021-01-01"}, "temporal_retrieval_bypasses_answer_cache"),
        ({"query": "Que assunto é tratado nas normas municipais?"}, None),
    ],
)
def test_warm_repeat_selection_matches_production_cache_bypass_policy(case, expected):
    assert _warm_cache_bypass_reason(case) == expected
