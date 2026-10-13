from __future__ import annotations

from pathlib import Path

import fitz
import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands.stage_lc55_official_candidate_qa import (
    EXPECTED_FILENAME,
    stage_lc55_official_candidate,
)
from src.apps.legislation.document_models import DocumentoNormativo


def _write_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((72, 72), "LEI COMPLEMENTAR Nº 055, DE 27 DE JANEIRO DE 2004")
    pdf.save(path)
    pdf.close()
    return path


def _qa_env(monkeypatch, qa_root: Path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


@pytest.mark.django_db
def test_official_lc55_candidate_dry_run_has_provenance_and_does_not_write(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lc55-2004" / EXPECTED_FILENAME)
    _qa_env(monkeypatch, qa_root)
    before = DocumentoNormativo.objects.count()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = stage_lc55_official_candidate(pdf_path=pdf_path)

    assert result["mode"] == "dry-run"
    assert result["identity_status"] == "candidate"
    assert result["edition_status"] == "consolidated_copy"
    assert result["edition_date"] == "2019-07"
    assert result["will_create_norma"] is False
    assert result["will_extract_text"] is False
    assert DocumentoNormativo.objects.count() == before


@pytest.mark.django_db
def test_official_lc55_candidate_apply_is_idempotent_and_remains_pending(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(qa_root / "evidence" / "lc55-2004" / EXPECTED_FILENAME)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = stage_lc55_official_candidate(pdf_path=pdf_path, apply=True)
        second = stage_lc55_official_candidate(pdf_path=pdf_path, apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["document_id"] == second["document_id"]
    assert document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
    assert document.source_ref.startswith("municipal_repository:")
    assert document.official_url.startswith("https://natal.rn.gov.br/")
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.condition_of_use == DocumentoNormativo.ConditionOfUse.UNKNOWN
    assert document.role == DocumentoNormativo.Role.UNDETERMINED
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.metadata_json["identity_candidate"]["number"] == "55"
    assert document.metadata_json["identity_candidate"]["year"] == 2004
    assert document.metadata_json["edition_candidate"] == {
        "kind": "consolidated_copy",
        "as_of": "2019-07",
        "date_basis": ["official repository filename"],
        "review_status": "unreviewed",
    }
    stored = qa_root / "normative-archive" / document.storage_key
    assert stored.is_file()
    assert stored.read_bytes() == pdf_path.read_bytes()
    assert DocumentoNormativo.objects.filter(content_sha256=first["content_sha256"]).count() == 1


def test_official_lc55_candidate_rejects_path_outside_qa_evidence(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    outside = _write_pdf(tmp_path / "outside" / EXPECTED_FILENAME)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diretório de evidências QA"):
            stage_lc55_official_candidate(pdf_path=outside)
