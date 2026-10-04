# ruff: noqa: F401,F403,E501,E701,I001
from __future__ import annotations

import json
import logging
import math
import re
from uuid import uuid4
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
    ChatTurn,
    Dispositivo,
    EventoAlteracao,
    Norma,
)
from src.apps.legislation.retrieval_api import build_retrieval_options
from src.apps.legislation.serializers import (
    serialize_chat_session,
    serialize_citation_sources,
)
from src.apps.legislation.suggestion_service import build_dynamic_suggestions
from src.processing.adaptive_rag_service import AdaptiveRAGService
from src.processing.answer_contract import build_answer_contract
from src.processing.chat_turns import (
    TurnPayloadConflict,
    normalize_turn_id,
    reserve_authenticated_turn,
    transition_turn,
)
from src.processing.conversation_titles import build_conversation_title
from src.processing.generation_control import (
    attach_ephemeral_session_cookie,
    claim_generation_finalization,
    finish_generation,
    is_generation_cancelled,
    register_generation,
)
from src.processing.llm_provider import validate_provider_config
from src.processing.normative_reference import parse_normative_references
from src.processing.rag_answer_pipeline import GenerationCancelled
from src.processing.rag_contract_helpers import no_retrieval_message
from src.observability.safe_logging import log_exception_safely

RAGService = AdaptiveRAGService
from .api_health import _format_error_message, _server_error

logger = logging.getLogger(__name__)


_ARTICLE_FOLLOWUP_RE = re.compile(
    r"\b(?:e\s+)?(?:o\s+)?art(?:igo)?\.?\s*(\d{1,4})\s*[º°o]?\b", re.IGNORECASE
)


def _resolve_article_followup(question: str, previous_question: str) -> str:
    """Preserve the follow-up and add only an unambiguous prior normative scope."""
    if not previous_question or len(previous_question) > 10000:
        return question
    match = _ARTICLE_FOLLOWUP_RE.search(question)
    if not match or parse_normative_references(question):
        return question
    reference = None
    typed_reference_seen = False
    # Conversations arrive newest-first from persistence. Resolve the law from
    # one message at a time so two norms mentioned in separate turns do not get
    # collapsed into an ambiguous composite citation.
    for prior_message in previous_question.splitlines():
        references = parse_normative_references(prior_message)
        typed_reference_seen = typed_reference_seen or bool(references)
        if len(references) == 1 and not references[0].ambiguous:
            reference = references[0]
            break
    if reference is None:
        # Compact references without a type are accepted only in isolation.
        # A typed but ambiguous mention must never fall back to its first match.
        if typed_reference_seen:
            return question
        compact_refs = [
            re.findall(r"\b(\d{1,7})\s*/\s*((?:19|20)\d{2})\b", line)
            for line in previous_question.splitlines()
        ]
        compact_refs = [items[0] for items in compact_refs if len(items) == 1]
        if len(compact_refs) != 1:
            return question
        number, year = compact_refs[0]
        kind = "norma"
    else:
        kind = {
            "lei": "Lei",
            "lei_complementar": "Lei Complementar",
            "lei_organica": "Lei Orgânica",
            "decreto": "Decreto",
            "decreto_lei": "Decreto-Lei",
            "decreto_legislativo": "Decreto Legislativo",
            "resolucao": "Resolução",
            "portaria": "Portaria",
            "emenda": "Emenda",
            "emenda_constitucional": "Emenda Constitucional",
        }.get(reference.type_key)
        if not kind or reference.year is None:
            return question
        number, year = reference.number, str(reference.year)
    # Keep the user's words/intention intact; context is a retrieval hint only.
    return f"{question.rstrip()} (contexto normativo: {kind} nº {number}/{year})"


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
            "API semantic search request (query_length=%s, k=%s, norma_id=%s, min_similarity=%s)",
            len(query_text),
            k,
            norma_id,
            min_similarity,
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
        log_exception_safely(logger, "Error in semantic search API", e)
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

        if retrieval_options.temporal_scope.as_of:
            return JsonResponse(
                {
                    "success": False,
                    "code": "historical_version_unavailable",
                    "error": (
                        "O corpus não mantém versões históricas verificadas desta redação. "
                        "Não é seguro apresentar o texto atual como se fosse o texto vigente "
                        "na data solicitada."
                    ),
                    "sources": [],
                    "metadata": {
                        "as_of": retrieval_options.temporal_scope.as_of.isoformat(),
                        "historical_version_available": False,
                    },
                },
                status=409,
            )

        logger.info(
            "RAG answer request (question_length=%s, k=%s, model=%s)",
            len(question),
            k,
            model,
        )

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
        formatted_sources = serialize_citation_sources(response.get("sources", []))
        reason_code = response.get("reason_code")
        answer_text = no_retrieval_message(reason_code) or response["answer"]
        answer_contract = build_answer_contract(
            question=question,
            retrieval_query=question,
            filters={
                "mode": retrieval_options.mode,
                "norma_status": retrieval_options.norma_status,
                "source_scope": retrieval_options.source_scope,
                "norma_type": retrieval_options.norma_type,
                "year": retrieval_options.year,
                "max_sources": retrieval_options.max_sources,
                "min_similarity": retrieval_options.min_similarity,
                "as_of": retrieval_options.as_of,
                "published_from": retrieval_options.published_from,
                "published_to": retrieval_options.published_to,
            },
            provider="ollama",
            model=response.get("model", model),
            sources=formatted_sources,
            grounding=response.get("grounding", {}),
            grounded=response.get("grounded") is True,
            cached=response.get("cached", False),
            reason_code=reason_code,
        )

        return JsonResponse(
            {
                "success": True,
                "question": question,
                "answer": answer_text,
                "sources": formatted_sources,
                "confidence": response["confidence"],
                "metadata": {
                    "k": k,
                    "model": response.get("model", model),
                    "context_length": response.get("context_length", 0),
                    "cached": response.get("cached", False),
                    "reason_code": reason_code,
                    "contract": answer_contract,
                },
            }
        )

    except Exception as e:
        log_exception_safely(logger, "Error in RAG answer API", e)
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

    archive_qa = data.get("qa_archive_corpus", False)
    if not isinstance(archive_qa, bool):
        return JsonResponse({"success": False, "error": "Escopo do corpus de teste inválido."}, status=400)
    if archive_qa and not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False):
        return JsonResponse({"success": False, "error": "Corpus de teste indisponível."}, status=404)

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
    request_id = str(uuid4())
    client_turn_id = data.get("client_turn_id")
    if client_turn_id is not None:
        try:
            client_turn_id = normalize_turn_id(client_turn_id)
        except ValueError as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
    retry_of_client_turn_id = data.get("retry_of_client_turn_id")
    if retry_of_client_turn_id is not None:
        try:
            retry_of_client_turn_id = normalize_turn_id(retry_of_client_turn_id)
        except ValueError as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=400)
        if client_turn_id is None:
            return JsonResponse(
                {"success": False, "error": "A retry must include a new client turn id"},
                status=400,
            )
    contract_filters = {
        "mode": retrieval_options.mode,
        "norma_status": retrieval_options.norma_status,
        "source_scope": retrieval_options.source_scope,
        "norma_type": retrieval_options.norma_type,
        "year": retrieval_options.year,
        "max_sources": retrieval_options.max_sources,
        "min_similarity": retrieval_options.min_similarity,
        "as_of": retrieval_options.as_of,
        "published_from": retrieval_options.published_from,
        "published_to": retrieval_options.published_to,
        "corpus": "archive-qa-unvalidated" if archive_qa else "consolidated",
    }

    # Session management
    chat_session = None
    chat_turn = None
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
                if client_turn_id is not None:
                    if not client_session_id:
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Client session id is required for idempotent turns",
                            },
                            status=400,
                        )
                    retry_of_turn = None
                    if retry_of_client_turn_id is not None:
                        retry_of_turn = ChatTurn.objects.filter(
                            user=request.user,
                            client_session_id=client_session_id,
                            client_turn_id=retry_of_client_turn_id,
                        ).first()
                        if retry_of_turn is None:
                            return JsonResponse(
                                {
                                    "success": False,
                                    "error": "Turno original da tentativa não encontrado",
                                },
                                status=409,
                            )
                        if chat_session is None:
                            chat_session = retry_of_turn.session
                    turn_payload = {
                        "question": question,
                        "k": k,
                        "model": model,
                        "temperature": temperature,
                        "retrieval": retrieval_options.fingerprint(),
                        "provider": text_provider,
                        "qa_archive_corpus": archive_qa,
                        "retry_of": str(retry_of_client_turn_id or ""),
                    }
                    chat_turn, created_turn = reserve_authenticated_turn(
                        user=request.user,
                        client_session_id=client_session_id,
                        client_turn_id=client_turn_id,
                        payload=turn_payload,
                        session=chat_session,
                        retry_of=retry_of_turn,
                    )
                    if not created_turn:
                        if chat_turn.state == "completed":
                            chat_session = chat_turn.session
                            replay_message = (
                                chat_turn.messages.filter(role="assistant")
                                .order_by("-created_at", "-id")
                                .first()
                            )
                            if not chat_session or not replay_message:
                                return JsonResponse(
                                    {
                                        "success": False,
                                        "error": "Turn is complete but its response is unavailable",
                                    },
                                    status=409,
                                )

                            def replay_completed_turn():
                                yield f"data: {json.dumps({'type': 'status', 'status': 'queued'})}\n\n"
                                yield f"data: {json.dumps({'type': 'session', 'session_id': chat_session.id, 'session_slug': chat_session.slug})}\n\n"
                                contract = replay_message.metadata_json or {}
                                replay_sources = (
                                    replay_message.sources_json
                                    if contract.get("grounded") is True
                                    else []
                                )
                                yield f"data: {json.dumps({'type': 'sources', 'sources': replay_sources, 'cached': True})}\n\n"
                                yield f"data: {json.dumps({'type': 'chunk', 'chunk': replay_message.content, 'provisional': False})}\n\n"
                                yield f"data: {json.dumps({'type': 'status', 'status': 'completed'})}\n\n"
                                yield f"data: {json.dumps({'type': 'done', 'answer': replay_message.content, 'grounded': contract.get('grounded') is True, 'contract': contract, 'session_id': chat_session.id, 'session_slug': chat_session.slug})}\n\n"

                            replay_response = StreamingHttpResponse(
                                replay_completed_turn(), content_type="text/event-stream"
                            )
                            replay_response["Cache-Control"] = "no-cache"
                            replay_response["X-Accel-Buffering"] = "no"
                            return replay_response
                        return JsonResponse(
                            {
                                "success": False,
                                "error": "Este turno já foi enviado; use uma nova tentativa para reenviar.",
                            },
                            status=409,
                        )
                    if not chat_session:
                        chat_session = ChatSession.objects.create(
                            user=request.user, title="Nova pesquisa", is_active=True
                        )
                        chat_turn.session = chat_session
                        chat_turn.save(update_fields=["session", "updated_at"])
                    chat_turn = transition_turn(chat_turn, "in_progress")
                elif not chat_session:
                    chat_session = ChatSession.objects.create(
                        user=request.user, title="Nova pesquisa", is_active=True
                    )
                prior_user_messages = list(
                    ChatMessage.objects.filter(session=chat_session, role="user")
                    .order_by("-created_at", "-id")
                    .values_list("content", flat=True)[:5]
                )
                if prior_user_messages:
                    context_question = "\n".join(prior_user_messages)
                else:
                    first_turn = True
                if not (chat_turn and chat_turn.retry_of_id):
                    ChatMessage.objects.create(
                        session=chat_session,
                        role="user",
                        content=question,
                        turn=chat_turn,
                    )
                ChatSession.objects.filter(pk=chat_session.pk).update(updated_at=timezone.now())
        except TurnPayloadConflict as exc:
            return JsonResponse({"success": False, "error": str(exc)}, status=409)
        except Exception as e:
            return _server_error("persisting user message", e)

    generation_id, cancel_token = register_generation(request)

    def event_stream():
        sources_list = []
        accumulated_answer = ""
        assistant_persisted = False
        generation_cancelled = False
        stream_gen = None
        pipeline_stage = "queued"
        retrieval_reason_code = None

        def mark_stream_cancelled():
            nonlocal generation_cancelled
            generation_cancelled = True
            finish_generation(generation_id, "cancelled")
            if chat_turn and ChatTurn.objects.filter(pk=chat_turn.pk, state="in_progress").exists():
                transition_turn(chat_turn, "cancelled")

        try:
            yield f"data: {json.dumps({'type': 'status', 'status': 'queued', 'cancel_token': cancel_token})}\n\n"
            if is_generation_cancelled(generation_id):
                mark_stream_cancelled()
                yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
                return
            if chat_session:
                yield f"data: {json.dumps({'type': 'session', 'session_id': chat_session.id, 'session_slug': chat_session.slug})}\n\n"
            if retrieval_options.temporal_scope.as_of:
                final_answer = (
                    "Não posso confirmar qual redação estava vigente nessa data: "
                    "o Jurix ainda não possui versões históricas verificadas para esta norma. "
                    "A redação atual não será apresentada como histórica."
                )
                metadata = {
                    "grounded": False,
                    "reason_code": "historical_version_unavailable",
                    "as_of": retrieval_options.temporal_scope.as_of.isoformat(),
                    "historical_version_available": False,
                }
                provenance = build_answer_contract(
                    question=question,
                    retrieval_query=question,
                    filters=contract_filters,
                    provider="unavailable",
                    model=model,
                    grounded=False,
                    request_id=request_id,
                )
                terminal_state = claim_generation_finalization(generation_id)
                if terminal_state == "cancelled":
                    mark_stream_cancelled()
                    yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
                    return
                yield f"data: {json.dumps({'type': 'status', 'status': 'insufficient_evidence'})}\n\n"
                if request.user.is_authenticated and chat_session:
                    with transaction.atomic():
                        ChatMessage.objects.create(
                            session=chat_session,
                            role="assistant",
                            content=final_answer,
                            sources_json=[],
                            metadata_json=provenance,
                            turn=chat_turn,
                        )
                        if chat_turn:
                            transition_turn(chat_turn, "completed")
                    assistant_persisted = True
                finish_generation(generation_id, "completed")
                yield f"data: {json.dumps({'type': 'status', 'status': 'completed'})}\n\n"
                yield f"data: {json.dumps({'type': 'done', 'answer': final_answer, **metadata, 'sources': [], 'contract': provenance})}\n\n"
                return
            retrieval_question = _resolve_article_followup(question, context_question)
            rag_service = RAGService()
            if archive_qa:
                from src.processing.qa_archive_rag import stream_archive_qa_answer

                stream_gen = stream_archive_qa_answer(
                    retrieval_question,
                    k=k,
                    model=model,
                    temperature=temperature,
                    text_provider=text_provider,
                    ollama=rag_service.ollama,
                    should_cancel=lambda: is_generation_cancelled(generation_id),
                )
            else:
                stream_gen = rag_service.stream_answer_question(
                    retrieval_question,
                    k=k,
                    model=model,
                    temperature=temperature,
                    options=retrieval_options,
                    text_provider=text_provider,
                    should_cancel=lambda: is_generation_cancelled(generation_id),
                )

            stream_iterator = iter(stream_gen)
            while True:
                # Poll between upstream events. This ends delivery promptly after
                # control returns from the provider; it does not interrupt a
                # currently blocked Ollama/provider request.
                if is_generation_cancelled(generation_id):
                    mark_stream_cancelled()
                    yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
                    return
                try:
                    item = next(stream_iterator)
                except StopIteration:
                    break
                if is_generation_cancelled(generation_id):
                    mark_stream_cancelled()
                    yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
                    return
                ev_type = item.get("event")
                if ev_type == "status":
                    status = item.get("status")
                    if status in {"queued", "retrieving", "reranking", "grounding", "generating", "finalizing"}:
                        pipeline_stage = status
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
                    retrieval_reason_code = item.get("reason_code")
                    raw_sources = item.get("sources", [])
                    sources_list = serialize_citation_sources(raw_sources)
                    payload = {
                        "type": "sources",
                        "sources": sources_list,
                        "confidence": item.get("confidence", 0.0),
                        "cached": item.get("cached", False),
                        "retrieval_strategy": item.get("retrieval_strategy")
                        or next((s.get("retrieval_strategy") for s in raw_sources if s.get("retrieval_strategy")), None),
                        "coverage": item.get("coverage")
                        or next((s.get("coverage") for s in raw_sources if s.get("coverage")), None),
                        "reason_code": item.get("reason_code"),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                elif ev_type == "chunk":
                    chunk_text = item.get("chunk", "") or ""
                    chunk_text = no_retrieval_message(retrieval_reason_code) or chunk_text
                    provisional = bool(item.get("provisional", False))
                    # Unverified draft output is streamed to the UI but must not
                    # become a persisted answer if the client disconnects.
                    if item.get("replace"):
                        accumulated_answer = chunk_text
                    elif not provisional:
                        accumulated_answer += chunk_text
                    payload = {
                        "type": "chunk",
                        "chunk": chunk_text,
                        "provisional": provisional,
                        "replace": bool(item.get("replace", False)),
                    }
                    yield f"data: {json.dumps(payload)}\n\n"
                elif ev_type == "done":
                    terminal_state = claim_generation_finalization(generation_id)
                    if terminal_state == "cancelled":
                        mark_stream_cancelled()
                        yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
                        return
                    grounded = item.get("grounded") is True
                    reason_code = item.get("reason_code")
                    if not grounded and not reason_code:
                        reason_code = retrieval_reason_code or "evidence_insufficient"
                    final_answer = no_retrieval_message(reason_code) or item.get("answer", "")
                    answer_sources = sources_list if grounded else []
                    provenance = build_answer_contract(
                        question=question,
                        retrieval_query=retrieval_question,
                        filters=contract_filters,
                        provider=text_provider.get("provider", "ollama"),
                        model=text_provider.get("model") or model,
                        sources=answer_sources,
                        discarded_sources=item.get("discarded_sources", []),
                        grounding=item.get("grounding", {}),
                        grounded=grounded,
                        cached=item.get("cached", False),
                        request_id=request_id,
                        timings_ms=item.get("timings_ms"),
                        generation_attempts=item.get("generation_attempts"),
                        reason_code=reason_code,
                    )
                    if request.user.is_authenticated and chat_session:
                        try:
                            with transaction.atomic():
                                ChatMessage.objects.create(
                                    session=chat_session,
                                    role="assistant",
                                    content=final_answer,
                                    sources_json=answer_sources,
                                    metadata_json=provenance,
                                    turn=chat_turn,
                                )
                                if chat_turn:
                                    transition_turn(chat_turn, "completed")
                            assistant_persisted = True
                        except Exception as msg_err:
                            log_exception_safely(
                                logger, "Error persisting streaming assistant message", msg_err
                            )
                            yield f"data: {json.dumps({'type': 'error', 'error': 'A resposta foi gerada, mas não pôde ser salva. Copie o texto antes de sair.'})}\n\n"
                            return

                    payload = {
                        "type": "done",
                        "answer": final_answer,
                        "grounded": grounded,
                        "contract": provenance,
                        "reason_code": reason_code,
                        "session_id": chat_session.id if chat_session else None,
                        "session_slug": getattr(chat_session, "slug", None)
                        if chat_session
                        else None,
                    }
                    if first_turn and chat_session:
                        title = build_conversation_title(question, answer_sources)
                        ChatSession.objects.filter(pk=chat_session.pk).update(title=title)
                        yield f"data: {json.dumps({'type': 'title', 'title': title})}\n\n"
                    elif (
                        not request.user.is_authenticated
                        and client_session_id.startswith("local-")
                        and not context_question
                    ):
                        title = build_conversation_title(question, answer_sources)
                        yield f"data: {json.dumps({'type': 'title', 'title': title, 'client_session_id': client_session_id})}\n\n"
                    finish_generation(generation_id, "completed")
                    yield f"data: {json.dumps({'type': 'status', 'status': 'completed'})}\n\n"
                    yield f"data: {json.dumps(payload)}\n\n"
        except GenerationCancelled:
            mark_stream_cancelled()
            yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
            return
        except Exception as e:
            log_exception_safely(logger, "Error in chatbot_stream_api stream", e)
            if is_generation_cancelled(generation_id):
                generation_cancelled = True
            if chat_turn:
                try:
                    transition_turn(chat_turn, "cancelled" if generation_cancelled else "failed")
                except Exception:
                    pass
            finish_generation(generation_id, "cancelled" if generation_cancelled else "failed")
            if generation_cancelled:
                yield f"data: {json.dumps({'type': 'status', 'status': 'cancelled'})}\n\n"
                return
            reason_code = "generation_failed" if pipeline_stage in {"generating", "grounding"} else "request_failed"
            yield f"data: {json.dumps({'type': 'status', 'status': 'failed', 'reason_code': reason_code})}\n\n"
            safe_error = (
                "A geração da resposta não foi concluída. Nenhum rascunho sem validação foi exibido; tente novamente."
                if reason_code == "generation_failed"
                else _format_error_message(e)
            )
            err_payload = {"type": "error", "error": safe_error, "reason_code": reason_code}
            yield f"data: {json.dumps(err_payload)}\n\n"
        finally:
            if is_generation_cancelled(generation_id):
                generation_cancelled = True
            if chat_turn and not assistant_persisted:
                try:
                    if ChatTurn.objects.filter(pk=chat_turn.pk, state="in_progress").exists():
                        transition_turn(chat_turn, "cancelled" if generation_cancelled else "interrupted")
                except Exception:
                    pass
            if stream_gen is not None and hasattr(stream_gen, "close"):
                try:
                    stream_gen.close()
                except Exception as close_err:
                    log_exception_safely(logger, "Error closing RAG stream", close_err)
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
                    log_exception_safely(
                        logger, "Error persisting interrupted assistant message", msg_err
                    )
            if assistant_persisted:
                finish_generation(generation_id, "completed")
            elif generation_cancelled:
                finish_generation(generation_id, "cancelled")
            else:
                finish_generation(generation_id, "interrupted")

    response = StreamingHttpResponse(event_stream(), content_type="text/event-stream")
    response["Cache-Control"] = "no-cache"
    response["X-Accel-Buffering"] = "no"
    attach_ephemeral_session_cookie(request, response)
    return response
