import pytest

from scripts.run_normative_rag_experiment import analyze


def _rows():
    rows = []
    for arm in ("baseline", "graph", "graph_temporal"):
        for cache_state in ("cold", "warm"):
            rows.append({
                "case_id": "case-1", "arm": arm, "repeat": 0,
                "corpus_revision": "r7", "model": "local-test", "temperature": 0.1,
                "token_budget": 512, "hardware": "qa-fixture", "cache_state": cache_state,
                "expected_source_ids": ["source-1"], "retrieved_source_ids": ["source-1"],
                "expected_citation_ids": ["citation-1"], "cited_citation_ids": ["citation-1"],
                "expected_versions": {"source-1": "a" * 64}, "cited_versions": {"source-1": "a" * 64},
                "expected_abstain": False, "abstained": False,
                "ttft_ms": 120, "final_ms": 400, "human_evidence_review": False,
            })
    return rows


def test_paired_experiment_separates_cold_warm_and_marks_fixture_as_smoke():
    result = analyze(_rows())

    assert result["status"] == "technical_smoke_only"
    assert result["scientific_claim_allowed"] is False
    assert result["paired_groups"] == 2
    assert result["cache_policy"]["cold"]["graph"]["quality"]["version_exact_accuracy"] is None
    assert result["cache_policy"]["cold"]["graph"]["quality"]["reviewed_cases"] == 0


def test_only_human_reviewed_cases_contribute_quality_metrics():
    rows = _rows()
    for row in rows:
        row["human_evidence_review"] = True

    result = analyze(rows)

    assert result["status"] == "human_reviewed_experiment"
    assert result["cache_policy"]["cold"]["graph"]["quality"]["reviewed_cases"] == 1
    assert result["cache_policy"]["cold"]["graph"]["quality"]["version_exact_accuracy"] == 1.0


def test_experiment_rejects_changed_model_or_corpus_between_arms():
    rows = _rows()
    rows[-1]["model"] = "different-model"

    with pytest.raises(ValueError, match="fixed configuration"):
        analyze(rows)


def test_duplicate_arm_and_incomplete_pair_are_rejected():
    rows = _rows()
    with pytest.raises(ValueError, match="duplicate arm"):
        analyze(rows + [rows[0]])
    with pytest.raises(ValueError, match="incomplete paired arms"):
        analyze(rows[:-1])
