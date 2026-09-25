"""
API Views for legislation app.

Provides REST API endpoints for:
- Semantic search
- Norma retrieval
- RAG-based question answering
"""

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
from src.apps.legislation.chat_api_helpers import (
    _chat_session_response,
    _parse_limit,
    _preview,
)
from src.apps.legislation.models import (
    ChatMessage,
    ChatSession,
    Dispositivo,
    EventoAlteracao,
    Norma,
)
from src.apps.legislation.retrieval_api import build_retrieval_options
from src.apps.legislation.serializers import (
    serialize_chat_session,
    serialize_dispositivo_source,
)
from src.processing.adaptive_rag_service import AdaptiveRAGService

RAGService = AdaptiveRAGService

logger = logging.getLogger(__name__)


def _format_error_message(e: Exception) -> str:
    """Format safe error message for API responses."""
    if settings.DEBUG:
        return str(e)
    return "Ocorreu um erro interno ao processar sua solicitação."


@require_http_methods(["GET"])
def health_live_api(request: HttpRequest) -> JsonResponse:
    """Liveness probe: cheap check ensuring process is alive."""
    return JsonResponse({"status": "alive"})


def _check_database() -> tuple[bool, str]:
    """Check database connectivity."""
    try:
        from django.db import connection

        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _check_pgvector() -> tuple[bool, str]:
    """Check if pgvector extension is available."""
    try:
        from django.db import connection

        if connection.vendor != "postgresql":
            return True, "ok"
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1 FROM pg_extension WHERE extname = 'vector'")
            row = cursor.fetchone()
            if not row:
                return False, "pgvector extension not installed"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _check_redis() -> tuple[bool, str]:
    """Check direct Redis connectivity and the configured Django cache separately."""
    try:
        import redis

        client = redis.Redis.from_url(
            settings.REDIS_URL,
            socket_connect_timeout=1,
            socket_timeout=1,
        )
        client.ping()

        from django.core.cache import cache

        probe_key = "__health_probe__:jurix"
        cache.set(probe_key, "1", timeout=5)
        if cache.get(probe_key) != "1":
            return False, "redis cache read/write failed"
        cache.delete(probe_key)
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _check_migrations() -> tuple[bool, str]:
    """Check for unapplied database migrations."""
    try:
        from django.db import connection
        from django.db.migrations.executor import MigrationExecutor

        executor = MigrationExecutor(connection)
        targets = executor.loader.graph.leaf_nodes()
        plan = executor.migration_plan(targets)
        if plan:
            return False, f"Unapplied migrations: {len(plan)}"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


def _check_ollama() -> tuple[bool, str]:
    """Check Ollama service connectivity."""
    if not getattr(settings, "READINESS_REQUIRE_OLLAMA", True):
        return True, "skipped"
    try:
        from src.llm_engine.ollama_service import OllamaService

        service = OllamaService()
        if not service.check_connection():
            return False, "ollama unreachable"
        return True, "ok"
    except Exception as exc:
        return False, str(exc)


@require_http_methods(["GET"])
def health_ready_api(request: HttpRequest) -> JsonResponse:
    """Readiness probe: verifies all dependencies required to serve requests."""
    checks = {
        "database": _check_database,
        "pgvector": _check_pgvector,
        "redis": _check_redis,
        "migrations": _check_migrations,
        "ollama": _check_ollama,
    }
    dependencies = {}
    all_ok = True
    for name, check_fn in checks.items():
        ok, detail = check_fn()
        dependencies[name] = detail
        if not ok:
            all_ok = False

    status = "ready" if all_ok else "not_ready"
    status_code = 200 if all_ok else 503
    return JsonResponse(
        {
            "status": status,
            "dependencies": dependencies,
        },
        status=status_code,
    )


@require_http_methods(["GET"])
def health_check_api(request: HttpRequest) -> JsonResponse:
    """Compatibility alias for health check."""
    return health_ready_api(request)


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
        query_text = request.GET.get("query", "").strip()

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
            k = min(int(request.GET.get("k", 10)), 50)  # Max 50 results
        except ValueError:
            k = 10

        norma_id = request.GET.get("norma_id")
        if norma_id:
            try:
                norma_id = int(norma_id)
            except ValueError:
                norma_id = None

        try:
            min_similarity = float(request.GET.get("min_similarity", 0.0))
            min_similarity = max(0.0, min(1.0, min_similarity))  # Clamp to [0, 1]
        except ValueError:
            min_similarity = 0.0

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
                        "tipo": disp.norma.tipo,
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
                    "model": "nomic-embed-text",
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
        retrieval_options = build_retrieval_options(request, data, k)
    except InvalidLLMParams as exc:
        return JsonResponse({"success": False, "error": str(exc)}, status=400)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return JsonResponse({"success": False, "error": "Invalid request body"}, status=400)

    session_id = data.get("session_id")
    if session_id is not None and (isinstance(session_id, bool) or not isinstance(session_id, int)):
        return JsonResponse({"success": False, "error": "Invalid session_id"}, status=400)

    if not question:
        return JsonResponse({"success": False, "error": "Question is required"}, status=400)

    # Session management
    chat_session = None
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
                        user=request.user, title=question[:50], is_active=True
                    )
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
            if chat_session:
                yield f"data: {json.dumps({'type': 'session', 'session_id': chat_session.id, 'session_slug': chat_session.slug})}\n\n"
            rag_service = RAGService()
            stream_gen = rag_service.stream_answer_question(
                question, k=k, model=model, options=retrieval_options
            )

            for item in stream_gen:
                ev_type = item.get("event")
                if ev_type == "sources":
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
                    accumulated_answer += item.get("chunk", "") or ""
                    payload = {"type": "chunk", "chunk": item.get("chunk", "")}
                    yield f"data: {json.dumps(payload)}\n\n"
                elif ev_type == "done":
                    final_answer = item.get("answer", "")
                    if request.user.is_authenticated and chat_session:
                        try:
                            ChatMessage.objects.create(
                                session=chat_session,
                                role="assistant",
                                content=final_answer,
                                sources_json=sources_list,
                                metadata_json={
                                    "model": model,
                                    "sources_count": len(sources_list),
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
                        "session_id": chat_session.id if chat_session else None,
                        "session_slug": getattr(chat_session, "slug", None)
                        if chat_session
                        else None,
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
        except Exception as e:
            logger.error(f"Error in chatbot_stream_api stream: {e}", exc_info=True)
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


@require_http_methods(["GET"])
def norma_list_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint to list normas.

    GET /api/v1/normas/?status=<status>&page=<int>&page_size=<int>

    Query Parameters:
        - status (optional): Filter by status (e.g., 'consolidated')
        - page (optional): Page number (default: 1)
        - page_size (optional): Items per page (default: 20, max: 100)
        - search (optional): Search in ementa, numero, tipo

    Returns:
        JSON response with paginated normas
    """
    try:
        # Extract parameters
        status = request.GET.get("status")
        search = request.GET.get("search", "").strip()

        try:
            page = max(int(request.GET.get("page", 1)), 1)
            page_size = min(int(request.GET.get("page_size", 20)), 100)
        except ValueError:
            page = 1
            page_size = 20

        # Build queryset
        queryset = Norma.objects.all()

        if status:
            queryset = queryset.filter(status=status)

        if search:
            queryset = queryset.filter(
                Q(ementa__icontains=search)
                | Q(numero__icontains=search)
                | Q(tipo__icontains=search)
            )

        queryset = queryset.order_by("-ano", "-numero")

        # Paginate
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)

        # Format results
        normas = []
        for norma in page_obj:
            normas.append(
                {
                    "id": norma.id,
                    "tipo": norma.tipo,
                    "numero": norma.numero,
                    "ano": norma.ano,
                    "ementa": norma.ementa[:200] if norma.ementa else None,
                    "status": norma.status,
                    "data_publicacao": norma.data_publicacao.isoformat()
                    if norma.data_publicacao
                    else None,
                    "url": f"/normas/{norma.id}/",
                }
            )

        return JsonResponse(
            {
                "success": True,
                "normas": normas,
                "pagination": {
                    "page": page,
                    "page_size": page_size,
                    "total_pages": paginator.num_pages,
                    "total_count": paginator.count,
                    "has_next": page_obj.has_next(),
                    "has_previous": page_obj.has_previous(),
                },
            }
        )

    except Exception as e:
        logger.error(f"Error in norma list API: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": _format_error_message(e)}, status=500)


@require_http_methods(["GET"])
def norma_detail_api(request: HttpRequest, pk: int) -> JsonResponse:
    """
    API endpoint to retrieve single norma with devices and alterations.

    GET /api/v1/normas/<pk>/
    """
    try:
        norma = get_object_or_404(Norma, pk=pk)

        # Get dispositivos
        dispositivos = (
            Dispositivo.objects.filter(norma=norma)
            .select_related("dispositivo_pai")
            .order_by("ordem")
        )
        dispositivos_data = [
            {
                "id": d.id,
                "tipo": d.tipo,
                "numero": d.numero,
                "texto": d.texto,
                "ordem": d.ordem,
                "hierarchy": d.get_full_identifier(),
                "parent_id": d.dispositivo_pai_id,
                "has_embedding": d.has_embedding(),
            }
            for d in dispositivos
        ]

        # Get alteration events
        eventos = (
            EventoAlteracao.objects.filter(norma_alvo=norma)
            .select_related("dispositivo_fonte", "dispositivo_fonte__norma", "dispositivo_alvo")
            .order_by("created_at")
        )

        eventos_data = [
            {
                "id": e.id,
                "acao": e.acao,
                "tipo": e.get_acao_display(),
                "target_text": e.target_text,
                "source_norma": f"{e.dispositivo_fonte.norma.tipo} {e.dispositivo_fonte.norma.numero}/{e.dispositivo_fonte.norma.ano}"
                if e.dispositivo_fonte and e.dispositivo_fonte.norma
                else None,
                "source_dispositivo": e.dispositivo_fonte.get_full_identifier()
                if e.dispositivo_fonte
                else None,
                "target_dispositivo": e.dispositivo_alvo.get_full_identifier()
                if e.dispositivo_alvo
                else None,
                "confidence": e.extraction_confidence,
            }
            for e in eventos
        ]

        return JsonResponse(
            {
                "success": True,
                "norma": {
                    "id": norma.id,
                    "tipo": norma.tipo,
                    "numero": norma.numero,
                    "ano": norma.ano,
                    "ementa": norma.ementa,
                    "status": norma.status,
                    "status_display": norma.get_status_display(),
                    "data_publicacao": norma.data_publicacao.isoformat()
                    if norma.data_publicacao
                    else None,
                    "data_vigencia": norma.data_vigencia.isoformat()
                    if norma.data_vigencia
                    else None,
                    "has_consolidated_text": bool(norma.texto_consolidado),
                    "pdf_url": norma.pdf_url,
                    "sapl_url": norma.sapl_url,
                    "dispositivos_count": len(dispositivos_data),
                    "eventos_count": len(eventos_data),
                },
                "dispositivos": dispositivos_data,
                "eventos": eventos_data,
            }
        )

    except Norma.DoesNotExist:
        return JsonResponse(
            {"success": False, "error": f"Norma with ID {pk} not found"}, status=404
        )
    except Exception as e:
        logger.error(f"Error in norma detail API: {e}", exc_info=True)
        return JsonResponse({"success": False, "error": _format_error_message(e)}, status=500)


def _server_error(context: str, exc: Exception) -> JsonResponse:
    """Log the failure with its traceback; tell the client nothing internal."""
    logger.error(f"Error in {context}: {exc}", exc_info=True)
    return JsonResponse({"success": False, "error": _format_error_message(exc)}, status=500)


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
