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
]

