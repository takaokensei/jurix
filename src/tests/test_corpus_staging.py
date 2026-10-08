from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import fitz
import pytest
from django.test import override_settings

from src.apps.ingestion.archive_import import ArchiveImportError
from src.apps.ingestion.corpus_staging import stage_normative_corpus
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.operations.models import ArchiveImportRun
from src.processing.archive_inventory import inventory_archive


def _pdf_bytes(text: str) -> bytes:
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), text)
    result = pdf.tobytes()
    pdf.close()
    return result


def _archive_inputs(qa_root: Path, count: int, *, duplicate_content: bool = False):
    qa_root.mkdir(parents=True, exist_ok=True)
    archive_path = qa_root / "source.zip"
    duplicate = _pdf_bytes("Documento repetido de QA.")
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(count):
            payload = duplicate if duplicate_content and index < 2 else _pdf_bytes(
                f"Documento QA {index + 1}."
            )
            archive.writestr(f"Lei_2020_{index + 1:04}.pdf", payload)
    manifest_path = qa_root / "inventory.jsonl"
    inventory_archive(archive_path, manifest_path)
    return archive_path, manifest_path


def _enable_isolated_qa(monkeypatch, qa_root: Path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    return override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True)


@pytest.mark.django_db(transaction=True)
def test_dry_run_counts_entire_archive_beyond_legacy_40_limit(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    archive_path, manifest_path = _archive_inputs(qa_root, 41)
    with _enable_isolated_qa(monkeypatch, qa_root):
        result = stage_normative_corpus(
            archive_path=archive_path,
            manifest_path=manifest_path,
            batch_size=3,
        )

    assert result["mode"] == "dry-run"
    assert result["total_pdfs"] == 41
    assert result["selected"] == 3
    assert result["remaining_after_batch"] == 38
    assert result["will_create_norma"] is False
    assert result["will_extract_text"] is False
    assert DocumentoNormativo.objects.count() == 0
    assert ArchiveImportRun.objects.count() == 0


@pytest.mark.django_db(transaction=True)
def test_staging_resumes_in_batches_without_extraction_or_norma_promotion(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    archive_path, manifest_path = _archive_inputs(qa_root, 5)
    qa_settings = _enable_isolated_qa(monkeypatch, qa_root)
    with qa_settings:
        first = stage_normative_corpus(
            archive_path=archive_path, manifest_path=manifest_path, apply=True, batch_size=2
        )
        assert first["corpus_status"] == "partial"
        assert first["created"] == 2
        assert first["remaining"] == 3

        second = stage_normative_corpus(
            archive_path=archive_path,
            manifest_path=manifest_path,
            apply=True,
            batch_size=2,
            resume=first["run_id"],
        )
        third = stage_normative_corpus(
            archive_path=archive_path,
            manifest_path=manifest_path,
            apply=True,
            batch_size=2,
            resume=first["run_id"],
        )
        repeated = stage_normative_corpus(
            archive_path=archive_path,
            manifest_path=manifest_path,
            apply=True,
            batch_size=2,
            resume=first["run_id"],
        )

    assert second["corpus_status"] == "partial"
    assert third["corpus_status"] == "complete"
    assert third["total_pdfs"] == 5
    assert third["remaining"] == 0
    assert repeated["mode"] == "complete"
    assert repeated["reason"] == "corpus_complete"
    assert repeated["created"] == 5
    assert repeated["failed"] == 0
    assert DocumentoNormativo.objects.count() == 5
    assert ExtracaoDocumento.objects.count() == 0
    assert ArchiveImportRun.objects.count() == 1
    run = ArchiveImportRun.objects.get(pk=first["run_id"])
    assert run.import_limit == 5
    assert run.stats_json["corpus_status"] == "complete"
    assert len(run.stats_json["completed"]) == 5
    for document in DocumentoNormativo.objects.select_related("norma", "accepted_extraction"):
        assert document.norma_id is None
        assert document.accepted_extraction_id is None
        blob = qa_root / "normative-archive" / document.storage_key
        assert hashlib.sha256(blob.read_bytes()).hexdigest() == document.content_sha256


@pytest.mark.django_db(transaction=True)
def test_staging_deduplicates_content_blob_but_preserves_each_archive_entry(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    archive_path, manifest_path = _archive_inputs(qa_root, 3, duplicate_content=True)
    with _enable_isolated_qa(monkeypatch, qa_root):
        result = stage_normative_corpus(
            archive_path=archive_path,
            manifest_path=manifest_path,
            apply=True,
            batch_size=3,
        )

    assert result["corpus_status"] == "complete"
    assert DocumentoNormativo.objects.count() == 3
    assert DocumentoNormativo.objects.values("content_sha256").distinct().count() == 2
    assert result["copied"] == 2


def test_staging_rejects_extractor_injection_and_oversized_batch(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    archive_path, manifest_path = _archive_inputs(qa_root, 1)
    with _enable_isolated_qa(monkeypatch, qa_root):
        with pytest.raises(ArchiveImportError, match="não executa OCR"):
            stage_normative_corpus(
                archive_path=archive_path,
                manifest_path=manifest_path,
                extractor=lambda *_args, **_kwargs: {},
            )
        with pytest.raises(ArchiveImportError, match="batch_size"):
            stage_normative_corpus(
                archive_path=archive_path,
                manifest_path=manifest_path,
                batch_size=21,
            )


def test_staging_refuses_manifest_outside_qa_root(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    archive_path, manifest_path = _archive_inputs(tmp_path / "source", 1)
    with _enable_isolated_qa(monkeypatch, qa_root):
        with pytest.raises(ArchiveImportError, match="manifesto deve permanecer"):
            stage_normative_corpus(archive_path=archive_path, manifest_path=manifest_path)
