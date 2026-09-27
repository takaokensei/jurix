"""Smoke contracts for every first-party workspace surface."""

from pathlib import Path
from types import SimpleNamespace

import pytest
from django.contrib.auth import get_user_model
from django.test import Client

from src.apps.legislation.models import ChatSession, Dispositivo, Norma
from src.apps.legislation.workspace_views import _deduplicate_search_results

pytestmark = pytest.mark.django_db


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


def test_product_root_enters_the_assistant_flow():
    response = Client().get("/")
    assert response.status_code == 302
    assert response["Location"] == "/assistente/"


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
    assert first.content.count(b"workspace-history-card") == 20
    assert second.content.count(b"workspace-history-card") == 1


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
    assert 'class="jurix-norma-stat-label">normas consolidadas<' in body


def test_norma_compare_renders_aligned_diff_and_explicit_missing_effective_date(norma):
    from datetime import date

    norma.data_publicacao = date(2026, 1, 1)
    norma.save(update_fields=["data_publicacao"])
    response = Client().get(f"/normas/{norma.pk}/compare/")
    body = response.content.decode()
    assert "Diferenças linha a linha" in body
    assert "Original (OCR)" in body
    assert "Consolidado" in body
    assert "Art. 1º Texto." in body

    detail_body = Client().get(f"/normas/{norma.pk}/").content.decode()
    assert "Não informada" in detail_body
    assert "Vigente desde a publicação" in detail_body
    assert "não registra uma data de vigência específica" in detail_body


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
    assert ".compare-container { display:grid; grid-template-columns:minmax(0,1fr)" in css
    assert ".alert-info strong { color: var(--figma-text-white, #f8fafc); }" in css


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
    assert "Modo: não executada" in search_body


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
