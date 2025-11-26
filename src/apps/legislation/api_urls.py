"""
API URL configuration for legislation app.

Provides RESTful API endpoints for:
- Semantic search
- RAG question answering
- Norma listing and retrieval
"""

from django.urls import path
from . import api_views

app_name = 'legislation_api'

urlpatterns = [
    # Semantic search endpoint
    path(
        'search/semantic/',
        api_views.semantic_search_api,
        name='semantic_search'
    ),
    
    # RAG answer endpoint
    path(
        'search/answer/',
        api_views.rag_answer_api,
        name='rag_answer'
    ),
    
    # Norma listing
    path(
        'normas/',
        api_views.norma_list_api,
        name='norma_list'
    ),
    
    # Norma detail
    path(
        'normas/<int:pk>/',
        api_views.norma_detail_api,
        name='norma_detail'
    ),
    
    # Chat sessions endpoints
    path(
        'chat/sessions/',
        api_views.chat_sessions_api,
        name='chat_sessions'
    ),
    path(
        'chat/sessions/<int:session_id>/',
        api_views.chat_session_detail_api,
        name='chat_session_detail'
    ),
    path(
        'chat/sessions/slug/<str:slug>/',
        api_views.chat_session_by_slug_api,
        name='chat_session_by_slug'
    ),
    path(
        'chat/sessions/<int:session_id>/regenerate/',
        api_views.chat_session_regenerate_api,
        name='chat_session_regenerate'
    ),
]

