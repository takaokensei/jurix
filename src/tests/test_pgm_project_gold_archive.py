from scripts.evaluate_pgm_project_gold_archive import (
    _qa_root,
    extracted_article_marker_coverage,
    score_retrieval,
    source_inventory,
)


def test_archive_gold_retrieval_scores_exact_pdf_and_article_identity():
    digest = "a" * 64
    query = {
        "case_id": "case-1",
        "expected_source_ids": [f"sha256:{digest}"],
        "expected_citation_ids": ["n01:art:1"],
        "gold_source_unit_map": {digest: "n01"},
    }
    sources = [
        {"document_sha256": digest, "dispositivo_ref": "Art. 1º"},
        {"document_sha256": "b" * 64, "dispositivo_ref": "Art. 2º"},
    ]

    result = score_retrieval([query], [sources], limit=2)

    assert result["source_recall_at_5"] == 1.0
    assert result["article_recall_at_5"] == 1.0
    assert result["queries_with_expected_article_at_limit"] == 1
    assert result["queries_without_expected_article_at_limit"] == []
    assert result["per_query"] == [
        {
            "case_id": "case-1",
            "expected_source_count": 1,
            "expected_citation_count": 1,
            "retrieved_record_count": 2,
            "source_hits_at_5": 1,
            "source_hits_at_limit": 1,
            "article_hits_at_5": 1,
            "article_hits_at_limit": 1,
            "missed_sources_at_5": [],
            "missed_sources_at_limit": [],
            "missed_citations_at_5": [],
            "missed_citations_at_limit": [],
        }
    ]
    assert result["scientific_claim_allowed"] is False


def test_archive_gold_retrieval_does_not_count_document_only_as_article_match():
    digest = "a" * 64
    query = {
        "case_id": "case-2",
        "expected_source_ids": [f"sha256:{digest}"],
        "expected_citation_ids": ["n01:art:9"],
        "gold_source_unit_map": {digest: "n01"},
    }

    result = score_retrieval(
        [query],
        [[{"document_sha256": digest, "dispositivo_ref": "Art. 1º"}]],
        limit=8,
    )

    assert result["source_recall_at_5"] == 1.0
    assert result["article_recall_at_5"] == 0.0
    assert result["queries_without_expected_article_at_limit"] == ["case-2"]
    assert result["per_query"][0]["missed_citations_at_limit"] == ["n01:art:9"]


def test_gold_source_inventory_distinguishes_absent_pending_and_accepted_sources():
    present_hash = "a" * 64
    absent_hash = "b" * 64
    inventory = source_inventory(
        {present_hash, absent_hash},
        [
            {
                "content_sha256": present_hash,
                "source_kind": "archive",
                "review_status": "pending",
                "accepted_extraction_id": None,
                "latest_extraction_status": "complete",
            },
            {
                "content_sha256": present_hash,
                "source_kind": "archive",
                "review_status": "pending",
                "accepted_extraction_id": None,
                "latest_extraction_status": "partial",
            },
        ],
    )

    assert inventory["expected_source_hash_count"] == 2
    assert inventory["exact_hash_present_count"] == 1
    assert inventory["exact_hash_absent_count"] == 1
    assert inventory["sources_with_accepted_extraction_count"] == 0
    assert inventory["items"][0]["latest_extraction_statuses"] == {
        "complete": 1,
        "partial": 1,
    }


def test_gold_article_marker_diagnostic_separates_extraction_from_retrieval():
    digest = "a" * 64
    coverage = extracted_article_marker_coverage(
        {digest: "n01"},
        {"n01:art:1", "n01:art:2.fragment", "n01:art:9"},
        [
            {
                "content_sha256": digest,
                "latest_extraction_status": "complete",
                "latest_legal_text": "Art. 1º Primeiro.\nArt. 2º Segundo.",
            }
        ],
    )

    assert coverage["expected_unit_article_count"] == 3
    assert coverage["unit_article_markers_present"] == 2
    assert coverage["unit_article_marker_recall"] == 2 / 3
    assert coverage["items"][0]["missing_article_markers"] == ["9"]


def test_archive_gold_evaluator_requires_explicit_qa_environment(monkeypatch, tmp_path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")
    monkeypatch.setenv("JURIX_QA_ROOT", str(tmp_path / "qa"))
    monkeypatch.setenv("TEMP", str(tmp_path))

    try:
        _qa_root()
    except ValueError as exc:
        assert "isolated normative QA" in str(exc)
    else:
        raise AssertionError("non-QA Django settings must be rejected")


def test_archive_gold_evaluator_rejects_qa_root_outside_system_temp(monkeypatch, tmp_path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(tmp_path / "outside"))
    monkeypatch.setenv("TEMP", str(tmp_path / "temp"))

    try:
        _qa_root()
    except ValueError as exc:
        assert "child of the system temporary directory" in str(exc)
    else:
        raise AssertionError("QA report path outside system temp must be rejected")
