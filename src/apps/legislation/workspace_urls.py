"""Top-level workspace routes for the Jurix product shell."""

from django.urls import path

from . import pilot_views, workspace_views

app_name = "workspace"

urlpatterns = [
    path("conta/entrar/", workspace_views.workspace_login_view, name="login"),
    path("conta/sair/", workspace_views.workspace_logout_view, name="logout"),
    path("assistente/", workspace_views.assistente_view, name="assistant"),
    path(
        "assistente/<str:session_slug>/", workspace_views.assistente_view, name="assistant_session"
    ),
    path("configuracoes/", workspace_views.settings_view, name="settings"),
    path("pesquisa/", workspace_views.legal_search_view, name="legal_search"),
    path("explorar/", workspace_views.explore_normative_graph_view, name="explore"),
    path("explorar/piloto/", pilot_views.casefile_view, name="pilot_casefile"),
    path("explorar/fontes/<str:pdf_sha256>/", pilot_views.source_pdf_view, name="pilot_source_pdf"),
    path(
        "explorar/adocoes-ia/",
        workspace_views.ai_pilot_adoptions_view,
        name="ai_pilot_adoptions",
    ),
    path(
        "explorar/gold-standard/",
        workspace_views.pgm_project_gold_view,
        name="pgm_project_gold",
    ),
    path(
        "explorar/norma/<int:pk>/",
        workspace_views.normative_casefile_view,
        name="normative_casefile",
    ),
    path(
        "explorar/demo-consolidacao/",
        workspace_views.pgm_consolidation_demo_view,
        name="pgm_consolidation_demo",
    ),
    path("conferir/", workspace_views.foundation_check_view, name="foundation_check"),
    path(
        "conferir/status/<uuid:job_id>/",
        workspace_views.foundation_check_status_view,
        name="foundation_check_status",
    ),
    path(
        "conferir/resultado/<uuid:job_id>/",
        workspace_views.foundation_check_result_view,
        name="foundation_check_result",
    ),
    path(
        "conferir/<uuid:job_id>/cancelar/",
        workspace_views.foundation_check_cancel_view,
        name="foundation_check_cancel",
    ),
    path("colecoes/", workspace_views.collections_view, name="collections"),
    path("colecoes/<int:pk>/", workspace_views.collection_detail_view, name="collection_detail"),
    path("historico/", workspace_views.history_view, name="history"),
]
