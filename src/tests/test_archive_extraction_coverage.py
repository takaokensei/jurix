from src.apps.ingestion.management.commands.inspect_archive_extraction_coverage_qa import (
    _incomplete_reason,
    _ocr_budget_workload,
)


def test_incomplete_extraction_reason_prefers_explicit_ocr_budget_metadata():
    assert _incomplete_reason(
        "partial",
        {
            "ocr_budget_skipped_pages": [8, 9],
            "unreadable_pages": [8, 9],
        },
        12,
    ) == "ocr_page_budget_exceeded"


def test_incomplete_extraction_reason_uses_only_safe_technical_categories():
    assert _incomplete_reason("unreadable", {"extraction_error": "FileDataError"}, 0) == (
        "pdf_or_extractor_error"
    )
    assert _incomplete_reason(
        "partial", {"page_methods": {"unreadable": 2}}, 8
    ) == "unreadable_page_or_ocr_failure"
    assert _incomplete_reason("unreadable", {}, 0) == "empty_or_unreadable_pdf"
    assert _incomplete_reason("partial", {"needs_review": True}, 4) == (
        "other_partial_extraction"
    )
    assert _incomplete_reason("unknown", {"page_methods": {"unreadable": "bad"}}, 3) == (
        "unclassified_incomplete"
    )


def test_ocr_budget_workload_reports_aggregate_buckets_and_percentiles_only():
    assert _ocr_budget_workload([1, 10, 11, 25, 26, 50, 51, 100]) == {
        "documents_with_ocr_backlog": 8,
        "skipped_pages_total": 274,
        "per_document_min": 1,
        "per_document_median": 25.5,
        "per_document_p90": 100,
        "per_document_max": 100,
        "document_buckets": {"1_10": 2, "11_25": 2, "26_50": 2, "51_plus": 2},
    }


def test_ocr_budget_workload_empty_result_has_no_fake_percentiles():
    result = _ocr_budget_workload([0, -1])
    assert result["documents_with_ocr_backlog"] == 0
    assert result["skipped_pages_total"] == 0
    assert result["per_document_median"] is None
    assert result["per_document_p90"] is None
