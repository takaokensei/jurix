import hashlib
import json
import zipfile

from src.apps.ingestion.management.commands.inspect_archive_extraction_coverage_qa import (
    _incomplete_reason,
    _incomplete_storage_coverage,
    _inventory_content_hashes,
    _ocr_budget_workload,
)
from src.apps.ingestion.management.commands.restore_missing_archive_blobs_qa import (
    _entry_sha256,
)
from src.processing.archive_inventory import sha256_file


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


def test_incomplete_storage_coverage_reports_only_integrity_counts(tmp_path):
    content = b"verified local QA PDF bytes"
    digest = hashlib.sha256(content).hexdigest()
    blob = tmp_path / "normative-archive" / "sha256" / "sample.pdf"
    blob.parent.mkdir(parents=True)
    blob.write_bytes(content)

    result = _incomplete_storage_coverage(
        [("sha256/sample.pdf", digest), ("sha256/missing.pdf", "f" * 64)],
        tmp_path,
        {digest},
    )

    assert result == {
        "documents": 2,
        "hashes_in_archive_inventory": 1,
        "hashes_absent_from_archive_inventory": 1,
        "storage_hash_verified": 1,
        "storage_missing_or_unsafe": 1,
    }
    assert "sample.pdf" not in str(result)
    assert sha256_file(blob) == digest


def test_inventory_hash_reader_ignores_unhashed_and_non_pdf_entries(tmp_path):
    inventory = tmp_path / "archive-inventory-test.jsonl"
    valid_hash = "a" * 64
    inventory.write_text(
        "\n".join(
            json.dumps(row)
            for row in (
                {
                    "record_type": "entry",
                    "extension": ".pdf",
                    "hash_status": "hashed",
                    "content_sha256": valid_hash,
                },
                {
                    "record_type": "entry",
                    "extension": ".pdf",
                    "hash_status": "failed",
                    "content_sha256": "b" * 64,
                },
                {
                    "record_type": "entry",
                    "extension": ".txt",
                    "hash_status": "hashed",
                    "content_sha256": "c" * 64,
                },
            )
        ),
        encoding="utf-8",
    )

    assert _inventory_content_hashes(tmp_path) == {valid_hash}


def test_archive_blob_restore_verifies_zip_index_name_and_hash(tmp_path):
    data = b"authentic QA PDF payload"
    archive_path = tmp_path / "archive.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("pdfs/law.pdf", data)
    row = {
        "entry_index": 0,
        "entry_name": "pdfs/law.pdf",
        "content_sha256": hashlib.sha256(data).hexdigest(),
        "uncompressed_bytes": len(data),
    }

    with zipfile.ZipFile(archive_path) as archive:
        assert _entry_sha256(archive, row) == row["content_sha256"]
        try:
            _entry_sha256(archive, {**row, "entry_name": "../unsafe.pdf"})
        except ValueError as error:
            assert "não corresponde" in str(error)
        else:
            raise AssertionError("mismatched ZIP name must be rejected")
