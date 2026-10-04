from __future__ import annotations

import hashlib

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import reverse

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.document_views import _document_path
from src.processing.official_urls import safe_official_url


@pytest.fixture
def document_map(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    return root, seed_fixture(root / "fixture-map.json")


@pytest.mark.django_db(transaction=True)
def test_approved_document_evidence_is_public_and_candidate_is_hidden(document_map):
    _root, mapping = document_map
    doc_id = mapping["temporal_scenarios"]["norma_a"]["document_id"]
    response = Client().get(reverse("legislation:document_evidence", args=[doc_id]))
    assert response.status_code == 200
    assert "O prazo é de dez dias" in response.content.decode()
    assert response["Cache-Control"] == "private, no-store, max-age=0"

    conflict_id = DocumentoNormativo.objects.get(
        source_ref__endswith=":conflito:v1"
    ).public_id
    guest = Client().get(reverse("legislation:document_evidence", args=[conflict_id]))
    assert guest.status_code == 404
    staff = User.objects.get(username="jurix-qa-reviewer")
    client = Client()
    client.force_login(staff)
    assert client.get(reverse("legislation:document_evidence", args=[conflict_id])).status_code == 200


@pytest.mark.django_db
def test_archive_candidates_are_inspectable_only_behind_explicit_qa_flag():
    from src.apps.legislation.document_models import ExtracaoDocumento

    text = "Art. 1º. Texto extraído para revisão, não para consolidação automática."
    document = DocumentoNormativo.objects.create(
        document_key=hashlib.sha256(b"archive-candidate-test").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa-archive://entry-0",
        entry_index=0,
        original_filename="LeiOrdinaria_2024_123.pdf",
        content_sha256=hashlib.sha256(b"candidate-pdf").hexdigest(),
        metadata_json={"identity_candidate": {"type": "lei_ordinaria", "number": "123", "year": 2024}},
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="qa-extractor-v1",
        policy_fingerprint=hashlib.sha256(b"qa-policy").hexdigest(),
        text_version="qa-text-v1",
        raw_text=text,
        legal_text=text,
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256=hashlib.sha256(b"qa-extraction").hexdigest(),
    )
    client = Client()
    evidence_url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        listing = client.get(reverse("legislation:norma_list"))
        evidence = client.get(evidence_url)

    assert listing.status_code == 200
    assert evidence_url.encode() in listing.content
    assert evidence.status_code == 200
    assert "<h1 id=\"evidence-title\">Lei Ordinária nº 123/2024</h1>" in evidence.content.decode()
    assert "Documento do acervo histórico local." in evidence.content.decode()
    assert "a identificação normativa, a extração do texto e a segmentação precisam de revisão" in evidence.content.decode()
    assert "Texto extraído automaticamente — rascunho não revisado" in evidence.content.decode()
    assert "Texto extraído sem segmentação" in evidence.content.decode()
    assert "Índice do documento" not in evidence.content.decode()
    assert text in evidence.content.decode()
    document.refresh_from_db()
    assert document.accepted_extraction_id is None

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        assert client.get(evidence_url).status_code == 404


@pytest.mark.django_db(transaction=True)
def test_pdf_serving_checks_root_hash_headers_and_private_cache(document_map):
    root, mapping = document_map
    document = DocumentoNormativo.objects.get(public_id=mapping["scenarios"]["conflito"]["document_id"])
    staff = User.objects.get(username="jurix-qa-reviewer")
    client = Client()
    client.force_login(staff)
    blob = b"%PDF-1.4\nsynthetic QA PDF\n%%EOF\n"
    key = "safe/synthetic.pdf"
    path = root / "normative-archive" / key
    path.parent.mkdir(parents=True)
    path.write_bytes(blob)
    document.storage_key = key
    document.content_sha256 = hashlib.sha256(blob).hexdigest()
    document.size_bytes = len(blob)
    document.save(update_fields=["storage_key", "content_sha256", "size_bytes", "updated_at"])
    with override_settings(QA_ROOT=root):
        response = client.get(reverse("legislation:document_pdf", args=[document.public_id]))
        assert response.status_code == 200
        assert response["Content-Type"] == "application/pdf"
        assert response["X-Content-Type-Options"] == "nosniff"
        assert response["Cache-Control"] == "private, no-store, max-age=0"
        assert b"".join(response.streaming_content) == blob


@pytest.mark.django_db(transaction=True)
def test_pdf_rejects_traversal_and_blob_hash_mismatch(document_map):
    root, mapping = document_map
    document = DocumentoNormativo.objects.get(public_id=mapping["scenarios"]["conflito"]["document_id"])
    document.storage_key = "../outside.pdf"
    with override_settings(QA_ROOT=root), pytest.raises(Exception, match="Documento indisponível"):
        _document_path(document)

    staff = User.objects.get(username="jurix-qa-reviewer")
    client = Client()
    client.force_login(staff)
    document.storage_key = "safe/mismatch.pdf"
    path = root / "normative-archive" / document.storage_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"%PDF-1.4\nchanged\n")
    document.content_sha256 = hashlib.sha256(b"different content").hexdigest()
    document.size_bytes = path.stat().st_size
    document.save(update_fields=["storage_key", "content_sha256", "size_bytes", "updated_at"])
    with override_settings(QA_ROOT=root):
        response = client.get(reverse("legislation:document_pdf", args=[document.public_id]))
    assert response.status_code == 404


@pytest.mark.django_db(transaction=True)
def test_document_routes_are_explicit_before_norma_integer_routes():
    assert reverse("legislation:norma_detail", args=[123]).endswith("/normas/123/")
    assert reverse("legislation:document_pdf", args=["12345678-1234-5678-1234-567812345678"]).endswith("/pdf/")


def test_official_source_url_rejects_active_or_credentialed_schemes():
    assert safe_official_url("https://sapl.example.gov/document.pdf") == "https://sapl.example.gov/document.pdf"
    assert safe_official_url("javascript:alert(1)") is None
    assert safe_official_url("https://user:password@example.gov/document.pdf") is None
