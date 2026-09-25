"""Top-level workspace routes for the Jurix product shell."""

from django.urls import path

from . import workspace_views

app_name = "workspace"

urlpatterns = [
    path("assistente/", workspace_views.assistente_view, name="assistant"),
    path(
        "assistente/<str:session_slug>/", workspace_views.assistente_view, name="assistant_session"
    ),
    path("configuracoes/", workspace_views.settings_view, name="settings"),
    path("pesquisa/", workspace_views.legal_search_view, name="legal_search"),
    path("colecoes/", workspace_views.collections_view, name="collections"),
    path("historico/", workspace_views.history_view, name="history"),
]
