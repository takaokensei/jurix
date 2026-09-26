"""
API URL configuration for legislation app.

Provides RESTful API endpoints for:
- Semantic search
- RAG question answering
- Norma listing and retrieval
"""

from django.urls import path

from . import api_views, temporal_api

app_name = "legislation_api"

urlpatterns = [
    # Liveness/readiness probes.
    path(
        "health/live/",
        api_views.health_live_api,
        name="health_live",
    ),
    path("health/", api_views.health_ready_api, name="health_check"),
    path(
        "health/ready/",
        api_views.health_ready_api,
        name="health_ready",
    ),
    # Semantic search endpoint
    path("search/semantic/", api_views.semantic_search_api, name="semantic_search"),
    # RAG answer endpoint
    path("search/answer/", api_views.rag_answer_api, name="rag_answer"),
    path("search/answer/stream/", api_views.chatbot_stream_api, name="rag_answer_stream"),
    # Norma listing
    path("normas/", api_views.norma_list_api, name="norma_list"),
    path("suggestions/", api_views.dynamic_suggestions_api, name="dynamic_suggestions"),
    # Norma detail
    path("normas/<int:pk>/", api_views.norma_detail_api, name="norma_detail"),
    path("normas/<int:pk>/timeline/", temporal_api.norma_timeline_api, name="norma_timeline"),
    path("normas/<int:pk>/conflicts/", temporal_api.norma_conflicts_api, name="norma_conflicts"),
    # Chat sessions endpoints
    path("chat/sessions/", api_views.chat_sessions_api, name="chat_sessions"),
    path("chat/attachments/", api_views.chat_attachment_api, name="chat-attachments"),
    path(
        "chat/attachments/<str:attachment_id>/",
        api_views.chat_attachment_detail_api,
        name="chat-attachment-detail",
    ),
    path(
        "chat/sessions/<int:session_id>/",
        api_views.chat_session_detail_api,
        name="chat_session_detail",
    ),
    path(
        "chat/sessions/slug/<str:slug>/",
        api_views.chat_session_by_slug_api,
        name="chat_session_by_slug",
    ),
    path(
        "chat/sessions/<int:session_id>/regenerate/",
        api_views.chat_session_regenerate_api,
        name="chat_session_regenerate",
    ),
]
