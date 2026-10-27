from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands.stage_ctm_3882_consolidation_qa import (
    EDITIONS,
    stage_ctm_consolidation,
)
from src.apps.legislation.document_models import DocumentoNormativo


def _write_pdf(path: Path, *, year: int = 2022, marker: str | None = None, text: str | None = None) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pymupdf.open()
    page = pdf.new_page()
    page.insert_text(
        (72, 72),
        text
        or (
            "LEI Nº 3.882, DE 11 DE DEZEMBRO DE 1989.\n"
            f"Valores atualizados para o exercício de {year}.\n"
            f"Alterada pela {marker or ('Lei Complementar nº 197, publicada no DOM de 18/06/2021' if year == 2021 else 'Lei Complementar nº 217, publicada no DOM de 02/09/2022' if year == 2022 else 'Lei Complementar nº 257/2024')}."
        ),
    )
    pdf.save(path)
    pdf.close()
    return path


def _qa_env(monkeypatch, qa_root: Path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


@pytest.mark.django_db
def test_ctm_consolidation_dry_run_is_explicitly_historical_and_does_not_write(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(
        qa_root / "evidence" / "ctm-3882-1989" / "lei3882-1989-consolidado-exercicio-2022.pdf"
    )
    _qa_env(monkeypatch, qa_root)
    before = DocumentoNormativo.objects.count()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = stage_ctm_consolidation(pdf_path=pdf_path)

    assert result["mode"] == "dry-run"
    assert result["identity_status"] == "candidate"
    assert result["edition_kind"] == "official_consolidated_text"
    assert result["declared_value_year"] == 2022
    assert result["will_create_norma"] is False
    assert result["will_extract_text"] is False
    assert result["will_accept_text"] is False
    assert result["will_enter_rag"] is False
    assert DocumentoNormativo.objects.count() == before


@pytest.mark.django_db
def test_ctm_consolidation_apply_is_idempotent_pending_and_not_rag_eligible(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(
        qa_root / "evidence" / "ctm-3882-1989" / "lei3882-1989-consolidado-exercicio-2022.pdf"
    )
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = stage_ctm_consolidation(pdf_path=pdf_path, apply=True)
        second = stage_ctm_consolidation(pdf_path=pdf_path, apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    assert first["created"] is True
    assert second["created"] is False
    assert first["document_id"] == second["document_id"]
    assert document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
    assert document.source_ref.startswith("municipal_consolidation:")
    assert document.official_url == (
        "https://www.natal.rn.gov.br/sefin/legislacao/lei/LEI3882-1989_2022.pdf"
    )
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.role == DocumentoNormativo.Role.UNDETERMINED
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.metadata_json["identity_candidate"]["number"] == "3882"
    assert document.metadata_json["identity_candidate"]["year"] == 1989
    assert document.metadata_json["edition_candidate"] == {
        "kind": "official_consolidated_text",
        "declared_value_year": 2022,
        "amendment_list_includes": "Lei Complementar nº 217, publicada no DOM de 02/09/2022",
        "temporal_limit": "Não declara atualização posterior ao exercício de 2022",
        "review_status": "unreviewed",
    }
    assert document.metadata_json["rag_eligible"] is False
    stored = qa_root / "normative-archive" / document.storage_key
    assert stored.read_bytes() == pdf_path.read_bytes()


def test_ctm_2022_marker_requires_the_publication_date_printed_in_official_pdf(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(
        qa_root / "evidence" / "ctm-3882-1989" / "lei3882-1989-consolidado-exercicio-2022.pdf",
        marker="Lei Complementar nº 217, publicada no DOM de 03/09/2022",
    )
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="confirma o marco de alteração declarado"):
            stage_ctm_consolidation(pdf_path=pdf_path)


def test_ctm_consolidation_rejects_pdf_without_declared_identity_or_year(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    pdf_path = _write_pdf(
        qa_root
        / "evidence"
        / "ctm-3882-1989"
        / "lei3882-1989-consolidado-exercicio-2022.pdf",
        text="LEI Nº 3.882, DE 11 DE DEZEMBRO DE 1989.\nValores atualizados para 2021.",
    )
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="confirma a edição do exercício de 2022"):
            stage_ctm_consolidation(pdf_path=pdf_path)


def test_ctm_consolidation_rejects_pdf_outside_qa_evidence(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    outside = _write_pdf(tmp_path / "outside" / "lei3882-1989-consolidado-exercicio-2022.pdf")
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diretório de evidências QA"):
            stage_ctm_consolidation(pdf_path=outside)


@pytest.mark.django_db
def test_ctm_2024_edition_is_staged_with_an_explicit_temporal_limit(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    filename = "lei3882-1989-consolidado-exercicio-2024.pdf"
    pdf_path = _write_pdf(
        qa_root / "evidence" / "ctm-3882-1989" / filename,
        year=2024,
        marker="Lei Complementar nº 257, publicada no DOM em 27/12/2024",
    )
    _qa_env(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = stage_ctm_consolidation(pdf_path=pdf_path)

    assert result["source_url"] == EDITIONS[filename]["source_url"]
    assert result["declared_value_year"] == 2024
    assert result["amendment_list_includes"] == (
        "Lei Complementar nº 257 (publicação listada em 27/12/2024)"
    )
    assert "não comprova alterações posteriores" in result["temporal_limit"]
    assert result["will_enter_rag"] is False
    assert DocumentoNormativo.objects.count() == 0


@pytest.mark.django_db
def test_ctm_2021_edition_is_staged_as_a_historical_baseline_only(tmp_path, monkeypatch):
    filename = "lei3882-1989-consolidado-exercicio-2021.pdf"
    pdf_path = _write_pdf( tmp_path / "qa" / "evidence" / "ctm-3882-1989" / filename, year=2021)
    _qa_env(monkeypatch, tmp_path / "qa")

    with override_settings(QA_ROOT=tmp_path / "qa", NORMATIVE_ARCHIVE_ENABLED=True):
        result = stage_ctm_consolidation(pdf_path=pdf_path)

    assert result["source_url"] == EDITIONS[filename]["source_url"]
    assert result["declared_value_year"] == 2021
    assert result["edition_kind"] == "official_consolidated_text"
    assert "não comprova alterações posteriores" in result["temporal_limit"]
    assert result["will_create_norma"] is False
    assert result["will_accept_text"] is False
    assert result["will_enter_rag"] is False
    assert DocumentoNormativo.objects.count() == 0
