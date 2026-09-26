# ruff: noqa: F401,F403,E501,E701,I001
from __future__ import annotations

import json
import logging
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, OuterRef, Q, Subquery
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from src.apps.legislation.api_limits import (
    InvalidLLMParams,
    parse_k,
    parse_llm_request,
    parse_model,
    rate_limit_response,
)
from src.apps.legislation.attachment_service import (
    AttachmentError,
    delete_attachment,
    list_attachments,
    upload_attachment,
)
from src.apps.legislation.chat_api_helpers import _chat_session_response, _parse_limit, _preview
from src.apps.legislation.models import (
    ChatMessage,
    ChatSession,
    Dispositivo,
    EventoAlteracao,
    Norma,
)
from src.apps.legislation.retrieval_api import build_retrieval_options
from src.apps.legislation.serializers import serialize_chat_session, serialize_dispositivo_source
from src.apps.legislation.suggestion_service import build_dynamic_suggestions
from src.processing.adaptive_rag_service import AdaptiveRAGService

RAGService = AdaptiveRAGService
from .api_health import _format_error_message, _server_error

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def chat_attachment_api(request: HttpRequest) -> JsonResponse:
    """List or upload temporary, session-bound chat documents."""
    limited = rate_limit_response(request, scope="attachment")
    if limited:
        return limited
    if request.method == "GET":
        return JsonResponse({"success": True, "attachments": list_attachments(request)})

    upload = request.FILES.get("file")
    if upload is None:
        return JsonResponse({"success": False, "error": "Arquivo não enviado."}, status=400)
    try:
        item = upload_attachment(request, upload)
    except AttachmentError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except Exception as exc:
        logger.error("Attachment upload failed", exc_info=True)
        return JsonResponse({"success": False, "error": _format_error_message(exc)}, status=500)
    return JsonResponse(
        {"success": True, "attachment": item, "attachments": list_attachments(request)}
    )


@require_http_methods(["DELETE"])
def chat_attachment_detail_api(request: HttpRequest, attachment_id: str) -> JsonResponse:
    """Delete one temporary session-bound chat document."""
    limited = rate_limit_response(request, scope="attachment")
    if limited:
        return limited
    if not delete_attachment(request, attachment_id):
        return JsonResponse({"success": False, "error": "Documento não encontrado."}, status=404)
    return JsonResponse({"success": True, "attachments": list_attachments(request)})


@require_http_methods(["GET"])
def dynamic_suggestions_api(request: HttpRequest) -> JsonResponse:
    """Return suggestion cards generated from the current municipal corpus."""
    limited = rate_limit_response(request, scope="suggestions")
    if limited:
        return limited
    try:
        limit = max(1, min(int(request.GET.get("limit", 4)), 8))
    except (TypeError, ValueError):
        limit = 4
    try:
        suggestions = build_dynamic_suggestions(limit)
        response = JsonResponse(
            {
                "success": True,
                "suggestions": suggestions,
                "count": len(suggestions),
                "source": "municipal_natal_corpus",
            }
        )
        response["Cache-Control"] = "private, max-age=120, stale-while-revalidate=300"
        response["X-Jurix-Suggestion-Source"] = "corpus"
        return response
    except Exception as exc:
        logger.error("Dynamic suggestion generation failed: %s", exc, exc_info=True)
        return JsonResponse(
            {
                "success": False,
                "error": "Não foi possível carregar sugestões do corpus.",
                "suggestions": [],
            },
            status=500,
        )
