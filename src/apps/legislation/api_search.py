# ruff: noqa: F401,F403,E501,E701,I001
from __future__ import annotations

import json
import logging
import math
import re
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
    parse_question,
    parse_temperature,
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
from src.processing.llm_provider import validate_provider_config

RAGService = AdaptiveRAGService
from .api_health import _format_error_message, _server_error

logger = logging.getLogger(__name__)


_LAW_REFERENCE_RE = re.compile(
    r"\b(Lei(?:\s+Complementar)?|Decreto|Resolução|Portaria)\s*(?:n[º°o.]?\s*)?(\d{1,7})\s*/\s*(\d{4})\b",
    re.IGNORECASE,
)
_ARTICLE_FOLLOWUP_RE = re.compile(r"\b(?:e\s+)?(?:o\s+)?art(?:igo)?\.?\s*(\d{1,4})\s*[º°o]?\b", re.IGNORECASE)


def _resolve_article_followup(question: str, previous_question: str) -> str:
    """Carry only an explicit law citation into a short article follow-up."""
    if not previous_question or len(previous_question) > 10000:
        return question
    match = _ARTICLE_FOLLOWUP_RE.search(question)
    law = _LAW_REFERENCE_RE.search(previous_question)
    if not match or not law or _LAW_REFERENCE_RE.search(question):
        return question
    kind = " ".join(law.group(1).split())
    number, year = law.group(2), law.group(3)
    return f"O que prevê o art. {match.group(1)} da {kind} nº {number}/{year}?"


def _generate_local_conversation_title(question: str) -> str:
    """Generate a compact title with the configured local Ollama model; fail closed."""
    try:
        from src.llm_engine.ollama_service import OllamaService

        generated = OllamaService(model=settings.OLLAMA_MODEL).generate_text(
            prompt=(
                "Resuma o tema desta conversa jurídica em um título de 3 a 7 palavras, "
                "máximo 55 caracteres. Não repita a pergunta inteira. Responda somente o título.\n\n"
                f"Pergunta: {question[:1500]}"
            ),
            model=settings.OLLAMA_MODEL,
            temperature=0.2,
            max_tokens=32,
        )
        title = " ".join(str(generated or "").replace("\n", " ").strip(" \t\"'`.*#-").split())
        if title and len(title) <= 70:
            return title[:55].rstrip(" .,;:!?—-")
    except Exception:
        logger.info("Local conversation title generation unavailable", exc_info=True)
    # A concise fallback is preferable to repeating the same question as title and preview.
    reference = _LAW_REFERENCE_RE.search(question)
    remainder = question[reference.end():] if reference else question
    words = [word for word in re.findall(r"[\wÀ-ÿ]+", remainder) if word.casefold() not in {"o", "a", "os", "as", "que", "sobre", "prevê", "preve", "estabelece", "trata", "da", "do", "de", "um", "uma", "qual"}]
    topic = " ".join(words[:5]).strip()
    if reference and topic:
        kind = "Lei" if reference.group(1).casefold().startswith("lei") else reference.group(1)
        topic = f"{kind} {reference.group(2)}/{reference.group(3)} — {topic}"
    if not topic and reference:
        topic = f"{reference.group(1)} {reference.group(2)}/{reference.group(3)}"
    return topic[:55].rstrip(" .,;:!?—-") or "Pesquisa jurídica"


@require_http_methods(["GET"])
def semantic_search_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for semantic search using pgvector.

    GET /api/v1/search/semantic/?query=<text>&k=<int>&norma_id=<int>

    Query Parameters:
        - query (required): Search query text
        - k (optional): Number of results (default: 10, max: 50)
        - norma_id (optional): Filter by specific norma ID
        - min_similarity (optional): Minimum similarity score (0-1)

    Returns:
        JSON response with:
        - success: bool
        - query: str (original query)
        - results: list of dispositivos with similarity scores
        - count: int
        - metadata: dict with search parameters
    """
    limited = rate_limit_response(request)
    if limited:
        return limited

    try:
        # Extract query parameters
        try:
            query_text = parse_question(request.GET.get("query", ""))
        except InvalidLLMParams as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=400)

        if not query_text:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Query parameter is required",
                    "example": "/api/v1/search/semantic/?query=mudanca+de+zoneamento",
                },
                status=400,
            )

        # Parse optional parameters
        try:
            k = max(1, min(int(request.GET.get("k", 10)), 50))  # 1..50 results
        except ValueError:
            return JsonResponse(
                {"success": False, "error": "k deve ser um número inteiro."}, status=400
            )

        norma_id = request.GET.get("norma_id")
        if norma_id:
            try:
                norma_id = int(norma_id)
            except ValueError:
                return JsonResponse(
                    {"success": False, "error": "norma_id deve ser um número inteiro."},
                    status=400,
                )

        try:
            min_similarity = float(request.GET.get("min_similarity", 0.0))
            if not math.isfinite(min_similarity):
                raise ValueError
            min_similarity = max(0.0, min(1.0, min_similarity))  # Clamp to [0, 1]
        except ValueError:
            return JsonResponse(
                {"success": False, "error": "min_similarity deve ser um número."}, status=400
            )

        logger.info(
            f"API semantic search request: query='{query_text[:50]}...', "
            f"k={k}, norma_id={norma_id}, min_similarity={min_similarity}"
        )

        # Perform semantic search
        rag_service = RAGService()
        results = rag_service.semantic_search(
            query_text=query_text, k=k, norma_id=norma_id, min_similarity=min_similarity
        )

        # Format results for JSON response
        formatted_results = []
        for result in results:
            disp = result["dispositivo"]

            formatted_results.append(
                {
                    "id": disp.id,
                    "tipo": disp.tipo,
                    "numero": disp.numero,
                    "texto": disp.texto,
                    "ordem": disp.ordem,
                    "similarity_score": result["similarity_score"],
                    "distance": result["distance"],
                    "norma": {
                        "id": disp.norma.id,
                        "tipo": disp.norma.get_tipo_display_name(),
                        "numero": disp.norma.numero,
                        "ano": disp.norma.ano,
                        "ementa": disp.norma.ementa[:200] if disp.norma.ementa else None,
                    },
                    "hierarchy": result["context"]["hierarchy"],
                    "parent": result["context"]["parent"],
                    "embedding_model": result["embedding_model"],
                }
            )

        return JsonResponse(
            {
                "success": True,
                "query": query_text,
                "results": formatted_results,
                "count": len(formatted_results),
                "metadata": {
                    "k": k,
                    "norma_id": norma_id,
                    "min_similarity": min_similarity,
                    "model": settings.OLLAMA_EMBEDDING_MODEL,
                },
            }
        )

    except Exception as e:
        logger.error(f"Error in semantic search API: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": _format_error_message(e)}, status=500)


@require_http_methods(["GET", "POST"])
@csrf_exempt  # Anonymous, session-less and side-effect free: there is no ambient
# credential for a cross-site request to abuse. Cost/abuse is handled by the
# rate limiter and input validation below, not by CSRF.
def rag_answer_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for RAG-based question answering.

    GET/POST /api/v1/search/answer/

    Parameters:
        - question (required): The legal question to answer
        - k (optional): Number of context items to retrieve (default: 5)
        - model (optional): LLM model to use (default: llama3)

    Returns:
        JSON response with:
        - success: bool
        - question: str
        - answer: str (generated answer)
        - sources: list of source dispositivos
        - confidence: float (0-1)
        - metadata: dict
    """
    limited = rate_limit_response(request)
    if limited:
        return limited

    try:
        # Handle both GET and POST
        if request.method == "POST":
            try:
                data = json.loads(request.body)
            except json.JSONDecodeError:
                return JsonResponse(
                    {"success": False, "error": "Invalid JSON in request body"}, status=400
                )
        else:  # GET
            data = request.GET

        try:
            question, k, model = parse_llm_request(data)
            temperature = parse_temperature(data.get("temperature"))
            retrieval_options = build_retrieval_options(request, data, k)
        except InvalidLLMParams as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=400)

        if not question:
            return JsonResponse(
                {
                    "success": False,
                    "error": "Question parameter is required",
                    "example": "/api/v1/search/answer/?question=Como+funciona+o+IPTU+em+Natal",
                },
                status=400,
            )

        logger.info(f"RAG answer request: question='{question[:50]}...', k={k}, model={model}")

        # Generate answer using RAG
        rag_service = RAGService()
        response = rag_service.answer_question(
            question=question,
            k=k,
            model=model,
            temperature=temperature,
            options=retrieval_options,
        )

        # Format sources with centralized serializer
        formatted_sources = [
            serialize_dispositivo_source(source) for source in response.get("sources", [])
        ]

        return JsonResponse(
            {
                "success": True,
                "question": question,
                "answer": response["answer"],
                "sources": formatted_sources,
                "confidence": response["confidence"],
                "metadata": {
                    "k": k,
                    "model": response.get("model", model),
                    "context_length": response.get("context_length", 0),
                    "cached": response.get("cached", False),
                },
            }
        )

    except Exception as e:
        logger.error(f"Error in RAG answer API: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": _format_error_message(e)}, status=500)


@require_http_methods(["POST"])
def chatbot_stream_api(request: HttpRequest) -> HttpResponse:
    """
    Streaming SSE endpoint for real-time RAG question answering.

    POST /api/v1/search/answer/stream/
    Payload: {"question": "...", "k": 5, "model": "llama3", "session_id": 123}

    Streams Server-Sent Events (SSE):
    - data: {"type": "status", "status": "retrieving"}
    - data: {"type": "sources", "sources": [...], "confidence": 0.85}
    - data: {"type": "chunk", "chunk": "..."}
    - data: {"type": "done", "answer": "...", "session_id": ...}
    """
    limited = rate_limit_response(request)
    if limited:
        return limited

    try:
        data = json.loads(request.body)
        question, k, model = parse_llm_request(data)
        temperature = parse_temperature(data.get("temperature"))
        retrieval_options = build_retrieval_options(request, data, k)
        text_provider = validate_provider_config(data.get("llm_provider", {"provider": "ollama"}))
    except InvalidLLMParams as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except ValueError as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid request body"}, status=400)

    session_id = data.get("session_id")
    if session_id is not None and (isinstance(session_id, bool) or not isinstance(session_id, int)):
        return JsonResponse({"success": False, "error": "Invalid session_id"}, status=400)

    if not question:
        return JsonResponse({"success": False, "error": "Question is required"}, status=400)

    previous_question = data.get("previous_question", "")
    if not isinstance(previous_question, str) or len(previous_question) > 10000:
        return JsonResponse({"success": False, "error": "Invalid previous_question"}, status=400)
    client_session_id = data.get("client_session_id", "")
    if not isinstance(client_session_id, str) or len(client_session_id) > 80:
        return JsonResponse({"success": False, "error": "Invalid client_session_id"}, status=400)

    # Session management
    chat_session = None
    first_turn = False
    context_question = previous_question
    if request.user.is_authenticated:
        try:
            with transaction.atomic():
                if session_id:
                    chat_session = ChatSession.objects.filter(
                        id=session_id, user=request.user
                    ).first()
                    if not chat_session:
                        return JsonResponse(
                            {"success": False, "error": "Session not found"}, status=404
                        )
                if not chat_session:
                    chat_session = ChatSession.objects.create(
                        user=request.user, title="Nova pesquisa", is_active=True
                    )
                prior_user_messages = list(ChatMessage.objects.filter(
                    session=chat_session, role="user"
                ).order_by("-created_at", "-id").values_list("content", flat=True)[:5])
                if prior_user_messages:
                    context_question = "\n".join(prior_user_messages)
                else:
                    first_turn = True
                ChatMessage.objects.create(session=chat_session, role="user", content=question)
                ChatSession.objects.filter(pk=chat_session.pk).update(updated_at=timezone.now())
        except Exception as e:
            return _server_error("persisting user message", e)

    def event_stream():
        sources_list = []
        accumulated_answer = ""
        assistant_persisted = False
        stream_gen = None
        try:
            yield f"data: {json.dumps({'type': 'status', 'status': 'queued'})}\n\n"
            if chat_session:
                yield f"data: {json.dumps({'type': 'session', 'session_id': chat_session.id, 'session_slug': chat_session.slug})}\n\n"
            rag_service = RAGService()
            retrieval_question = _resolve_article_followup(question, context_question)
            stream_gen = rag_service.stream_answer_question(
                retrieval_question, k=k, model=model, temperature=temperature, options=retrieval_options,
                text_provider=text_provider,
            )

            for item in stream_gen:
                ev_type = item.get("event")
                if ev_type == "status":
                    status = item.get("status")
                    allowed_statuses = {
                        "queued",
                        "retrieving",
                        "reranking",
                        "grounding",
                        "generating",
                        "finalizing",
                        "completed",
                        "insufficient_evidence",
                        "failed",
                        "cancelled",
                    }
                    if status in allowed_statuses:
                        yield f"data: {json.dumps({'type': 'status', 'status': status})}\n\n"
                elif ev_type == "sources":
                    raw_sources = item.get("sources", [])
                    sources_list = [serialize_dispositivo_source(s) for s in raw_sources]
                    payload = {
                        "type": "sources",
                        "sources": sources_list,
                        "confidence": item.get("confidence", 0.0),
                        "cached": item.get("cached", False),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                elif ev_type == "chunk":
                    chunk_text = item.get("chunk", "") or ""
                    provisional = bool(item.get("provisional", False))
                    # Unverified draft output is streamed to the UI but must not
                    # become a persisted answer if the client disconnects.
                    if not provisional:
                        accumulated_answer += chunk_text
                    payload = {
                        "type": "chunk",
                        "chunk": chunk_text,
                        "provisional": provisional,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                elif ev_type == "done":
                    final_answer = item.get("answer", "")
                    grounded = item.get("grounded") is True
                    answer_sources = sources_list if grounded else []
                    if request.user.is_authenticated and chat_session:
                        try:
                            ChatMessage.objects.create(
                                session=chat_session,
                                role="assistant",
                                content=final_answer,
                                sources_json=answer_sources,
                                metadata_json={
                                    "model": model,
                                    "sources_count": len(answer_sources),
                                    "grounded": grounded,
                                    "streaming": True,
                                },
                            )
                            assistant_persisted = True
                        except Exception as msg_err:
                            logger.error(f"Error persisting streaming assistant message: {msg_err}")
                            yield f"data: {json.dumps({'type': 'error', 'error': 'A resposta foi gerada, mas não pôde ser salva. Copie o texto antes de sair.'})}\n\n"
                            return

                    payload = {
                        "type": "done",
                        "answer": final_answer,
                        "grounded": grounded,
                        "session_id": chat_session.id if chat_session else None,
                        "session_slug": getattr(chat_session, "slug", None)
                        if chat_session
                        else None,
                    }
                    yield f"data: {json.dumps({'type': 'status', 'status': 'completed'})}\n\n"
                    yield f"data: {json.dumps(payload)}\n\n"
                    if first_turn and chat_session:
                        title = _generate_local_conversation_title(question)
                        ChatSession.objects.filter(pk=chat_session.pk).update(title=title)
                        yield f"data: {json.dumps({'type': 'title', 'title': title})}\n\n"
                    elif not request.user.is_authenticated and client_session_id.startswith("local-") and not context_question:
                        title = _generate_local_conversation_title(question)
                        yield f"data: {json.dumps({'type': 'title', 'title': title, 'client_session_id': client_session_id})}\n\n"
        except Exception as e:
            logger.error(f"Error in chatbot_stream_api stream: {e}", exc_info=True)
            yield f"data: {json.dumps({'type': 'status', 'status': 'failed'})}\n\n"
            err_payload = {"type": "error", "error": _format_error_message(e)}
            yield f"data: {json.dumps(err_payload)}\n\n"
        finally:
            if stream_gen is not None and hasattr(stream_gen, "close"):
                try:
                    stream_gen.close()
                except Exception:
                    logger.exception("Error closing RAG stream")
            if (
                request.user.is_authenticated
                and chat_session
                and accumulated_answer
                and not assistant_persisted
            ):
                try:
                    ChatMessage.objects.create(
                        session=chat_session,
                        role="assistant",
                        content=accumulated_answer,
                        sources_json=sources_list,
                        metadata_json={
                            "model": model,
                            "sources_count": len(sources_list),
                            "streaming": True,
                            "interrupted": True,
                        },
                    )
                except Exception as msg_err:
                    logger.error(f"Error persisting interrupted assistant message: {msg_err}")

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    return response
