from __future__ import annotations

from pathlib import Path

import pymupdf
import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands.stage_lc271_ctm_amendment_qa import (
    EXPECTED_FILENAME,
    stage_lc271_candidate,
)
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma


def _pdf(path: Path, *, final_line="Publicada no Diário Oficial do Município em: 17/12/2025"):
    path.parent.mkdir(parents=True, exist_ok=True)
    document = pymupdf.open()
    first = document.new_page()
    first.insert_text(
        (72, 72),
        "LEI COMPLEMENTAR Nº 271, de 16 de dezembro de 2025\n"
        "Acrescenta e altera dispositivos da Lei nº 3.882, de 11/12/1989, "
        "da Lei Complementar nº 141, de 28/08/2014.",
    )
    for _ in range(5):
        document.new_page()
    last = document.new_page()
    last.insert_text((72, 72), final_line)
    document.save(path)
    document.close()
    return path


def _qa(monkeypatch, qa_root):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))


@pytest.mark.django_db
def test_lc271_dry_run_preserves_publication_date_conflict_and_writes_nothing(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    path = _pdf(qa_root / "evidence" / "lc-271-2025" / EXPECTED_FILENAME)
    _qa(monkeypatch, qa_root)
    before_documents = DocumentoNormativo.objects.count()
    before_normas = Norma.objects.count()

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = stage_lc271_candidate(pdf_path=path)

    assert result["mode"] == "dry-run"
    assert result["page_count"] == 7
    assert result["edition_candidate"]["publication_date_status"] == "source_conflict_requires_review"
    assert result["edition_candidate"]["sapl_record_publication_date"] == "2025-12-16"
    assert result["edition_candidate"]["pdf_colophon_publication_date"] == "2025-12-17"
    assert result["will_create_norma"] is False
    assert result["will_enter_rag"] is False
    assert DocumentoNormativo.objects.count() == before_documents
    assert Norma.objects.count() == before_normas


def test_lc271_rejects_wrong_colophon_date(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    path = _pdf(
        qa_root / "evidence" / "lc-271-2025" / EXPECTED_FILENAME,
        final_line="Publicada no Diário Oficial do Município em: 16/12/2025",
    )
    _qa(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="publicação em 17/12/2025"):
            stage_lc271_candidate(pdf_path=path)


def test_lc271_rejects_pdf_outside_exact_qa_evidence_directory(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    path = _pdf(tmp_path / "outside" / EXPECTED_FILENAME)
    _qa(monkeypatch, qa_root)

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(ValueError, match="diretório de evidências QA"):
            stage_lc271_candidate(pdf_path=path)
