from __future__ import annotations

import hashlib
from pathlib import Path

import pymupdf
import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands import stage_bvn_4566_1992_candidate_qa as staging
from src.apps.legislation.document_models import DocumentoNormativo


def _write_verified_shape_pdf(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open()
    first = pdf.new_page()
    first.insert_text(
        (72, 72),
        "LEI Nº 4.566, DE 19 DE MAIO DE 1992.\n"
        "A PREFEITA MUNICIPAL DO NATAL\nDECRETA:\n"
        "Art. 1o – Hotel-Residência.\n"
        "Art. 2o – Para efeito do presente Decreto.\n"
        "Art. 3o – Serviços.\nArt. 4o – Áreas.\nArt. 5o – Dimensões.\n"
        "Art. 6o – Plano Diretor.\n"
        "Art. 7o – Este decreto entra em vigor.\n"
        "Publicada no DOE de 21/05/92.",
    )
    pdf.new_page()
    pdf.save(path)
    pdf.close()
    return path


def _qa_env(monkeypatch, qa_root: Path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


@pytest.mark.django_db
def test_bvn_4566_dry_run_detects_conflict_and_does_not_write(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_verified_shape_pdf(
        qa_root / staging.EVIDENCE_RELATIVE_DIRECTORY / staging.EXPECTED_FILENAME
    )
    monkeypatch.setattr(staging, "EXPECTED_SHA256", hashlib.sha256(pdf_path.read_bytes()).hexdigest())
    _qa_env(monkeypatch, qa_root)
    before = DocumentoNormativo.objects.count()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_bvn_4566_candidate(pdf_path=pdf_path)

    assert result["mode"] == "dry-run"
    assert result["identity_status"] == "conflicting_evidence"
    assert result["identity_conflict"]["pdf_body"].startswith("PDF says DECRETA")
    assert result["will_create_norma"] is False
    assert result["will_accept_text"] is False
    assert result["will_enter_rag"] is False
    assert DocumentoNormativo.objects.count() == before


@pytest.mark.django_db
def test_bvn_4566_apply_is_idempotent_pending_and_never_rag_eligible(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    pdf_path = _write_verified_shape_pdf(
        qa_root / staging.EVIDENCE_RELATIVE_DIRECTORY / staging.EXPECTED_FILENAME
    )
    monkeypatch.setattr(staging, "EXPECTED_SHA256", hashlib.sha256(pdf_path.read_bytes()).hexdigest())
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = staging.stage_bvn_4566_candidate(pdf_path=pdf_path, apply=True)
        second = staging.stage_bvn_4566_candidate(pdf_path=pdf_path, apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["document_id"] == second["document_id"]
    assert document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.role == DocumentoNormativo.Role.UNDETERMINED
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.metadata_json["identity_status"] == "conflicting_evidence"
    assert document.metadata_json["rag_eligible"] is False
    stored = qa_root / "normative-archive" / document.storage_key
    assert stored.read_bytes() == pdf_path.read_bytes()


def test_bvn_4566_staging_rejects_path_outside_exact_evidence_root(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    outside = _write_verified_shape_pdf(tmp_path / "outside" / staging.EXPECTED_FILENAME)
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diretório QA exato"):
            staging.stage_bvn_4566_candidate(pdf_path=outside)
