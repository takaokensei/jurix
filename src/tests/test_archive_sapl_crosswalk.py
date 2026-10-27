from src.apps.ingestion.management.commands.audit_archive_sapl_crosswalk_qa import Command
from src.processing.archive_sapl_crosswalk import (
    archive_identity_candidate,
    rank_archive_candidates_by_publication,
    rank_archive_candidates_for_qa_extraction,
    summarize_crosswalk,
)


def test_archive_identity_requires_one_year_and_keeps_filename_date_as_candidate():
    assert archive_identity_candidate("Lei_8206_2026_original.pdf") == (
        "lei",
        "8206",
        2026,
    )
    assert archive_identity_candidate("Lei_20260821_8206.pdf") == (
        "lei",
        "8206",
        2026,
    )
    assert archive_identity_candidate("Lei_no_8.206_2026_original.pdf") == (
        "lei",
        "8206",
        2026,
    )
    assert archive_identity_candidate("Lei_8206.pdf") is None
    assert archive_identity_candidate("Lei_20260821_8206_2025.pdf") is None


def test_crosswalk_counts_only_one_to_one_type_number_year_matches():
    report = summarize_crosswalk(
        [
            "Lei_8206_2026_original.pdf",
            "LeiComplementar_55_2004.pdf",
            "Decreto_77_2020_original.pdf",
            "Decreto_77_2020_copia.pdf",
            "Lei_88_2025.pdf",
        ],
        [
            {"id": 1, "tipo": 1, "numero": "8.206", "ano": 2026, "data_publicacao": "2026-08-21"},
            {"id": 2, "tipo": 2, "numero": "55", "ano": 2004, "data_publicacao": None},
            {"id": 3, "tipo": 2, "numero": "55", "ano": 2004, "data_publicacao": "2004-01-27"},
            {"id": 4, "tipo": 3, "numero": "77", "ano": 2020, "data_publicacao": "2020-01-01"},
        ],
        {1: "Lei Ordinária", 2: "Lei Complementar", 3: "Decreto"},
    )
    assert report["strict_unique_document_to_catalog_matches"] == 1
    assert report["unique_matches_with_sapl_publication_date"] == 1
    assert report["ambiguous_archive_identity_groups"] == 1
    assert report["ambiguous_catalog_identity_groups"] == 1
    assert report["unmatched_archive_identity_groups"] == 1
    assert report["filename_dates_are_publication_facts"] is False
    assert report["matches_are_reviewed_legal_identities"] is False


def test_catalog_checkpoint_is_atomically_serializable(tmp_path):
    checkpoint_path = tmp_path / "sapl-crosswalk.json"
    checkpoint = {"schema_version": 1, "records": [], "offset": 0}

    Command._save_checkpoint(checkpoint_path, checkpoint)

    assert checkpoint_path.exists()
    assert checkpoint_path.read_text(encoding="utf-8") == (
        '{"offset": 0, "records": [], "schema_version": 1}'
    )
    assert list(tmp_path.iterdir()) == [checkpoint_path]


def test_publication_order_uses_sapl_date_then_act_year_and_number_and_skips_ambiguity():
    archives = [
        {"document_id": 1, "public_id": "a", "filename": "Lei_2_2025.pdf", "storage_key": "a.pdf", "content_sha256": "a" * 64, "size_bytes": 10},
        {"document_id": 2, "public_id": "b", "filename": "Lei_3_2025.pdf", "storage_key": "b.pdf", "content_sha256": "b" * 64, "size_bytes": 20},
        {"document_id": 3, "public_id": "c", "filename": "Lei_4_2024.pdf", "storage_key": "c.pdf", "content_sha256": "c" * 64, "size_bytes": 30},
        {"document_id": 4, "public_id": "d", "filename": "Lei_5_2024_original.pdf", "storage_key": "d.pdf", "content_sha256": "d" * 64, "size_bytes": 40},
        {"document_id": 5, "public_id": "e", "filename": "Lei_5_2024_copia.pdf", "storage_key": "e.pdf", "content_sha256": "e" * 64, "size_bytes": 50},
    ]
    catalog = [
        {"id": 1, "tipo": 1, "numero": "2", "ano": 2025, "data_publicacao": "2025-02-01"},
        {"id": 2, "tipo": 1, "numero": "3", "ano": 2025, "data_publicacao": None},
        {"id": 3, "tipo": 1, "numero": "4", "ano": 2024, "data_publicacao": "2024-12-20"},
        {"id": 4, "tipo": 1, "numero": "5", "ano": 2024, "data_publicacao": "2024-11-01"},
    ]

    result = rank_archive_candidates_by_publication(archives, catalog, {1: "Lei Ordinária"})

    assert [item["public_id"] for item in result] == ["a", "b", "c"]
    assert [item["publication_date"] for item in result] == [
        "2025-02-01",
        None,
        "2024-12-20",
    ]


def test_qa_extraction_order_covers_unmatched_and_ambiguous_pdfs_without_linking_them():
    archives = [
        {"document_id": 1, "public_id": "strict", "filename": "Lei_10_2026.pdf", "storage_key": "1.pdf", "content_sha256": "a" * 64, "size_bytes": 10},
        {"document_id": 2, "public_id": "fallback", "filename": "Lei_11_2025.pdf", "storage_key": "2.pdf", "content_sha256": "b" * 64, "size_bytes": 20},
        {"document_id": 3, "public_id": "duplicate-a", "filename": "Lei_12_2024_original.pdf", "storage_key": "3.pdf", "content_sha256": "c" * 64, "size_bytes": 30},
        {"document_id": 4, "public_id": "duplicate-b", "filename": "Lei_12_2024_copia.pdf", "storage_key": "4.pdf", "content_sha256": "d" * 64, "size_bytes": 40},
        {"document_id": 5, "public_id": "unresolved", "filename": "scan_legislacao.pdf", "storage_key": "5.pdf", "content_sha256": "e" * 64, "size_bytes": 50},
    ]
    catalog = [
        {"id": 1, "tipo": 1, "numero": "10", "ano": 2026, "data_publicacao": "2026-02-03"},
        {"id": 2, "tipo": 1, "numero": "12", "ano": 2024, "data_publicacao": "2024-05-01"},
    ]

    result = rank_archive_candidates_for_qa_extraction(archives, catalog, {1: "Lei Ordinária"})

    assert [item["public_id"] for item in result] == [
        "strict", "fallback", "duplicate-b", "duplicate-a", "unresolved",
    ]
    assert [item["priority_basis"] for item in result] == [
        "sapl_publication_date_candidate",
        "filename_year_number_fallback",
        "filename_year_number_fallback",
        "filename_year_number_fallback",
        "unresolved_stable_public_id",
    ]
    assert result[0]["publication_date_candidate"] == "2026-02-03"
    assert all(item["publication_date_candidate"] is None for item in result[1:])
    assert all(item["act_year_candidate"] is None for item in result[-1:])
