from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands import stage_lp275_2009_candidate_qa as staging
from src.apps.legislation.document_models import DocumentoNormativo


def _write_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "LEI PROMULGADA Nº 0275/2009")
    page.insert_text((72, 100), "Dispõe sobre a regulamentação das calçadas no Município de Natal")
    page.insert_text(
        (72, 128),
        "Art. 21 - O rebaixamento de guias para os fins de garantir a acessibilidade é de responsabilidade do Executivo Municipal.",
    )
    pdf.save(path)
    pdf.close()
    return path


def _qa_env(monkeypatch, qa_root: Path) -> None:
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


@pytest.mark.django_db
def test_lp275_dry_run_verifies_identity_and_does_not_write(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lp275-2009" / staging.EXPECTED_FILENAME)
    monkeypatch.setattr(staging, "EXPECTED_SHA256", hashlib.sha256(pdf_path.read_bytes()).hexdigest())
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)
    before = DocumentoNormativo.objects.count()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_lp275_2009_candidate(pdf_path=pdf_path)

    assert result["mode"] == "dry-run"
    assert result["identity_candidate"]["type"] == "lei_promulgada"
    assert result["identity_candidate"]["number"] == "275"
    assert result["identity_candidate"]["year"] == 2009
    assert result["will_create_norma"] is False
    assert result["will_accept_text"] is False
    assert result["will_enter_rag"] is False
    assert DocumentoNormativo.objects.count() == before


@pytest.mark.django_db
def test_lp275_apply_is_idempotent_and_stays_pending_unlinked_and_out_of_rag(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lp275-2009" / staging.EXPECTED_FILENAME)
    digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest()
    monkeypatch.setattr(staging, "EXPECTED_SHA256", digest)
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = staging.stage_lp275_2009_candidate(pdf_path=pdf_path, apply=True)
        second = staging.stage_lp275_2009_candidate(pdf_path=pdf_path, apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["document_id"] == second["document_id"]
    assert document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.official_url == staging.SOURCE_URL
    assert document.metadata_json["identity_candidate"]["type"] == "lei_promulgada"
    assert document.metadata_json["identity_candidate"]["number"] == "275"
    assert document.metadata_json["identity_candidate"]["year"] == 2009
    assert document.metadata_json["rag_eligible"] is False
    stored = qa_root / "normative-archive" / document.storage_key
    assert stored.is_file()
    assert hashlib.sha256(stored.read_bytes()).hexdigest() == digest
    assert DocumentoNormativo.objects.filter(content_sha256=digest).count() == 1


def test_lp275_rejects_pdf_outside_exact_qa_evidence_directory(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    outside = _write_pdf(tmp_path / "outside" / staging.EXPECTED_FILENAME)
    monkeypatch.setattr(staging, "EXPECTED_SHA256", hashlib.sha256(outside.read_bytes()).hexdigest())
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diretório de evidências QA"):
            staging.stage_lp275_2009_candidate(pdf_path=outside)


def test_lp275_rejects_hash_mismatch(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lp275-2009" / staging.EXPECTED_FILENAME)
    monkeypatch.setattr(staging, "EXPECTED_SHA256", "0" * 64)
    monkeypatch.setattr(staging, "EXPECTED_PAGE_COUNT", 1)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="SHA-256"):
            staging.stage_lp275_2009_candidate(pdf_path=pdf_path)


def test_lp275_rejects_non_qa_settings(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lp275-2009" / staging.EXPECTED_FILENAME)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings")

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="somente no ambiente QA"):
            staging.stage_lp275_2009_candidate(pdf_path=pdf_path)
