from __future__ import annotations

import hashlib
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest
from django.test import override_settings

from src.apps.ingestion.management.commands import stage_lc208_unlinked_sapl_candidate_qa as staging
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma

PDF_BYTES = b"%PDF-1.7\nLC 208 official QA source\n%%EOF\n"
IDENTITY_KEY = "BR-RN-NATAL|lei_complementar|municipal_lc|208|2022"
PDF_URL = (
    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2022/1160/"
    "pdn_-_lc_208_2022.pdf"
)
LC261_PDF_BYTES = b"%PDF-1.7\nLC 261 official QA source\n%%EOF\n"
LC261_IDENTITY_KEY = "BR-RN-NATAL|lei_complementar|municipal_lc|261|2025"
LC261_PDF_URL = (
    "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2025/8823/"
    "lei_complementar_no_261_2025.pdf"
)


class FakeSaplClient:
    def __init__(self, content=PDF_BYTES):
        self.content = content

    def fingerprint_pdf(self, _url):
        return "sha256:" + hashlib.sha256(self.content).hexdigest()

    def download_pdf_version(self, _url, destination: Path):
        destination.write_bytes(self.content)
        return {
            "content_sha256": hashlib.sha256(self.content).hexdigest(),
            "size_bytes": len(self.content),
            "etag": None,
            "last_modified": None,
        }

    def close(self):
        return None


def _qa_environment(monkeypatch, qa_root, *, sapl_id=1160):
    qa_root.mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    content = PDF_BYTES if sapl_id == 1160 else LC261_PDF_BYTES
    url = PDF_URL if sapl_id == 1160 else LC261_PDF_URL
    monkeypatch.setattr(staging, "SaplAPIClient", lambda **_kwargs: FakeSaplClient(content))
    identity_key = IDENTITY_KEY if sapl_id == 1160 else LC261_IDENTITY_KEY
    number, year = ("208", 2022) if sapl_id == 1160 else ("261", 2025)
    publication_date = date(year, 3, 8) if sapl_id == 1160 else date(2025, 7, 4)
    identity = SimpleNamespace(
        identity_key=identity_key,
        identity_json={
            "jurisdiction": "BR-RN-NATAL",
            "type": "lei_complementar",
            "number": number,
            "year": year,
        },
    )
    candidate = {
        "identity": identity,
        "publication_date": publication_date,
        "safe_metadata": {"id": sapl_id},
    }
    monkeypatch.setattr(staging, "_validated_record", lambda _client, requested_id: ({}, url, candidate) if requested_id == sapl_id else {})


@pytest.mark.django_db
def test_lc208_conflict_candidate_dry_run_does_not_write(monkeypatch, tmp_path):
    qa_root = tmp_path / "qa"
    _qa_environment(monkeypatch, qa_root)
    norma = Norma.objects.create(
        sapl_id=1160,
        tipo="Lei Complementar",
        numero="208",
        ano=2022,
        data_publicacao=date(2022, 3, 8),
        pdf_url=PDF_URL,
        status=Norma.Status.PENDING,
        identity_key="legacy-lc208-key",
    )
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_lc208_unlinked_candidate(apply=False)

    norma.refresh_from_db()
    assert result["mode"] == "dry-run"
    assert result["identity_conflicts"] == ["identity_key"]
    assert result["will_create_unlinked_document_candidate"] is True
    assert result["will_link_to_norma"] is False
    assert result["will_mutate_existing_norma"] is False
    assert result["will_accept_text"] is False
    assert result["will_enter_rag"] is False
    assert norma.identity_key == "legacy-lc208-key"


@pytest.mark.django_db
def test_lc261_conflict_candidate_dry_run_does_not_write(monkeypatch, tmp_path):
    qa_root = tmp_path / "qa"
    _qa_environment(monkeypatch, qa_root, sapl_id=8823)
    norma = Norma.objects.create(
        sapl_id=8823,
        tipo="Lei Complementar",
        numero="261",
        ano=2025,
        data_publicacao=date(2025, 7, 4),
        pdf_url=LC261_PDF_URL,
        status=Norma.Status.PENDING,
        identity_key="legacy-lc261-key",
    )
    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        result = staging.stage_lc261_unlinked_candidate(apply=False)

    norma.refresh_from_db()
    assert result["mode"] == "dry-run"
    assert result["identity_conflicts"] == ["identity_key"]
    assert result["will_create_unlinked_document_candidate"] is True
    assert result["will_mutate_existing_norma"] is False
    assert result["will_accept_text"] is False
    assert not DocumentoNormativo.objects.filter(metadata_json__sapl_id=8823).exists()
    assert norma.identity_key == "legacy-lc261-key"


@pytest.mark.django_db
def test_lc261_conflict_candidate_is_idempotent_and_stays_unlinked_pending(
    monkeypatch, tmp_path
):
    qa_root = tmp_path / "qa"
    _qa_environment(monkeypatch, qa_root, sapl_id=8823)
    norma = Norma.objects.create(
        sapl_id=8823,
        tipo="Lei Complementar",
        numero="261",
        ano=2025,
        data_publicacao=date(2025, 7, 4),
        pdf_url=LC261_PDF_URL,
        status=Norma.Status.PENDING,
        identity_key="legacy-lc261-key",
    )

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = staging.stage_lc261_unlinked_candidate(apply=True)
        second = staging.stage_lc261_unlinked_candidate(apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    norma.refresh_from_db()
    assert first["created"] is True
    assert second["created"] is False
    assert first["norma_linked"] is False
    assert first["text_accepted"] is False
    assert first["identity_conflicts"] == ["identity_key"]
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.metadata_json["sapl_id"] == 8823
    assert document.metadata_json["association_status"] == "identity_conflict_unlinked"
    assert document.metadata_json["identity_key_candidate"] == LC261_IDENTITY_KEY
    assert norma.identity_key == "legacy-lc261-key"
    assert not DocumentoNormativo.objects.filter(metadata_json__sapl_id=1160).exists()


@pytest.mark.django_db
def test_lc208_conflict_candidate_is_idempotent_and_stays_unlinked_pending(
    monkeypatch, tmp_path
):
    qa_root = tmp_path / "qa"
    _qa_environment(monkeypatch, qa_root)
    norma = Norma.objects.create(
        sapl_id=1160,
        tipo="Lei Complementar",
        numero="208",
        ano=2022,
        data_publicacao=date(2022, 3, 8),
        pdf_url=PDF_URL,
        status=Norma.Status.PENDING,
        identity_key="legacy-lc208-key",
    )

    with override_settings(QA_ROOT=qa_root, NORMATIVE_ARCHIVE_ENABLED=True):
        first = staging.stage_lc208_unlinked_candidate(apply=True)
        second = staging.stage_lc208_unlinked_candidate(apply=True)

    document = DocumentoNormativo.objects.get(public_id=first["document_id"])
    norma.refresh_from_db()
    assert first["created"] is True
    assert second["created"] is False
    assert first["norma_linked"] is False
    assert first["text_accepted"] is False
    assert first["identity_conflicts"] == ["identity_key"]
    assert document.norma_id is None
    assert document.accepted_extraction_id is None
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.metadata_json["association_status"] == "identity_conflict_unlinked"
    assert document.metadata_json["identity_status"] == "candidate"
    assert document.metadata_json["source_provenance"]["kind"] == "sapl_norma_pdf"
    assert document.metadata_json["identity_key_candidate"] == IDENTITY_KEY
    assert norma.identity_key == "legacy-lc208-key"
