from __future__ import annotations

import hashlib
from pathlib import Path

import fitz
import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands import stage_lc55_original_candidate_qa as staging
from src.apps.legislation.document_models import DocumentoNormativo


def _write_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "LEI COMPLEMENTAR Nº 055, DE 27 DE JANEIRO DE 2004")
    pdf.save(path)
    pdf.close()
    return path


def _qa_env(monkeypatch, qa_root: Path) -> None:
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


@pytest.mark.django_db
def test_lc55_original_dry_run_is_verified_and_does_not_write(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lc55-2004" / staging.EXPECTED_FILENAME)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_SHA256", digest)
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)
    before = DocumentoNormativo.objects.count()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_lc55_original_candidate(pdf_path=pdf_path)

    assert result["mode"] == "dry-run"
    assert result["identity_status"] == "candidate"
    assert result["edition_status"] == "original"
    assert result["document_role"] == "original"
    assert result["will_create_norma"] is False
    assert result["will_extract_text"] is False
    assert DocumentoNormativo.objects.count() == before


@pytest.mark.django_db
def test_lc55_original_apply_is_idempotent_and_stays_unlinked_pending(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lc55-2004" / staging.EXPECTED_FILENAME)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_SHA256", digest)
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = staging.stage_lc55_original_candidate(pdf_path=pdf_path, apply=True)
        second = staging.stage_lc55_original_candidate(pdf_path=pdf_path, apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["document_id"] == second["document_id"]
    assert document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
    assert document.role == DocumentoNormativo.Role.ORIGINAL
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.metadata_json["identity_candidate"]["number"] == "55"
    assert document.metadata_json["identity_candidate"]["year"] == 2004
    assert document.metadata_json["edition_candidate"]["kind"] == "original"
    stored = qa_root / "normative-archive" / document.storage_key
    assert stored.is_file()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == digest
    assert DocumentoNormativo.objects.filter(content_sha256=digest).count() == 1


def test_lc55_original_rejects_pdf_outside_exact_qa_evidence_directory(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    outside = _write_pdf(tmp_path / "outside" / staging.EXPECTED_FILENAME)
    monkeypatch.setattr(staging, "EXPECTED_SHA256", hashlib.sha256(outside.read_bytes()).hexdigest())
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diretório de evidências QA"):
            staging.stage_lc55_original_candidate(pdf_path=outside)


def test_lc55_original_rejects_hash_mismatch(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lc55-2004" / staging.EXPECTED_FILENAME)
    monkeypatch.setattr(staging, "EXPECTED_SHA256", "0" * 64)
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="SHA-256"):
            staging.stage_lc55_original_candidate(pdf_path=pdf_path)
