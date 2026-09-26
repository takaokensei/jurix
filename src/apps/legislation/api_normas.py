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
