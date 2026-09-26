# ruff: noqa: F401,F403,E501,E701
"""Stable API view import surface.

The endpoint implementations are grouped by concern. Wrappers synchronize the
legacy module globals before delegation so existing tests and integrations that
patch ``api_views`` symbols keep working.
"""

from __future__ import annotations

from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import api_attachments, api_chat, api_health, api_normas, api_search
from .api_attachments import *  # noqa: F401,F403
from .api_attachments import (
    chat_attachment_api,
    chat_attachment_detail_api,
    dynamic_suggestions_api,
)
from .api_chat import *  # noqa: F401,F403
from .api_chat import (
    chat_session_by_slug_api,
    chat_session_detail_api,
    chat_session_regenerate_api,
    chat_sessions_api,
)
from .api_health import *  # noqa: F401,F403
from .api_health import (
    _check_database,
    _check_migrations,
    _check_ollama,
    _check_pgvector,
    _check_redis,
    _format_error_message,
    health_check_api,
    health_live_api,
    health_ready_api,
)
from .api_normas import *  # noqa: F401,F403
from .api_normas import norma_detail_api, norma_list_api
from .api_search import *  # noqa: F401,F403
from .chat_api_helpers import _chat_session_response


def _sync(module) -> None:
    for name in (
        "RAGService",
        "ChatMessage",
        "ChatSession",
        "Dispositivo",
        "EventoAlteracao",
        "Norma",
        "rate_limit_response",
        "parse_k",
        "parse_llm_request",
        "parse_model",
        "build_retrieval_options",
        "serialize_dispositivo_source",
        "transaction",
        "timezone",
        "InvalidLLMParams",
        "_format_error_message",
        "_chat_session_response",
        "_server_error",
        "_check_database",
        "_check_pgvector",
        "_check_redis",
        "_check_migrations",
        "_check_ollama",
        "list_attachments",
        "upload_attachment",
        "delete_attachment",
        "AttachmentError",
        "build_dynamic_suggestions",
        "_chat_session_response",
        "_parse_limit",
        "_preview",
    ):
        if name in globals():
            setattr(module, name, globals()[name])


def health_ready_api(request):
    _sync(api_health)
    return api_health.health_ready_api(request)


def health_check_api(request):
    _sync(api_health)
    return api_health.health_check_api(request)


def semantic_search_api(request):
    _sync(api_search)
    return api_search.semantic_search_api(request)


@require_http_methods(["GET", "POST"])
@csrf_exempt
def rag_answer_api(request):
    _sync(api_search)
    return api_search.rag_answer_api(request)


def chatbot_stream_api(request):
    _sync(api_search)
    return api_search.chatbot_stream_api(request)


def norma_list_api(request):
    _sync(api_normas)
    return api_normas.norma_list_api(request)


def norma_detail_api(request, pk):
    _sync(api_normas)
    return api_normas.norma_detail_api(request, pk)


def chat_sessions_api(request):
    _sync(api_chat)
    return api_chat.chat_sessions_api(request)


def chat_session_by_slug_api(request, slug):
    _sync(api_chat)
    return api_chat.chat_session_by_slug_api(request, slug)


def chat_session_detail_api(request, session_id):
    _sync(api_chat)
    return api_chat.chat_session_detail_api(request, session_id)


def chat_session_regenerate_api(request, session_id):
    _sync(api_chat)
    return api_chat.chat_session_regenerate_api(request, session_id)


def chat_attachment_api(request):
    _sync(api_attachments)
    return api_attachments.chat_attachment_api(request)


def chat_attachment_detail_api(request, attachment_id):
    _sync(api_attachments)
    return api_attachments.chat_attachment_detail_api(request, attachment_id)


def dynamic_suggestions_api(request):
    _sync(api_attachments)
    return api_attachments.dynamic_suggestions_api(request)
