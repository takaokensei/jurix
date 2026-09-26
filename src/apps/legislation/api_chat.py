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
from src.apps.legislation.api_limits import InvalidLLMParams, parse_k, parse_llm_request, parse_model, rate_limit_response
from src.apps.legislation.attachment_service import AttachmentError, delete_attachment, list_attachments, upload_attachment
from src.apps.legislation.chat_api_helpers import _chat_session_response, _parse_limit, _preview
from src.apps.legislation.models import ChatMessage, ChatSession, Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.retrieval_api import build_retrieval_options
from src.apps.legislation.serializers import serialize_chat_session, serialize_dispositivo_source
from src.apps.legislation.suggestion_service import build_dynamic_suggestions
from src.processing.adaptive_rag_service import AdaptiveRAGService
RAGService = AdaptiveRAGService

logger = logging.getLogger(__name__)

@require_http_methods(["GET", "POST"])
def chat_sessions_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for chat sessions management.

    GET /api/v1/chat/sessions/ - List sessions of the authenticated user
    POST /api/v1/chat/sessions/ - Create new session
    """
    if not request.user.is_authenticated:
        # Guest history is intentionally stored by the browser. Returning an
        # empty collection prevents every refresh from producing an expected
        # but noisy 401 while retaining the strict auth boundary for DB data.
        return JsonResponse({"success": True, "sessions": []})

    try:
        if request.method == "GET":
            latest_user_message = (
                ChatMessage.objects.filter(session=OuterRef("pk"), role="user")
                .order_by("-created_at", "-id")
                .values("content")[:1]
            )
            # Count and latest-question preview come from the same query: no N+1.
            sessions = (
                ChatSession.objects.filter(user=request.user)
                .annotate(
                    message_count=Count("messages"),
                    latest_user_content=Subquery(latest_user_message),
                )
                .order_by("-updated_at", "-id")[: _parse_limit(request.GET.get("limit"))]
            )
            sessions_data = []
            for session in sessions:
                item = serialize_chat_session(session)
                item["message_count"] = session.message_count
                item["latest_message_preview"] = _preview(session.latest_user_content)
                sessions_data.append(item)
            return JsonResponse(
                {"success": True, "sessions": sessions_data, "count": len(sessions_data)}
            )

        # POST
        data = json.loads(request.body) if request.body else {}
        title = data.get("title", "Nova Conversa") if isinstance(data, dict) else None
        if not isinstance(title, str):
            return JsonResponse({"success": False, "error": "Invalid title"}, status=400)

        ChatSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
        session = ChatSession.objects.create(user=request.user, title=title[:200], is_active=True)
        return JsonResponse(
            {"success": True, "session": serialize_chat_session(session)}, status=201
        )
    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    except Exception as e:
        return _server_error("chat sessions API", e)

@require_http_methods(["GET"])
def chat_session_by_slug_api(request: HttpRequest, slug: str) -> JsonResponse:
    """
    API endpoint to get a chat session by slug.
    GET /api/v1/chat/sessions/slug/<slug>/
    Same response as chat_session_detail_api, addressed by slug instead of ID.
    """
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)

    try:
        session = ChatSession.objects.get(slug=slug, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({"success": False, "error": "Session not found"}, status=404)

    try:
        return _chat_session_response(session, request.GET.get("before"))
    except Exception as e:
        return _server_error("chat session by slug API", e)

@require_http_methods(["GET", "DELETE"])
def chat_session_detail_api(request: HttpRequest, session_id: int) -> JsonResponse:
    """API endpoint for single chat session operations (GET detail, DELETE)."""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)

    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({"success": False, "error": "Session not found"}, status=404)

    try:
        if request.method == "DELETE":
            session.delete()
            return JsonResponse({"success": True, "message": "Session deleted"})
        return _chat_session_response(session, request.GET.get("before"))
    except Exception as e:
        return _server_error("chat session detail API", e)

@require_http_methods(["POST"])
def chat_session_regenerate_api(request: HttpRequest, session_id: int) -> JsonResponse:
    """API endpoint to regenerate the last assistant response."""
    if not request.user.is_authenticated:
        return JsonResponse({"success": False, "error": "Authentication required"}, status=401)

    limited = rate_limit_response(request)
    if limited:
        return limited

    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({"success": False, "error": "Session not found"}, status=404)

    try:
        data = json.loads(request.body) if request.body else {}
        if not isinstance(data, dict):
            raise InvalidLLMParams("Corpo da requisição inválido.")
        k = parse_k(data.get("k"))
        model = parse_model(data.get("model"))
    except InvalidLLMParams as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid request body"}, status=400)

    try:
        # Use direct query instead of related manager
        last_user_msg = (
            ChatMessage.objects.filter(session_id=session.id, role="user")
            .order_by("-created_at")
            .first()
        )
        if not last_user_msg:
            return JsonResponse(
                {"success": False, "error": "No user message found to regenerate"}, status=400
            )

        last_assistant = (
            ChatMessage.objects.filter(session_id=session.id, role="assistant")
            .order_by("-created_at")
            .first()
        )

        # Generate new answer FIRST before touching database state (force refresh cache)
        rag_service = RAGService()
        response = rag_service.answer_question(
            question=last_user_msg.content, k=k, model=model, force_refresh=True
        )

        # Only after generation succeeds, delete previous assistant response
        if last_assistant:
            last_assistant.delete()

        sources = []
        for source in response.get("sources", []):
            disp = source["dispositivo"]
            similarity = source.get("similarity_score", 0.0)
            similarity_score = max(
                0.0, min(1.0, float(similarity) if similarity is not None else 0.0)
            )
            norma = disp.norma

            sources.append(
                {
                    "id": disp.id,
                    "text": disp.texto[:200] + ("..." if len(disp.texto) > 200 else ""),
                    "full_text": disp.texto,
                    "similarity_score": similarity_score,
                    "distance": float(source.get("distance", 1.0)),
                    "norma_ref": f"{norma.tipo} {norma.numero}/{norma.ano}",
                    "norma_id": norma.id,
                    "dispositivo_ref": disp.get_full_identifier(),
                    "hierarchy": source.get("context", {}).get("hierarchy", ""),
                    "pdf_url": norma.pdf_url if norma.pdf_url else None,
                    "sapl_url": norma.sapl_url if norma.sapl_url else None,
                    "dispositivo_id": disp.id,
                }
            )

        ChatMessage.objects.create(
            session=session,
            role="assistant",
            content=response["answer"],
            sources_json=sources,
            metadata_json={
                "model": response.get("model", model),
                "confidence": response.get("confidence", 0.0),
                "context_length": response.get("context_length", 0),
                "sources_count": len(sources),
            },
        )

        return JsonResponse(
            {
                "success": True,
                "answer": response["answer"],
                "sources": sources,
                "confidence": response["confidence"],
                "metadata": {
                    "model": response.get("model", model),
                    "context_length": response.get("context_length", 0),
                    "sources_count": len(sources),
                },
            }
        )

    except json.JSONDecodeError:
        return JsonResponse({"success": False, "error": "Invalid JSON"}, status=400)
    except Exception as e:
        logger.error(f"Error in chat session regenerate API: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": _format_error_message(e)}, status=500)
