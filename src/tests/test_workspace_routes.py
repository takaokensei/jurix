"""Smoke contracts for every first-party workspace surface."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.db import connection
from django.test import Client, override_settings

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import (
    ChatMessage,
    ChatSession,
    Dispositivo,
    EventoAlteracao,
    Norma,
    NormaTopic,
    Topic,
)
from src.apps.legislation.workspace_views import (
    _deduplicate_search_results,
    _parse_repeal_candidates,
    _pgm_lc258_sapl_registry_evidence,
    _rank_history,
)
from src.apps.operations.models import CorpusRevision

pytestmark = pytest.mark.django_db


def test_settings_exposes_source_freshness_to_staff_only(client):
    anonymous = client.get("/configuracoes/").content.decode()
    assert "Atualização das fontes" not in anonymous

    staff = get_user_model().objects.create_user(
        username="source-health-staff",
        password="qa-password",
        is_staff=True,
    )
    client.force_login(staff)
    response = client.get("/configuracoes/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Atualização das fontes" in body
    assert "SAPL · legislação municipal" in body
    assert "Diário Oficial do Município" in body
    assert "Nenhuma sincronização registrada" in body
    assert "não comprova que o corpus esteja completo" in body


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
        "/explorar/",
        "/conferir/",
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


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_assistant_discloses_unconfigured_official_updates_without_overstating_coverage(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        return_value={"status": "not_configured"},
    ) as source_health:
        archive_response = client.get("/assistente/?corpus=archive-qa")
        standard_response = client.get("/assistente/")

    archive_body = archive_response.content.decode()
    standard_body = standard_response.content.decode()
    assert archive_response.status_code == 200
    assert "A atualização do SAPL e do Diário Oficial não está configurada" in archive_body
    assert "a cobertura das fontes pode estar incompleta" in archive_body
    assert "Atualização das fontes" in standard_body
    assert "A atualização do SAPL e do Diário Oficial não está configurada" in standard_body
    assert source_health.call_count == 4


@override_settings(NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True)
def test_assistant_hides_source_health_exception_details(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        side_effect=RuntimeError("private database hostname"),
    ):
        response = client.get("/assistente/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Não foi possível confirmar a atualização das fontes oficiais" in body
    assert "private database hostname" not in body


def test_assistant_omits_source_warning_when_all_configured_sources_are_current(client):
    with patch(
        "src.apps.ingestion.source_sync_health.get_source_sync_health",
        return_value={"status": "current"},
    ) as source_health:
        response = client.get("/assistente/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Atualização das fontes" not in body
    assert "não está configurada neste ambiente" not in body
    assert source_health.call_count == 2


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
    assert "Nenhum texto pesquisável localizado para esta referência" in body
    assert "Referência exata não localizada nos resultados pesquisáveis desta instância." not in body
    assert "Consultar acervo normativo e catálogo SAPL" in body
    assert "Isso não prova que a norma inexista" in body
    assert "fora do staging" in body
    assert "Nenhuma correspondência semântica encontrada." not in body


@override_settings(
    DEBUG=True,
    NORMATIVE_ARCHIVE_ENABLED=True,
    NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
)
def test_exact_normative_search_with_archive_candidate_is_not_shown_as_error(client):
    DocumentoNormativo.objects.create(
        document_key="d" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:1202010",
        entry_index=1202010,
        original_filename="LeiComplementar_120_2010.pdf",
        content_sha256="e" * 64,
        metadata_json={
            "identity_candidate": {
                "type": "lei_complementar",
                "number": "120",
                "year": 2010,
            }
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    from src.processing.document_search import search_archive_documents

    assert search_archive_documents("Lei Complementar nº 120/2010")["count"] == 1

    response = client.get("/pesquisa/", {"q": "Lei Complementar nº 120/2010"})
    body = response.content.decode("utf-8")

    assert response.status_code == 200
    assert "Acervo histórico local" in body
    assert "Referência normativa exata não localizada" not in body
    assert 'class="workspace-alert"' not in body
    assert "Referência ainda não consolidada" in body
    assert "A busca encontrou 1 PDF candidato no acervo histórico" in body
    assert "1 documento candidato" in body
    assert "Lei Complementar nº 120/2010" in body
    assert "Lei Complementar nº 120 /2010" not in body
    assert "LeiComplementar_120_2010.pdf" in body


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
    assert "<title>Normas e acervo — Jurix</title>" in body
    assert '<h1 id="normas-title" class="jurix-norma-title">Normas e acervo</h1>' in body
    assert 'placeholder="Número ou tema"' in body
    assert 'class="jurix-norma-stat-value">1<' in body
    assert 'class="jurix-norma-stat-label">normas consolidadas<' in body
    assert 'class="jurix-norma-stat-label">resultados<' in body


def test_norma_search_surfaces_sapl_metadata_separately_from_consolidated_law():
    Norma.objects.create(
        tipo="Lei",
        numero="8206",
        ano=2026,
        status="pending",
        ementa="Institui programa municipal de educação.",
        sapl_id=9387,
        sapl_url="https://sapl.natal.rn.leg.br/norma/9387",
        sapl_metadata={
            "_jurix_source_hash": "qa-catalog-hash",
            "_jurix_type_catalog": {
                "raw_code": "1",
                "raw_label": "LEI ORDINÁRIA",
                "type_key": "lei",
                "known": True,
            },
        },
    )

    response = Client().get("/normas/?q=8206")

    assert response.status_code == 200
    body = response.content.decode()
    assert 'class="jurix-norma-stat-value">0<' in body
    assert "normas consolidadas" in body
    assert "Referências encontradas no SAPL" in body
    assert "Lei Ordinária nº 8206/2026" in body
    assert "Ementa registrada no SAPL" in body
    assert "texto não integrado" in body
    assert "não comprovam o conteúdo integral" in body.casefold()
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387"' in body
    assert 'href="/normas/1/"' not in body


def test_explore_page_explains_empty_reviewed_graph_without_promoting_archive_candidates():
    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True, NORMATIVE_GRAPH_ENABLED=True):
        response = Client().get("/explorar/")

    body = response.content.decode()
    assert response.status_code == 200
    assert "Nenhuma norma consolidada disponível para explorar." in body
    assert "PDFs em revisão" in body
    assert "Buscar no acervo local" in body
    assert 'aria-label="Filtrar normas para exploração"' not in body


def test_pgm_consolidation_preview_is_hidden_when_qa_flag_is_disabled():
    with override_settings(DEBUG=True, PGM_CONSOLIDATION_DEMO_ENABLED=False):
        response = Client().get("/explorar/demo-consolidacao/")

    assert response.status_code == 404


def test_pgm_consolidation_preview_entry_point_requires_explicit_qa_flag():
    with override_settings(
        DEBUG=True,
        NORMATIVE_GRAPH_ENABLED=True,
        PGM_CONSOLIDATION_DEMO_ENABLED=True,
    ):
        response = Client().get("/explorar/")

    assert response.status_code == 200
    assert b"demo-consolidacao/" in response.content
    assert b"/explorar/demo-consolidacao/" in response.content
    assert "sete referências expressas de revogação" in response.content.decode()
    assert "Abrir grafo demonstrativo da LC 258/2024" in response.content.decode()
    assert "relação entre dois PDFs candidatos" not in response.content.decode()


def test_pgm_case_sapl_snapshot_keeps_exact_mismatch_duplicate_and_unchecked_distinct():
    with override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api"):
        exact = _pgm_lc258_sapl_registry_evidence("4885", 1997, "lei")
        type_conflict = _pgm_lc258_sapl_registry_evidence("1894", 1969, "lei_complementar")
        duplicate = _pgm_lc258_sapl_registry_evidence("562", 2018, "lei_promulgada")
        mismatch = _pgm_lc258_sapl_registry_evidence("198", 2021, "lei")
        unchecked = _pgm_lc258_sapl_registry_evidence("4566", 1992, "lei")

    assert exact["status"] == "exact_identity_candidate"
    assert exact["records"][0]["url"] == "https://sapl.natal.rn.leg.br/norma/6817"
    assert type_conflict["status"] == "species_conflict"
    assert type_conflict["records"][0]["type_display"] == "Lei Ordinária"
    assert duplicate["status"] == "ambiguous"
    assert {row["sapl_id"] for row in duplicate["records"]} == {254, 9202}
    assert mismatch["status"] == "species_conflict"
    assert mismatch["records"][0]["type_display"] == "Lei Complementar"
    assert unchecked["status"] == "not_checked"
    assert unchecked["records"] == []


def test_pgm_repeal_graph_parser_extracts_each_roman_reference_without_merging_items():
    article = """Art. 260. Ficam revogados:
I - Lei Complementar nº 1.894 de 31 de dezembro de 1969;
II - Lei nº 4.566 de 19 de maio de 1992;
III - Lei nº 4.885 de 07 de outubro de 1997;
IV - Lei Complementar nº 055 de 27 de janeiro de 2004;
V - Art. 21 da Lei Promulgada nº 275 de 12 de março de 2009;
VI - Lei Promulgada nº 562 de 14 de setembro de 2018;
VII - Lei nº 198 de 12 de novembro de 2021.
Art. 261. Próximo dispositivo."""
    source_match, references = _parse_repeal_candidates(article)

    assert source_match is not None
    assert [roman for roman, _ in references] == ["I", "II", "III", "IV", "V", "VI", "VII"]
    assert references[4][1].startswith("Art. 21 da Lei Promulgada nº 275")
    assert references[6][1] == "Lei nº 198 de 12 de novembro de 2021"


def test_explore_filters_confirmed_topics_and_publication_dates(norma):
    norma.data_publicacao = "2026-04-10"
    norma.ementa = "Programa municipal de educação popular"
    norma.save(update_fields=["data_publicacao", "ementa", "updated_at"])
    topic_code = f"educacao-pgm-test-{uuid4().hex}"
    topic = Topic.objects.create(code=topic_code, label="Educação")
    NormaTopic.objects.create(
        norma=norma,
        topic=topic,
        origin=NormaTopic.Origin.MANUAL,
        status=NormaTopic.Status.CONFIRMED,
    )

    client = Client()
    matching = client.get(f"/explorar/?tema={topic_code}&de=2026-04-01&ate=2026-04-30")
    outside_range = client.get(f"/explorar/?tema={topic_code}&de=2026-05-01")
    invalid_range = client.get("/explorar/?de=2026-05-01&ate=2026-04-01")

    assert matching.status_code == 200 and b"Lei" in matching.content and b"123/2026" in matching.content
    assert b"0 normas" in outside_range.content
    assert "A data inicial não pode ser posterior" in invalid_range.content.decode()
    assert b"123/2026" not in invalid_range.content


def test_explore_resolves_explicit_norm_identity_without_cross_type_or_year_matches(norma):
    norma.numero = "198"
    norma.tipo = "Lei Complementar"
    norma.ano = 2021
    norma.save(update_fields=["numero", "tipo", "ano", "updated_at"])
    Norma.objects.create(tipo="Lei", numero="198", ano=2021, status="consolidated")
    Norma.objects.create(tipo="Lei Complementar", numero="198", ano=2020, status="consolidated")

    response = Client().get("/explorar/?q=Lei+Complementar+198%2F2021")
    body = response.content.decode()

    assert response.status_code == 200
    assert "1 norma" in body
    assert "Lei Complementar nº 198/2021" in body
    assert "Lei nº 198/2021" not in body
    assert "Lei Complementar nº 198/2020" not in body


def test_explore_selection_uses_only_consolidated_norms_and_reuses_public_graph(norma):
    candidate = Norma.objects.create(tipo="Lei", numero="124", ano=2026, status="pending")
    client = Client()
    with override_settings(NORMATIVE_GRAPH_ENABLED=True):
        selected = client.get(f"/explorar/?norma={norma.pk}")
        hidden = client.get(f"/explorar/?norma={candidate.pk}")

    assert selected.status_code == 200
    assert f"data-api-url=\"/api/v1/normas/{norma.pk}/relations/\"" in selected.content.decode()
    assert "Norma selecionada" in selected.content.decode()
    assert "Norma selecionada" not in hidden.content.decode()
    assert "124/2026" not in hidden.content.decode()


def test_explore_candidate_relations_are_staff_only_and_preserve_source_scope(norma):
    candidate = Norma.objects.create(tipo="Lei", numero="991234", ano=2095, status="pending")
    document = DocumentoNormativo.objects.create(
        document_key=uuid4().hex,
        norma=candidate,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="jurix-qa:candidate-relations:991234-2095",
        original_filename="[QA] candidato.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        content_sha256="a" * 64,
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    candidate.documento_base = document
    candidate.save(update_fields=["documento_base", "updated_at"])
    source_device = Dispositivo.objects.create(
        norma=candidate,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="[QA] texto de evidência candidata",
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        acao="ALTERA",
        target_text="[QA] referência a norma existente",
        norma_alvo=norma,
        evidence_json={"quote": "[QA] evidência não revisada", "page": 1},
        target_reference_json={"synthetic_candidate": True},
    )

    with override_settings(NORMATIVE_GRAPH_ENABLED=True):
        anonymous = Client().get("/explorar/?escopo=candidatas")
        public = Client().get("/explorar/")
        denied_user = get_user_model().objects.create_user(
            username=f"candidate-review-partial-{uuid4().hex}",
            password="qa-password",
            is_staff=True,
        )
        denied_user.user_permissions.add(
            Permission.objects.get(content_type__app_label="legislation", codename="view_eventoalteracao")
        )
        denied_client = Client()
        denied_client.force_login(denied_user)
        missing_document_permission = denied_client.get("/explorar/?escopo=candidatas")

        reviewer = get_user_model().objects.create_user(
            username=f"candidate-review-{uuid4().hex}",
            password="qa-password",
            is_staff=True,
        )
        reviewer.user_permissions.add(
            Permission.objects.get(content_type__app_label="legislation", codename="view_eventoalteracao"),
            Permission.objects.get(content_type__app_label="legislation", codename="view_documentonormativo"),
        )
        reviewer_client = Client()
        reviewer_client.force_login(reviewer)
        reviewed_candidates = reviewer_client.get(f"/explorar/?escopo=candidatas&norma={candidate.pk}")

    assert anonymous.status_code == 403
    assert missing_document_permission.status_code == 403
    assert public.status_code == 200
    assert "991234/2095" not in public.content.decode()
    body = reviewed_candidates.content.decode()
    assert reviewed_candidates.status_code == 200
    assert "Modo restrito a revisores" in body
    assert "não comprova" in body
    assert "Fonte selecionada para revisão" in body
    assert "Relações extraídas · confira o status" in body
    assert f'data-api-url="/api/v1/normas/{candidate.pk}/relations/?include_pending=true"' in body
    assert f'href="/normas/documentos/{document.public_id}/"' in body
    assert f'href="/normas/{candidate.pk}/"' not in body


def test_explore_paginates_reviewed_norm_list(norma):
    Norma.objects.bulk_create([
        Norma(tipo="Lei", numero=f"{index:04}", ano=2020, status="consolidated")
        for index in range(20)
    ])

    first = Client().get("/explorar/")
    second = Client().get("/explorar/?page=2")

    assert first.status_code == second.status_code == 200
    assert "Página 1 de 2" in first.content.decode()
    assert "Página 2 de 2" in second.content.decode()
    assert first.content.count(b"class=\"workspace-result-card explore-norm-card\"") == 20


def test_norma_list_hides_explicit_qa_only_consolidated_fixtures(norma):
    norma.numero = "9917"
    norma.ano = 2090
    norma.identity_json = {"synthetic_fixture": True}
    norma.ementa = "[QA SINTÉTICO — NÃO É LEGISLAÇÃO REAL] Fixture de coleção."
    norma.save(update_fields=["numero", "ano", "identity_json", "ementa", "updated_at"])

    body = Client().get("/normas/").content.decode()

    assert "Lei 9917/2090" not in body
    assert "[QA SINTÉTICO" not in body
    assert 'class="jurix-norma-stat-value">0<' in body


def test_workspace_norma_count_excludes_synthetic_collection_fixture(norma):
    norma.identity_json = {"synthetic_fixture": True}
    norma.save(update_fields=["identity_json", "updated_at"])

    collections_body = Client().get("/colecoes/").content.decode()
    settings_body = Client().get("/configuracoes/").content.decode()

    assert "1 normas no acervo" not in collections_body
    assert "0 consolidadas" in settings_body
    assert "PDF local" not in settings_body


def test_exact_search_does_not_surface_synthetic_consolidated_fixture(norma):
    norma.numero = "9917"
    norma.ano = 2090
    norma.identity_json = {"synthetic_fixture": True}
    norma.ementa = "[QA SINTÉTICO — NÃO É LEGISLAÇÃO REAL] Fixture de coleção."
    norma.save(update_fields=["numero", "ano", "identity_json", "ementa", "updated_at"])

    body = Client().get("/pesquisa/?q=Lei+9917%2F2090").content.decode()

    assert "Nenhum texto pesquisável localizado para esta referência" in body
    assert "A busca também não examina arquivos fora do staging." in body
    assert "[QA SINTÉTICO" not in body


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
    for index in range(40):
        DocumentoNormativo.objects.create(
            document_key=str(index + 1).zfill(64),
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            source_ref=f"archive:qa-fixture:entry:{10000 + index}",
            entry_index=10000 + index,
            original_filename=f"candidate-{index}.pdf",
            content_sha256=str(index + 1001).zfill(64),
            metadata_json={"identity_candidate": {"type": "lei", "number": str(index + 1), "year": 2020}},
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
        )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=False):
        production_body = Client().get("/normas/").content.decode()
    assert "Documentos para consolidação" not in production_body
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        body = Client().get("/normas/").content.decode()
        queried_body = Client().get("/normas/", {"q": "120/2010"}).content.decode()
        typed_year_query = Client().get(
            "/normas/",
            {"q": "LC 258/2024", "tipo": "Lei Complementar", "ano": "2024"},
        ).content.decode()

    assert "Documentos para consolidação" in body
    assert '<h1 id="normas-title" class="jurix-norma-title">Normas e acervo</h1>' in body
    assert "Nenhuma norma consolidada disponível" in body
    assert "Lei Complementar nº 198/2021" in body
    assert "não equivalem a redações consolidadas ou vigentes" in body
    assert "Estes documentos compõem o acervo histórico local e estão disponíveis para consulta." in body
    assert "Ainda não foram consolidados no corpus principal" in body
    assert "Identidade candidata reconhecida; falta revisão humana." in body
    assert 'id="archive-candidate-search"' in body
    assert 'id="archive-global-search"' in body
    assert "Pesquisar em todo o acervo histórico" in body
    assert 'href="/pesquisa/?q="' in body
    assert 'href="/pesquisa/?q=120/2010"' in queried_body
    assert 'id="archive-global-search-top"' in queried_body
    assert 'href="/pesquisa/?q=120/2010"' in queried_body
    assert "A busca acima não pesquisa o texto integral destes PDFs." in queried_body
    assert (
        'href="/pesquisa/?q=LC%20258/2024&amp;arquivo_tipo=Lei%20Complementar&amp;arquivo_ano=2024"'
        in typed_year_query
    )
    assert 'id="archive-candidate-identity"' in body
    assert 'id="archive-candidate-extraction"' in body
    assert 'data-identity="resolved"' in body
    assert 'data-review-status="pending"' in body
    assert 'data-extraction-status="complete"' in body
    assert "Extração completa · 1 página · segmentação de dispositivos pendente" in body
    assert "PDF candidato" in body
    assert "PDF · entrada" not in body
    assert "PDF · entrada 9876" not in body
    assert "40 exibidos · 41 no acervo" in body
    assert "Exibindo 1–40 de 41 documentos pendentes." in body
    assert 'aria-label="Paginação dos documentos candidatos"' in body
    assert "Página 1 de 2" in body
    assert "arquivo_pagina=2#archive-candidates" in body
    assert 'id="archive-candidates-list" data-total-candidates="41"' in body

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        no_match = Client().get("/normas/?q=parcelamento+do+solo").content.decode()
    assert 'value="parcelamento do solo"' in no_match
    assert 'id="archive-global-search-top"' in no_match
    assert 'href="/pesquisa/?q=parcelamento%20do%20solo"' in no_match
    # This page's client-side filter covers only the first 40; keep the CTA to
    # the complete archive even when the visible subset has no matching item.
    assert 'href="/pesquisa/?q=parcelamento%20do%20solo"' in no_match
    assert (
        'class="jurix-norma-primary-button jurix-archive-global-search" id="archive-global-search"'
        in no_match
    )
    assert "Nenhuma norma consolidada corresponde aos filtros" in no_match
    assert "Não encontramos normas consolidadas para os filtros atuais." in no_match

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        show_all_candidates = Client().get("/normas/").content.decode()
    assert 'id="archive-candidate-search"' in show_all_candidates
    assert 'id="archive-candidate-search" type="search" autocomplete="off" spellcheck="false"\n                    value=""' in show_all_candidates
    assert "Exibindo 1–40 de 41 documentos pendentes." in show_all_candidates

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        second_candidate_page = Client().get("/normas/?arquivo_pagina=2#archive-candidates").content.decode()
    assert "Exibindo 41–41 de 41 documentos pendentes." in second_candidate_page
    assert "Página 2 de 2" in second_candidate_page
    assert "candidate-39.pdf" in second_candidate_page
    assert "Lei Complementar nº 198/2021" not in second_candidate_page
    assert "arquivo_pagina=1#archive-candidates" in second_candidate_page

    with override_settings(
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
    ):
        collections_body = Client().get("/colecoes/").content.decode()
        settings_body = Client().get("/configuracoes/").content.decode()

    assert "41 PDFs locais em revisão" in collections_body, [
        line.strip() for line in collections_body.splitlines() if "PDF" in line
    ]
    assert "41 PDFs locais em revisão" in settings_body
    assert "normas consolidadas" in collections_body
    assert 'href="/normas/#archive-candidates"' in settings_body
    assert "Perguntar ao assistente sobre o acervo" in collections_body


def test_norma_list_surfaces_dom_editions_only_in_qa_and_validates_official_pdf_url():
    valid_url = (
        "https://www2.natal.rn.gov.br/_anexos/publicacao/dom/"
        "dom_20261001_0123456789abcdef01234567.pdf"
    )
    DocumentoNormativo.objects.create(
        document_key="e" * 64,
        source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
        source_ref="dom_natal:2026:6206",
        original_filename="dom_20261001_0123456789abcdef01234567.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        storage_key="qa/dom/candidate.pdf",
        content_sha256="f" * 64,
        official_url=valid_url,
        metadata_json={
            "label": "DOM nº 6.206 — 1º de outubro de 2026",
            "publication_date": "2026-10-01",
            "special_edition": False,
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=False):
        hidden_body = Client().get("/normas/").content.decode()
    assert "Edições para revisão" not in hidden_body
    assert valid_url not in hidden_body

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        body = Client().get("/normas/").content.decode()
    assert "Edições para revisão" in body
    assert "DOM nº 6.206 — 1º de outubro de 2026" in body
    assert "Publicação: 01/10/2026" in body
    assert "Extração e identificação dos atos ainda não realizadas" in body
    assert "não são normas consolidadas" in body
    assert f'href="{valid_url}"' in body
    assert "Abrir PDF oficial" in body


def test_norma_list_never_links_untrusted_dom_pdf_url():
    DocumentoNormativo.objects.create(
        document_key="d" * 64,
        source_kind=DocumentoNormativo.SourceKind.OFFICIAL_GAZETTE,
        source_ref="dom_natal:unsafe:test",
        original_filename="external.pdf",
        role=DocumentoNormativo.Role.UNDETERMINED,
        storage_key="qa/dom/external.pdf",
        content_sha256="c" * 64,
        official_url="https://example.invalid/malicious.pdf",
        metadata_json={"label": "Edição com URL inválida", "publication_date": "2026-10-01"},
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        body = Client().get("/normas/").content.decode()

    assert "Edição com URL inválida" in body
    assert "Link oficial indisponível para validação." in body
    assert 'href="https://example.invalid/malicious.pdf"' not in body


def test_norma_list_rewrites_legacy_sapl_detail_url(norma):
    norma.sapl_id = 9387
    norma.sapl_url = "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/"
    norma.save(update_fields=["sapl_id", "sapl_url"])
    body = Client().get("/normas/").content.decode()
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387"' in body
    assert "/norma/normajuridica/9387/" not in body


def test_norma_detail_rewrites_legacy_sapl_url_without_mutating_the_record(norma):
    norma.sapl_id = 9387
    legacy = "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/"
    norma.sapl_url = legacy
    norma.save(update_fields=["sapl_id", "sapl_url"])
    response = Client().get(f"/normas/{norma.pk}/")
    body = response.content.decode()
    assert response.status_code == 200
    assert 'href="https://sapl.natal.rn.leg.br/norma/9387"' in body
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


def test_assistant_prefills_a_bounded_question_without_creating_a_session():
    question = "O que prevê o art. 18 da Lei Complementar nº 120/2010?"
    response = Client().get(
        "/assistente/",
        {"new": "1", "corpus": "archive-qa", "question": question},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert question in body
    assert f'value="{question}"' in body
    assert ChatSession.objects.count() == 0


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


def test_empty_search_offers_separate_review_archive_search(monkeypatch):
    document = DocumentoNormativo.objects.create(
        document_key="e" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:4321",
        archive_sha256="f" * 64,
        entry_index=4321,
        entry_name="fixture/Lei_4321.pdf",
        original_filename="Lei_4321.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key="sha256/ee/ff/fixture.pdf",
        size_bytes=321,
        content_sha256="a" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="pymupdf-qa-test",
        policy_fingerprint="f" * 64,
        text_version="technical_text_v1",
        legal_text="O vencimento básico será calculado conforme a regra do município.",
        page_count=1,
        status=ExtracaoDocumento.Status.COMPLETE,
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_ASSISTANT_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get("/pesquisa/", {"q": "vencimento básico"})

    body = response.content.decode()
    assert response.status_code == 200
    assert response.context[0]["archive_search_available"] is True
    assert 'class="workspace-archive-search-summary" role="status"' in body
    assert "1 PDF candidato no acervo local" in body
    assert 'href="#workspace-archive-results-title">Ver PDFs candidatos</a>' in body
    assert "PDFs locais ainda estão em revisão" in body
    assert (
        'href="/assistente/?new=1&amp;corpus=archive-qa&amp;question=vencimento%20b%C3%A1sico"'
        in body
    )
    assert 'href="/normas/#archive-candidates"' in body


def test_archive_candidate_hit_is_not_presented_only_as_semantic_miss(monkeypatch):
    DocumentoNormativo.objects.create(
        document_key="b" * 64,
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:qa-fixture:entry:2582024",
        archive_sha256="c" * 64,
        entry_index=2582024,
        entry_name="fixture/LeiComplementar_20241227_258_.pdf",
        original_filename="LeiComplementar_20241227_258_.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        storage_key="sha256/bb/cc/candidate.pdf",
        size_bytes=321,
        content_sha256="d" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_status": "candidate",
            "identity_candidate": {"type": "lei_complementar", "number": "258", "year": 2024},
        },
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {"results": [], "mode": "semantic"}

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        response = Client().get("/pesquisa/", {"q": "258/2024"})

    body = response.content.decode()
    assert response.status_code == 200
    assert "0 resultados consolidados" in body
    assert "Nenhuma norma consolidada para esta consulta" in body
    assert "A busca encontrou 1 PDF candidato no acervo histórico, exibidos abaixo" in body
    assert "Nenhuma correspondência semântica encontrada" not in body
    assert "LeiComplementar_20241227_258_.pdf" in body
    assert "Eles permanecem pendentes de revisão" in body

    with override_settings(
        DEBUG=True,
        NORMATIVE_ARCHIVE_ENABLED=True,
        NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True,
    ):
        filtered_response = Client().get(
            "/pesquisa/",
            {
                "q": "258/2024",
                "arquivo_tipo": "Lei Complementar",
                "arquivo_ano": "2024",
                "arquivo_revisao": "pending",
            },
        )
    filtered_body = filtered_response.content.decode()
    assert filtered_response.status_code == 200
    assert 'aria-label="Filtros aplicados aos PDFs locais"' in filtered_body
    assert "Espécie: Lei Complementar" in filtered_body
    assert "Ano: 2024" in filtered_body
    assert "Revisão: Pendente" in filtered_body


def test_legal_search_never_presents_synthetic_qa_norms_as_product_results(norma, monkeypatch):
    norma.identity_json = {"synthetic_fixture": True}
    norma.save(update_fields=["identity_json", "updated_at"])
    device = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="plano de cargos sintético para QA",
    )

    class FakeRAG:
        def semantic_search(self, **kwargs):
            return {
                "results": [{"dispositivo": device, "similarity_score": 0.99, "context": {}}],
                "mode": "semantic",
            }

    monkeypatch.setattr("src.apps.legislation.workspace_views.RAGService", FakeRAG)
    response = Client().get("/pesquisa/", {"q": "plano de cargos"})

    assert response.status_code == 200
    assert b"0 resultados consolidados" in response.content
    assert f"/normas/{norma.pk}/".encode() not in response.content
    assert b"Fixture sint\xc3\xa9tica de QA" not in response.content


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
    assert response.context["exact_reference_not_found"] is True
    body = response.content.decode("utf-8").lower()
    assert "nenhum texto pesquisável localizado para esta referência" in body
    assert "isso não prova que a norma inexista" in body
    assert "consultar acervo normativo e catálogo sapl" in body
    assert f"/normas/{other_year.pk}/".encode() not in response.content
