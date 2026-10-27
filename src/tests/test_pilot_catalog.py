"""The operational collection is discoverable without an archive query switch."""

import hashlib

import pytest
from django.test import RequestFactory, override_settings

from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.pilot_catalog import pilot_catalog_context
from src.processing.pilot_corpus import publish_revision


@pytest.fixture
def pilot_catalog(tmp_path, monkeypatch):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    sources = []
    for number in range(1, 21):
        digest = hashlib.sha256(str(number).encode()).hexdigest()
        DocumentoNormativo.objects.create(
            document_key=digest, content_sha256=digest,
            source_kind="archive", source_ref=f"test-pilot:{number}",
        )
        sources.append({
            "pdf_sha256": digest, "source_role": "primary",
            "norma_key": f"BR-RN-NATAL|lei_complementar|{number}|2024",
            "identity": {"tipo": "lei_complementar", "numero": str(number), "ano": 2024},
            "devices": [{"page": 1, "type": "artigo", "number": "1", "device_key": "art-1",
                         "start": 0, "end": len("Art. 1º Texto de teste.")}],
            "aliases": [], "text": "Art. 1º Texto de teste.",
            "coverage": {"act_spans": [[0, len("Art. 1º Texto de teste.")]]},
        })
    publish_revision(tmp_path / "pilot", sources, report={})
    with override_settings(QA_ROOT=tmp_path, JURIX_BUILD_PROFILE="qa", NORMATIVE_ARCHIVE_ENABLED=True):
        yield sources


@pytest.mark.django_db
def test_pilot_cards_are_batched_and_paginated(pilot_catalog, django_assert_num_queries):
    factory = RequestFactory()
    with django_assert_num_queries(1):
        first = pilot_catalog_context(factory.get("/normas/"))
    assert first["pilot_total"] == 20
    assert len(first["pilot_entries"]) == 18
    with django_assert_num_queries(1):
        filtered = pilot_catalog_context(factory.get("/normas/?q=LC+1%2F2024"))
    assert len(filtered["pilot_entries"]) == 1
    assert filtered["pilot_entries"][0]["pdf_url"].endswith("#page=1")
    second = pilot_catalog_context(factory.get("/normas/?piloto_pagina=2"))
    assert len(second["pilot_entries"]) == 2


@pytest.mark.django_db
def test_common_library_renders_pilot_and_keeps_reviewed_scope_honest(pilot_catalog, client):
    response = client.get("/normas/")
    assert response.status_code == 200
    assert b"data-pilot-catalog" in response.content
    assert "Nenhuma norma consolidada disponível" not in response.content.decode()
    reviewed = client.get("/normas/?escopo=revisadas")
    assert b"data-pilot-catalog" not in reviewed.content
    exact = client.get("/normas/?escopo=experimental&q=LC+1%2F2024")
    assert exact.context["pilot_filtered_count"] == 1
    assert exact.context["filtered_count"] == 1
    search = client.get("/pesquisa/?escopo=experimental&q=LC+1%2F2024")
    assert search.status_code == 200
    assert search.context["pilot_filtered_count"] == 1
    assert "Consultar texto, alterações e grafo" in search.content.decode()
    document = DocumentoNormativo.objects.get(content_sha256=pilot_catalog[0]["pdf_sha256"])
    detail = client.get(f"/normas/documentos/{document.public_id}/")
    assert detail.status_code == 200
    assert b"data-pilot-document" in detail.content
    assert "Conferir Art. 1 no PDF" in detail.content.decode()
    assert "Texto extraído sem segmentação" not in detail.content.decode()
