"""Smoke contracts for every first-party workspace surface."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.contrib.auth import get_user_model
from django.db import connection
from django.test import Client, override_settings

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import ChatMessage, ChatSession, Dispositivo, Norma
from src.apps.legislation.workspace_views import _deduplicate_search_results, _rank_history
from src.apps.operations.models import CorpusRevision

pytestmark = pytest.mark.django_db


def test_history_search_ranks_bag_of_words_relevance_before_recency():
    recent_weak = SimpleNamespace(
        title="Consulta recente",
        history_messages=[SimpleNamespace(content="Assunto geral")],
        updated_at=2,
    )
    relevant_old = SimpleNamespace(
        title="Política de imóveis abandonados",
        history_messages=[
            SimpleNamespace(content="Lei municipal sobre imóveis abandonados e revitalização")
        ],
        updated_at=1,
    )
    assert _rank_history([recent_weak, relevant_old], "imóveis abandonados") == [relevant_old]


def test_history_preview_uses_first_user_question_not_a_recent_answer():
    user = get_user_model().objects.create_user(username="history-preview", password="pass")
    session = ChatSession.objects.create(user=user, title="Resumo gerado")
    ChatMessage.objects.create(session=session, role="user", content="Pergunta inicial distinta")
    ChatMessage.objects.create(session=session, role="assistant", content="Resposta inicial")
    for index in range(11):
        ChatMessage.objects.create(
            session=session, role="user", content=f"Pergunta posterior {index}"
        )
        ChatMessage.objects.create(
            session=session, role="assistant", content=f"Resposta posterior {index}"
        )
    client = Client()
    client.force_login(user)

    response = client.get("/historico/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Pergunta inicial distinta" in body
    assert "Resposta inicial" not in body


@pytest.fixture
def norma():
    return Norma.objects.create(
        tipo="Lei",
        numero="123",
        ano=2026,
        status="consolidated",
        ementa="Norma de teste",
        texto_original="Art. 1º Texto.",
        texto_consolidado="Lei nº 123/2026\nArt. 1º Texto.",
    )


def test_workspace_surfaces_render_without_server_errors(norma):
    client = Client()
    urls = [
        "/",
        "/assistente/",
        "/normas/",
        "/pesquisa/",
        "/colecoes/",
        "/historico/",
        "/configuracoes/",
        f"/normas/{norma.pk}/",
        f"/normas/{norma.pk}/compare/",
        f"/normas/{norma.pk}/tree/",
        "/api/v1/normas/",
    ]
    for url in urls:
        response = client.get(url, follow=True)
        assert response.status_code == 200, url
        assert b"Server Error" not in response.content
        assert b"Traceback" not in response.content


def test_norma_detail_does_not_claim_currently_in_force_when_corpus_completeness_is_unknown():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="consolidated",
        data_publicacao="2026-09-21",
        data_vigencia="2026-09-21",
        texto_consolidado="Art. 1º Texto.",
    )
    CorpusRevision.objects.update_or_create(
        key="municipal",
        defaults={
            "completeness": "unknown",
            "digest": "a" * 64,
            "norm_count": 1,
            "device_count": 1,
        },
    )

    response = Client().get(f"/normas/{norma.pk}/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Situação atual não verificada no corpus" in body
    assert "Início de vigência registrado" in body
    assert '<span class="badge badge-success">Vigente</span>' not in body


def test_pending_norma_detail_does_not_call_the_record_consolidated():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="9001",
        ano=2020,
        status="pending",
        texto_original="Art. 1º Texto sintético.",
    )

    body = Client().get(f"/normas/{norma.pk}/").content.decode("utf-8")

    assert "Norma municipal" in body
    assert '<span class="badge badge-success">Consolidada</span>' not in body


def test_norma_detail_explicitly_labels_synthetic_qa_fixture():
    norma = Norma.objects.create(
        tipo="Lei",
        numero="9001",
        ano=2020,
        status="pending",
        texto_original="Art. 5º O prazo é de dez dias.",
    )
    document = DocumentoNormativo.objects.create(
        document_key="b" * 64,
        norma=norma,
        source_kind=DocumentoNormativo.SourceKind.LEGACY,
        source_ref="jurix-synthetic-qa:test",
        original_filename="[SINTÉTICO QA] Lei 9001/2020.pdf",
        content_sha256="c" * 64,
        metadata_json={"synthetic": True},
    )
    norma.documento_base = document
    norma.save(update_fields=["documento_base"])

    body = Client().get(f"/normas/{norma.pk}/").content.decode("utf-8")

    assert "Fixture sintética de QA." in body
    assert "não representa uma norma real nem uma validação jurídica" in body

    comparison = Client().get(
        f"/normas/{norma.pk}/compare/?from_as_of=2020-01-01&to_as_of=2020-01-02"
    ).content.decode("utf-8")
    assert "Fixture sintética de QA." in comparison
    assert "não representa uma norma real nem uma validação jurídica" in comparison


def test_collections_and_assistant_copy_describe_only_available_products():
    anonymous = Client()
    collections = anonymous.get("/colecoes/").content.decode()
    assistant = anonymous.get("/assistente/").content.decode()

    assert "normas municipais salvas" in collections
    assert "normas e evidências" not in collections
    assert "legislação municipal" in assistant
    assert "jurisprudência..." not in assistant

    user = get_user_model().objects.create_user(username="collections-copy", password="pass")
    authenticated = Client()
    authenticated.force_login(user)
    assert (
        "Adicione normas municipais à coleção" in authenticated.get("/colecoes/").content.decode()
    )


def test_workspace_uses_local_system_fonts_regardless_of_google_fonts_csp_opt_in():
    client = Client()
    routes = ("/assistente/", "/normas/", "/configuracoes/")
    with override_settings(CSP_ALLOW_GOOGLE_FONTS=False):
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200
            assert b"fonts.googleapis.com" not in response.content
            assert b"fonts.gstatic.com" not in response.content
            assert "fonts.googleapis.com" not in response["Content-Security-Policy"]

    with override_settings(CSP_ALLOW_GOOGLE_FONTS=True):
        for route in routes:
            response = client.get(route)
            assert response.status_code == 200
            assert b"fonts.googleapis.com" not in response.content
            assert b"fonts.gstatic.com" not in response.content

    styles = Path("src/apps/core/static/css/jurix-figma.css").read_text(encoding="utf-8")
    assert "--font-sans: system-ui" in styles
    assert "--font-serif: Georgia" in styles


def test_product_root_enters_the_assistant_flow():
    response = Client().get("/")
    assert response.status_code == 302
    assert response["Location"] == "/assistente/"


def test_anonymous_assistant_get_does_not_create_session_state_or_chat_records():
    client = Client()

    assert client.get("/assistente/").status_code == 200
    assert client.get("/assistente/").status_code == 200
    assert "temp_chat_session_id" not in client.session
    assert "temp_chat_messages" not in client.session
    assert ChatSession.objects.count() == 0


def test_authenticated_assistant_get_does_not_change_active_session():
    user = get_user_model().objects.create_user(username="assistant-get", password="pass")
    active = ChatSession.objects.create(user=user, title="Ativa", is_active=True)
    inactive = ChatSession.objects.create(user=user, title="Inativa", is_active=False)
    client = Client()
    client.force_login(user)

    assert client.get(f"/assistente/{inactive.slug}/").status_code == 200
    assert client.get(f"/assistente/{inactive.slug}/").status_code == 200
    active.refresh_from_db()
    inactive.refresh_from_db()

    assert active.is_active is True
    assert inactive.is_active is False
    assert ChatSession.objects.filter(user=user).count() == 2


def test_semantic_search_empty_state_omits_none_year_from_catalog_link():
    response = Client().get("/pesquisa/", {"q": "x" * 201})
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Buscar no acervo normativo" in body
    assert "&amp;ano=" in body
    assert "ano=None" not in body


def test_exact_normative_search_not_found_uses_nonsemantic_empty_state():
    response = Client().get("/pesquisa/", {"q": "Lei nº 9001/2020"})
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Referência normativa exata não localizada no acervo municipal." in body
    assert "Norma não encontrada no acervo" in body
    assert "Nenhuma correspondência semântica encontrada." not in body


def test_history_page_paginates_authenticated_sessions():
    user = get_user_model().objects.create_user(username="history-page", password="pass")
    ChatSession.objects.bulk_create(
        [ChatSession(user=user, title=f"Conversa {index}") for index in range(21)]
    )
    client = Client()
    assert client.login(username="history-page", password="pass")

    first = client.get("/historico/")
    second = client.get("/historico/?page=2")

    assert first.status_code == second.status_code == 200
    first_body = first.content.decode("utf-8")
    second_body = second.content.decode("utf-8")
    assert "Próxima" in first_body
    assert "Anterior" in second_body
    assert first.content.count(b"data-history-card") == 20
    assert second.content.count(b"data-history-card") == 1
    assert b"data-history-delete" in first.content
    assert (
        "csrftoken" in client.cookies
    ), "History deletion needs the CSRF cookie for its API request"


def test_norma_surfaces_expose_consistent_identity(norma):
    client = Client()
    for url in (
        f"/normas/{norma.pk}/",
        f"/normas/{norma.pk}/compare/",
        f"/normas/{norma.pk}/tree/",
    ):
        response = client.get(url)
        body = response.content.decode()
        assert "Lei" in body
        assert "123" in body
        assert "2026" in body


def test_norma_list_corpus_total_matches_current_database(norma):
    response = Client().get("/normas/")
    body = response.content.decode()
    assert 'class="jurix-norma-stat-value">1<' in body
    assert 'class="jurix-norma-stat-label">no acervo<' in body
    assert 'class="jurix-norma-stat-label">resultados<' in body


def test_norma_list_surfaces_archive_candidates_only_in_qa():
    document = DocumentoNormativo.objects.create(
        document_key="a" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:9876",
        archive_sha256="b" * 64,
        entry_index=9876,
        entry_name="sistema2/pdfs/LeiComplementar_20211220_198_.pdf",
        original_filename="LeiComplementar_20211220_198_.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key="sha256/aa/bb/example.pdf",
        size_bytes=123,
        content_sha256="c" * 64,
        metadata_json={
            "identity_key": "BR-RN-NATAL|lei_complementar|lc|198|2021",
            "identity_candidate": {"type": "lei_complementar", "number": "198", "year": 2021},
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-qa-test",
        policy_fingerprint="d" * 64,
        text_version="technical_text_v1",
        legal_text="Texto extraído para validar o estado de segmentação.",
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=False):
        production_body = Client().get("/normas/").content.decode()
    assert "Documentos para consolidação" not in production_body
    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        body = Client().get("/normas/").content.decode()

    assert "Documentos para consolidação" in body
    assert "Lei Complementar nº 198/2021" in body
    assert "Estes documentos compõem o acervo histórico local e estão disponíveis para consulta." in body
    assert "Ainda não foram consolidados no corpus principal" in body
    assert "Identidade candidata reconhecida; falta revisão humana." in body
    assert 'id="archive-candidate-search"' in body
    assert 'id="archive-candidate-identity"' in body
    assert 'id="archive-candidate-extraction"' in body
    assert 'data-identity="resolved"' in body
    assert 'data-review-status="pending"' in body
    assert 'data-extraction-status="complete"' in body
    assert "Extração completa · 1 página · segmentação de dispositivos pendente" in body
    assert 'Exibindo 1 de 1 documentos.' in body


def test_norma_list_rewrites_legacy_sapl_detail_url(norma):
    norma.sapl_id = 9387
    norma.sapl_url = "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/"
    norma.save(update_fields=["sapl_id", "sapl_url"])
    body = Client().get("/normas/").content.decode()
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387/"' in body
    assert "/norma/normajuridica/9387/" not in body


def test_norma_detail_rewrites_legacy_sapl_url_without_mutating_the_record(norma):
    norma.sapl_id = 9387
    legacy = "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/"
    norma.sapl_url = legacy
    norma.save(update_fields=["sapl_id", "sapl_url"])
    response = Client().get(f"/normas/{norma.pk}/")
    body = response.content.decode()
    assert response.status_code == 200
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387/"' in body
    assert legacy not in body
    norma.refresh_from_db()
    assert norma.sapl_url == legacy


def test_workspace_new_research_link_requests_a_blank_conversation():
    body = Client().get("/normas/").content.decode()
    assert 'href="/assistente/?new=1" id="workspace-new-chat"' in body


def test_norma_compare_renders_aligned_diff_and_explicit_missing_effective_date(norma):
    from datetime import date

    norma.data_publicacao = date(2026, 1, 1)
    norma.save(update_fields=["data_publicacao"])
    response = Client().get(f"/normas/{norma.pk}/compare/")
    body = response.content.decode()
    assert "Diferenças textuais estruturais" in body
    assert "Original (OCR)" in body
    assert "Consolidado" in body
    assert "Art. 1º Texto." in body

    detail_body = Client().get(f"/normas/{norma.pk}/").content.decode()
    assert "Não informada" in detail_body
    assert "Data de vigência não registrada no corpus" in detail_body
    assert "Confirme a vigência na fonte oficial" in detail_body


@pytest.mark.parametrize(
    "original_text",
    [
        "linha\n" * 1_000 + "linha",
        "x" * 120_001,
    ],
    ids=["line-limit", "character-limit"],
)
def test_norma_compare_declines_oversized_diff_and_links_to_full_versions(norma, original_text):
    norma.texto_original = original_text
    norma.sapl_url = "https://sapl.example.test/norma/123/"
    norma.save(update_fields=["texto_original", "sapl_url"])

    with patch("src.apps.legislation.views.build_legal_diff") as matcher:
        response = Client().get(f"/normas/{norma.pk}/compare/")

    assert response.status_code == 200
    body = response.content.decode()
    assert "Comparação grande indisponível nesta visualização" in body
    assert "Nenhum diff parcial foi gerado." in body
    assert "Ler texto consolidado completo" in body
    assert 'href="https://sapl.example.test/norma/123/"' in body
    assert "Diferenças textuais estruturais" not in body
    matcher.assert_not_called()


def test_norma_compare_unknown_norma_returns_not_found():
    response = Client().get("/normas/999999/compare/")
    assert response.status_code == 404


def test_norma_tree_exposes_hierarchy_semantics(norma):
    body = Client().get(f"/normas/{norma.pk}/tree/").content.decode()
    assert 'role="tree"' in body
    assert "Estrutura hierárquica dos dispositivos" in body


def test_norma_detail_exposes_safe_assistant_and_official_source_actions(norma):
    norma.sapl_url = "https://sapl.example.test/norma/123/"
    norma.save(update_fields=["sapl_url"])
    body = Client().get(f"/normas/{norma.pk}/").content.decode()
    assert "Perguntar sobre esta norma" in body
    assert 'href="https://sapl.example.test/norma/123/"' in body
    assert 'target="_blank"' in body
    assert 'rel="noopener noreferrer"' in body


def test_norma_detail_device_index_preserves_hierarchical_deep_links(norma):
    article = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Texto", ordem=1, caminho=""
    )
    inciso = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="I",
        texto="Inciso",
        ordem=2,
        dispositivo_pai=article,
        caminho="",
    )
    alinea = Dispositivo.objects.create(
        norma=norma,
        tipo="alinea",
        numero="a)",
        texto="Alínea",
        ordem=3,
        dispositivo_pai=inciso,
        caminho="",
    )
    second_article = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="2º", texto="Texto", ordem=4, caminho=""
    )

    body = Client().get(f"/normas/{norma.pk}/").content.decode()

    assert 'class="dispositivos-index-links" data-device-index' in body
    assert f'href="#dispositivo-{article.pk}"' in body
    assert f'href="#dispositivo-{inciso.pk}"' in body
    assert f'href="#dispositivo-{alinea.pk}"' in body
    assert f'href="#dispositivo-{second_article.pk}"' in body
    assert f'data-device-parent-id="{inciso.pk}"' in body
    assert 'data-device-type="artigo"' in body


def test_norma_pdf_export_returns_a_real_pdf(norma):
    import fitz

    response = Client().get(f"/normas/{norma.pk}/export/pdf/")
    assert response.status_code == 200
    assert response["Content-Type"] == "application/pdf"
    assert response["Content-Disposition"].startswith("attachment;")
    assert response.content.startswith(b"%PDF-")
    with fitz.open(stream=response.content, filetype="pdf") as document:
        exported_text = "\n".join(page.get_text() for page in document)
    assert "Art. 1º Texto." in exported_text


def test_assistant_can_prefill_a_consolidated_norm_context(norma):
    body = Client().get(f"/assistente/?norma_id={norma.pk}").content.decode()
    assert f"Sobre Lei nº {norma.numero}/{norma.ano}:" in body


def test_assistant_ignores_unknown_or_non_numeric_norm_context(norma):
    for query in ("?norma_id=not-a-number", "?norma_id=999999"):
        body = Client().get(f"/assistente/{query}").content.decode()
        assert "Sobre Lei nº" not in body


def test_norma_detail_api_returns_devices_without_model_helper_error(norma):
    response = Client().get(f"/api/v1/normas/{norma.pk}/")
    assert response.status_code == 200
    payload = response.json()
    assert payload["success"] is True
    assert payload["norma"]["id"] == norma.pk
    assert payload["dispositivos"] == []


def test_norma_detail_api_builds_missing_hierarchy_from_loaded_tree(norma):
    article = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Texto", ordem=1, caminho=""
    )
    paragraph = Dispositivo.objects.create(
        norma=norma,
        tipo="paragrafo",
        numero="2º",
        texto="Parágrafo",
        ordem=2,
        dispositivo_pai=article,
        caminho="",
    )

    payload = Client().get(f"/api/v1/normas/{norma.pk}/").json()
    by_id = {item["id"]: item for item in payload["dispositivos"]}
    assert by_id[paragraph.id]["hierarchy"] == "Art. 1º > § 2º"


def test_norma_detail_api_returns_json_404_for_unknown_norma():
    response = Client().get("/api/v1/normas/999999/")
    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "Norma with ID 999999 not found",
    }


def test_first_party_templates_do_not_depend_on_inline_csp_bypasses():
    root = Path(__file__).parents[1] / "apps" / "legislation" / "templates"
    for template in root.rglob("*.html"):
        source = template.read_text(encoding="utf-8")
        assert "<style" not in source.lower(), template
        assert "style=" not in source.lower(), template
        assert "javascript:" not in source.lower(), template

    css = (
        Path(__file__).parents[1] / "apps" / "core" / "static" / "css" / "jurix-legacy-shell.css"
    ).read_text(encoding="utf-8")
    assert "@media (max-width:640px)" in css
    assert ".tree-node { margin-left:8px" in css
    assert ".compare-container { display: grid; grid-template-columns: minmax(0, 1fr)" in css
    assert ".alert-info strong { color: var(--figma-text-white); }" in css


def test_norma_api_filters_by_human_type_and_year():
    Norma.objects.create(tipo="Decreto", numero="1", ano=2025, status="consolidated")
    Norma.objects.create(tipo="Lei", numero="2", ano=2026, status="consolidated")
    response = Client().get("/api/v1/normas/?tipo=Decreto&ano=2025")
    assert response.status_code == 200
    data = response.json()["normas"]
    assert [(item["tipo"], item["ano"]) for item in data] == [("Decreto", 2025)]
    by_code = Client().get("/api/v1/normas/?tipo=3&ano=2025")
    assert [(item["tipo"], item["ano"]) for item in by_code.json()["normas"]] == [("Decreto", 2025)]

    oversized = Client().get("/api/v1/normas/?search=" + ("x" * 201))
    assert oversized.status_code == 400
    assert "Busca muito longa" in oversized.json()["error"]

    search_page = Client().get("/pesquisa/?q=" + ("x" * 201))
    assert search_page.status_code == 200
    search_body = search_page.content.decode("utf-8")
    assert "Busca muito longa" in search_body
    assert "Busca não executada" in search_body


def test_norma_api_reports_clamped_page_number():
    Norma.objects.create(tipo="Lei", numero="1", ano=2025, status="consolidated")
    response = Client().get("/api/v1/normas/?page=999&page_size=1")

    assert response.status_code == 200
    pagination = response.json()["pagination"]
    assert pagination["page"] == pagination["total_pages"] == 1


def test_legal_search_collapses_multiple_device_hits_per_norm(norma):
    other = Norma.objects.create(tipo="Lei", numero="456", ano=2025, status="consolidated")
    rows = [
        {"norma": norma, "dispositivo": SimpleNamespace(pk=1), "similarity_score": 0.91},
        {"norma": norma, "dispositivo": SimpleNamespace(pk=2), "similarity_score": 0.88},
        {"norma": other, "dispositivo": SimpleNamespace(pk=3), "similarity_score": 0.80},
    ]
    result = _deduplicate_search_results(rows)
    assert [row["norma"].pk for row in result] == [norma.pk, other.pk]
    assert result[0]["dispositivo"].pk == 1

    invalid = Client().get("/api/v1/normas/?ano=not-a-year")
    assert invalid.status_code == 400

    for page_size in ("0", "-10"):
        bounded = Client().get(f"/api/v1/normas/?page_size={page_size}")
        assert bounded.status_code == 200
        assert bounded.json()["pagination"]["page_size"] == 1


@pytest.mark.skipif(
    connection.vendor != "sqlite",
    reason="Este caso testa o fallback lexical específico de SQLite.",
)
def test_legal_search_labels_sqlite_lexical_fallback_as_text_search(norma):
    Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="zoneamento urbano municipal",
    )

    response = Client().get("/pesquisa/", {"q": "zoneamento urbano"})

    assert response.status_code == 200
    assert b"Busca textual" in response.content


def test_legal_search_uses_retrieval_metadata_and_falls_back_after_semantic_failure(monkeypatch):
    class FakeRAG:
        def semantic_search(self, **kwargs):
            assert kwargs["include_metadata"] is True
            return {"results": [], "mode": "unavailable"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "tema sem resultado"})

    assert response.status_code == 200
    assert b"Busca textual" in response.content
    assert (
        b"busca sem\xc3\xa2ntica est\xc3\xa1 temporariamente indispon\xc3\xadvel"
        in response.content
    )


def test_legal_search_labels_successful_vector_retrieval_as_semantic(monkeypatch):
    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "tema sem resultado"})

    assert response.status_code == 200
    assert b"Busca sem\xc3\xa2ntica" in response.content


def test_legal_search_result_links_to_the_matching_device(norma, monkeypatch):
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Texto específico pesquisado.",
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {
                "results": [{"dispositivo": device, "similarity_score": 0.9, "context": {}}],
                "mode": "semantic",
            }

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "texto específico"})
    expected_href = f"/normas/{norma.pk}/#dispositivo-{device.pk}"

    assert response.status_code == 200
    assert expected_href.encode() in response.content
    detail = Client().get(expected_href.split("#", 1)[0])
    assert f'id="dispositivo-{device.pk}"'.encode() in detail.content


def test_legal_search_resolves_explicit_norm_and_article_before_semantic_search(monkeypatch):
    target = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="consolidated",
        ementa="Institui o Programa Municipal de Educação Popular.",
        texto_consolidado="Art. 1º Institui o programa. Art. 4º Entra em vigor na publicação.",
    )
    target_article = Dispositivo.objects.create(
        norma=target,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Fica instituído o Programa Municipal de Educação Popular.",
    )
    distractor = Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2025,
        status="consolidated",
        ementa="Cláusula genérica de vigência.",
        texto_consolidado="Art. 4º Entra em vigor na publicação.",
    )
    Dispositivo.objects.create(
        norma=distractor,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Artigo não relacionado à lei do pedido.",
    )

    class UnexpectedRAG:
        def semantic_search(self, **kwargs):
            raise AssertionError("Explicit norm lookup must not call semantic RAG")

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", UnexpectedRAG)
    client = Client()
    whole_law = client.get("/pesquisa/", {"q": "O que prevê a Lei nº 8.206/2026?"})
    article = client.get("/pesquisa/", {"q": "O que prevê o art. 1º da Lei nº 8.206/2026?"})

    assert whole_law.status_code == article.status_code == 200
    assert f"/normas/{target.pk}/".encode() in whole_law.content
    assert target.ementa.encode() in whole_law.content
    assert "Cláusula genérica de vigência".encode() not in whole_law.content
    assert f"/normas/{target.pk}/#dispositivo-{target_article.pk}".encode() in article.content
    assert f"/normas/{distractor.pk}/".encode() not in article.content


def test_legal_search_explicit_missing_norm_returns_a_qualified_empty_state(monkeypatch):
    other_year = Norma.objects.create(tipo="Lei", numero="8206", ano=2025, status="consolidated")

    class UnexpectedRAG:
        def semantic_search(self, **kwargs):
            raise AssertionError("An exact missing reference must not drift to semantic results")

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", UnexpectedRAG)
    response = Client().get("/pesquisa/", {"q": "O que prevê a Lei nº 8206/2026?"})

    assert response.status_code == 200
    assert b"normativa exata" in response.content.lower()
    assert f"/normas/{other_year.pk}/".encode() not in response.content
