import json

import pytest

from scripts.run_normative_rag_experiment import analyze, load_sampling_report


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
                "norma_key": "norma-1", "document_key": "document-1", "relation_chain_keys": ["chain-1"],
                "human_review": {"review_kind": "synthetic", "status": "pending"},
                "condition_of_use": "unknown", "sampling_report_sha256": None,
            })
    return rows


def _bind_sampling_report(rows, tmp_path):
    reviewed = [row for row in rows if row["human_review"]["review_kind"] == "human"]
    units = sorted({
        (row["norma_key"], row["document_key"], row["condition_of_use"])
        for row in reviewed
    })
    report = {
        "schema_version": 1,
        "created_at": "2026-10-08T12:00:00+00:00",
        "selection_method": "stratified_random",
        "seed": 42,
        "strata": {"act_type": {"lei_complementar": len(units)}},
        "units": [
            {"norma_key": norma, "document_key": document, "condition_of_use": condition}
            for norma, document, condition in units
        ],
        "relation_chain_keys": sorted({
            chain for row in reviewed for chain in row["relation_chain_keys"]
        }),
    }
    path = tmp_path / "sampling-report.json"
    path.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True), encoding="utf-8")
    verified = load_sampling_report(path)
    for row in rows:
        row["sampling_report_sha256"] = verified["sha256"]
    return verified


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
        row["human_review"] = {
            "review_kind": "human",
            "status": "approved",
            "reviewer_id": "reviewer-qa",
            "reviewed_at": "2026-10-08T12:00:00+00:00",
        }

    result = analyze(rows)

    assert result["status"] == "human_reviewed_experiment"
    assert result["cache_policy"]["cold"]["graph"]["quality"]["reviewed_cases"] == 1
    assert result["cache_policy"]["cold"]["graph"]["quality"]["version_exact_accuracy"] == 1.0
    assert result["scientific_claim_allowed"] is False
    assert result["human_review"]["distinct_normas"] == 1


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


def test_boolean_review_flag_does_not_admit_synthetic_rows_to_metrics():
    rows = _rows()
    for row in rows:
        row["human_evidence_review"] = True
    result = analyze(rows)

    assert result["status"] == "technical_smoke_only"
    assert result["cache_policy"]["cold"]["graph"]["quality"]["reviewed_cases"] == 0
    assert result["human_review"]["excluded_nonhuman_or_incomplete_rows"] == len(rows)


def test_paired_gold_annotations_must_be_identical_between_arms():
    rows = _rows()
    rows[0]["expected_citation_ids"] = ["different-gold"]

    with pytest.raises(ValueError, match="paired gold annotation differs"):
        analyze(rows)


def test_cluster_bootstrap_uses_norms_and_requires_twenty_independent_clusters(tmp_path):
    rows = []
    for index in range(20):
        for arm in ("baseline", "graph", "graph_temporal"):
            row = _rows()[0].copy()
            row.update(
                case_id=f"case-{index}",
                norma_key=f"norma-{index}",
                document_key=f"document-{index}",
                relation_chain_keys=[f"chain-{index % 3}"],
                arm=arm,
                cache_state="cold",
                human_review={
                    "review_kind": "human",
                    "status": "adjudicated",
                    "reviewer_id": "reviewer-qa",
                    "reviewed_at": "2026-10-08T12:00:00+00:00",
                },
                condition_of_use="public_record_reviewed",
                sampling_report_sha256="f" * 64,
                cited_citation_ids=["citation-1"] if arm != "baseline" else [],
            )
            rows.append(row)

    sampling_report = _bind_sampling_report(rows, tmp_path)
    result = analyze(rows, sampling_report=sampling_report)
    interval = result["paired_confidence_intervals"]["cold"]["graph_vs_baseline"]["citation_f1"]

    assert result["scientific_claim_allowed"] is True
    assert interval["cluster_unit"] == "norma_key"
    assert interval["n_norm_clusters"] == 20
    assert interval["status"] == "estimated_cluster_bootstrap"
    assert interval["ci_95"] == {"lower": 1.0, "upper": 1.0}


def test_row_hash_without_sampling_report_cannot_enable_scientific_claim():
    rows = []
    for index in range(20):
        for arm in ("baseline", "graph", "graph_temporal"):
            row = _rows()[0].copy()
            row.update(
                case_id=f"case-{index}", norma_key=f"norma-{index}",
                document_key=f"document-{index}", relation_chain_keys=[f"chain-{index % 3}"],
                arm=arm, cache_state="cold",
                human_review={
                    "review_kind": "human", "status": "approved",
                    "reviewer_id": "reviewer-qa", "reviewed_at": "2026-10-08T12:00:00+00:00",
                },
                condition_of_use="public_record_reviewed", sampling_report_sha256="f" * 64,
            )
            rows.append(row)

    result = analyze(rows)

    assert result["scientific_claim_allowed"] is False
    assert result["human_review"]["sampling_report_present"] is False


def test_sampling_report_hash_must_match_every_human_reviewed_row(tmp_path):
    rows = []
    for index in range(20):
        for arm in ("baseline", "graph", "graph_temporal"):
            row = _rows()[0].copy()
            row.update(
                case_id=f"case-{index}", norma_key=f"norma-{index}",
                document_key=f"document-{index}", relation_chain_keys=[f"chain-{index % 3}"],
                arm=arm, cache_state="cold",
                human_review={
                    "review_kind": "human", "status": "approved",
                    "reviewer_id": "reviewer-qa", "reviewed_at": "2026-10-08T12:00:00+00:00",
                },
                condition_of_use="licensed", sampling_report_sha256="f" * 64,
            )
            rows.append(row)
    sampling_report = _bind_sampling_report(rows, tmp_path)
    for row in rows:
        row["sampling_report_sha256"] = "e" * 64

    result = analyze(rows, sampling_report=sampling_report)

    assert result["human_review"]["sampling_report_present"] is False
    assert result["scientific_claim_allowed"] is False


def test_sampling_report_requires_timezone_aware_created_at(tmp_path):
    path = tmp_path / "invalid-report.json"
    path.write_text(json.dumps({
        "schema_version": 1,
        "created_at": "2026-10-08T12:00:00",
        "selection_method": "stratified_random",
        "seed": 1,
        "strata": {"type": 1},
        "units": [{"norma_key": "n1", "document_key": "d1", "condition_of_use": "licensed"}],
        "relation_chain_keys": [],
    }), encoding="utf-8")

    with pytest.raises(ValueError, match="timezone-aware"):
        load_sampling_report(path)
