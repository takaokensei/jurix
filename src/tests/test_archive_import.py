from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import fitz
import pytest
from django.test import override_settings

from src.apps.ingestion.archive_import import ArchiveImportError, import_archive
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.operations.models import ArchiveImportRun
from src.processing.archive_inventory import inventory_archive


def _pdf_bytes(text: str) -> bytes:
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), text)
    payload = document.tobytes()
    document.close()
    return payload


def _inputs(tmp_path: Path, count: int = 2) -> tuple[Path, Path]:
    tmp_path.mkdir(parents=True, exist_ok=True)
    archive_path = tmp_path / "fixture.zip"
    with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for index in range(count):
            archive.writestr(f"Lei_{2020 + index:04}_000{index + 1}.pdf", _pdf_bytes(f"Lei número {index + 1}. Art. 1º Texto QA."))
    manifest = tmp_path / "manifest.jsonl"
    inventory_archive(archive_path, manifest)
    return archive_path, manifest


@pytest.mark.django_db(transaction=True)
def test_archive_import_dry_run_then_apply_is_staging_only(tmp_path, monkeypatch):
    archive, manifest = _inputs(tmp_path)
    qa_root = tmp_path / "isolated-root"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        dry = import_archive(archive_path=archive, manifest_path=manifest, apply=False)
        assert dry["mode"] == "dry-run" and dry["selected"] == 2
        assert DocumentoNormativo.objects.count() == 0
        result = import_archive(archive_path=archive, manifest_path=manifest, apply=True)
        assert result["created"] == 2
        assert result["extraction_created"] == 2
        assert DocumentoNormativo.objects.count() == 2
        assert ExtracaoDocumento.objects.count() == 2
        assert ArchiveImportRun.objects.get(pk=result["run_id"]).status == ArchiveImportRun.Status.COMPLETED
        for document in DocumentoNormativo.objects.select_related("norma", "accepted_extraction"):
            assert document.norma_id is None
            assert document.accepted_extraction_id is None
            assert document.condition_of_use == DocumentoNormativo.ConditionOfUse.UNKNOWN
            assert Path(qa_root, "normative-archive", document.storage_key).is_file()
            assert document.content_sha256 == hashlib.sha256(
                Path(qa_root, "normative-archive", document.storage_key).read_bytes()
            ).hexdigest()


@pytest.mark.django_db(transaction=True)
def test_archive_import_interruption_resumes_without_duplicate_documents(tmp_path, monkeypatch):
    archive, manifest = _inputs(tmp_path, count=3)
    qa_root = tmp_path / "isolated-root"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(RuntimeError, match="injected QA interruption"):
            import_archive(archive_path=archive, manifest_path=manifest, apply=True, limit=3, batch_size=1, fail_after=1)
        run = ArchiveImportRun.objects.get()
        assert run.status == ArchiveImportRun.Status.PAUSED
        assert DocumentoNormativo.objects.count() == 1
        result = import_archive(
            archive_path=archive, manifest_path=manifest, apply=True, limit=3,
            batch_size=1, resume=str(run.pk),
        )
        assert result["created"] == 2
        assert DocumentoNormativo.objects.count() == 3
        assert ExtracaoDocumento.objects.count() == 3


@pytest.mark.django_db(transaction=True)
def test_archive_import_resume_refuses_different_archive(tmp_path, monkeypatch):
    archive, manifest = _inputs(tmp_path, count=1)
    other_archive, other_manifest = _inputs(tmp_path / "other", count=1)
    qa_root = tmp_path / "isolated-root"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        run = import_archive(archive_path=archive, manifest_path=manifest, apply=True, limit=1)
        with pytest.raises(ArchiveImportError, match="manifesto ausente|checkpoint"):
            import_archive(archive_path=other_archive, manifest_path=other_manifest, apply=True, limit=1, resume=run["run_id"])


def test_archive_import_rejects_over_limit_and_missing_qa(monkeypatch, tmp_path):
    archive, manifest = _inputs(tmp_path, count=1)
    monkeypatch.setenv("JURIX_QA_ONLY", "0")
    with pytest.raises(ArchiveImportError, match="QA explícito"):
        import_archive(archive_path=archive, manifest_path=manifest, apply=True)
