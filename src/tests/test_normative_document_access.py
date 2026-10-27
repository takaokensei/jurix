from __future__ import annotations

import hashlib
import json

import pytest
from django.contrib.auth.models import User
from django.test import Client, override_settings
from django.urls import reverse

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.document_views import _document_path
from src.processing.official_urls import safe_official_url


@pytest.mark.django_db
def test_public_pilot_pdf_membership_never_grants_product_access(tmp_path, monkeypatch):
    from django.contrib.auth.models import AnonymousUser
    from django.http import Http404
    from django.test import RequestFactory

    from src.apps.legislation.document_views import _authorized_document
    from src.processing.pilot_corpus import publish_revision

    digest = hashlib.sha256(b"public-pilot-pdf").hexdigest()
    document = DocumentoNormativo.objects.create(
        document_key=digest, content_sha256=digest,
        source_kind=DocumentoNormativo.SourceKind.SAPL, source_ref="pilot-access-test",
    )
    publish_revision(tmp_path / "pilot", [{
        "pdf_sha256": digest, "norma_key": "BR-RN-NATAL|lei|20|2026", "source_role": "primary",
    }], report={})
    request = RequestFactory().get("/normas/documentos/example/pdf/")
    request.user = AnonymousUser()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    with override_settings(QA_ROOT=tmp_path, JURIX_BUILD_PROFILE="qa", NORMATIVE_ARCHIVE_ENABLED=True):
        assert _authorized_document(request, document.public_id).pk == document.pk
    with override_settings(QA_ROOT=tmp_path, JURIX_BUILD_PROFILE="production", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(Http404):
            _authorized_document(request, document.public_id)
    monkeypatch.setenv("JURIX_QA_ONLY", "0")
    with override_settings(QA_ROOT=tmp_path, JURIX_BUILD_PROFILE="qa", NORMATIVE_ARCHIVE_ENABLED=True):
        with pytest.raises(Http404):
            _authorized_document(request, document.public_id)


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
        document.metadata_json = {
            "identity_candidate": {"type": "decreto", "number": "7795", "year": 2005}
        }
        document.save(update_fields=["metadata_json", "updated_at"])
        decree_listing = client.get(reverse("legislation:norma_list"))
        decree_evidence = client.get(evidence_url)

    assert listing.status_code == 200
    assert evidence_url.encode() in listing.content
    assert evidence.status_code == 200
    assert "<h1 id=\"evidence-title\">Lei Ordinária nº 123/2024</h1>" in evidence.content.decode()
    assert decree_evidence.status_code == 200
    assert "Decreto nº 7.795/2005" in decree_listing.content.decode()
    assert "Decreto nº 7795/2005" not in decree_listing.content.decode()
    assert '<h1 id="evidence-title">Decreto nº 7.795/2005</h1>' in decree_evidence.content.decode()
    assert "Candidato do acervo histórico" in evidence.content.decode()
    assert "Documento normativo versionado" not in evidence.content.decode()
    assert "Documento do acervo histórico local." in evidence.content.decode()
    assert "a identificação normativa, a extração do texto e a segmentação precisam de revisão" in evidence.content.decode()
    assert "Texto extraído automaticamente — rascunho não revisado" in evidence.content.decode()
    assert evidence.content.decode().count('class="historical-message historical-message--warning document-evidence-review-notice" role="note"') == 1
    assert "Texto extraído sem segmentação" in evidence.content.decode()
    assert "Índice do documento" not in evidence.content.decode()
    assert "<details><summary>Texto integral extraído (rascunho)</summary>" in evidence.content.decode()
    assert "<details open>" not in evidence.content.decode()
    assert text in evidence.content.decode()
    document.refresh_from_db()
    assert document.accepted_extraction_id is None

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        assert client.get(evidence_url).status_code == 404


@pytest.mark.django_db
def test_archive_page_resolver_uses_pdf_access_policy_and_returns_only_verified_page():
    legal_text = "Introdução. Art. 1º Conteúdo verificável na segunda página."
    start = legal_text.index("Art. 1º")
    document = DocumentoNormativo.objects.create(
        document_key=hashlib.sha256(b"page-resolver-doc").hexdigest(),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa/page-resolver.pdf",
        content_sha256=hashlib.sha256(b"page-resolver-pdf").hexdigest(),
        original_filename="page-resolver.pdf",
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="qa-page-resolver-v1",
        policy_fingerprint=hashlib.sha256(b"page-resolver-policy").hexdigest(),
        text_version="qa-page-resolver-text-v1",
        legal_text=legal_text,
        page_map_json=[
            {"page": 1, "start": 0, "end": start + 8},
            {"page": 2, "start": start + 8, "end": len(legal_text)},
        ],
    )
    request_source = {
        "evidence_scope": "isolated_qa_archive",
        "document_id": str(document.public_id),
        "document_sha256": document.content_sha256,
        "span": {"start": start, "end": len(legal_text)},
        "full_text": legal_text[start:],
    }
    url = reverse("legislation_api:archive_citation_resolve_pages")
    client = Client()

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        response = client.post(
            url,
            data=json.dumps({"sources": [request_source]}),
            content_type="application/json",
        )
    assert response.status_code == 200
    assert response.json() == {"success": True, "resolved": [{"index": 0, "page": 2}]}
    assert response["Cache-Control"] == "private, no-store, max-age=0"

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        hidden = client.post(
            url,
            data=json.dumps({"sources": [request_source]}),
            content_type="application/json",
        )
    assert hidden.status_code == 200
    assert hidden.json() == {"success": True, "resolved": []}


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
