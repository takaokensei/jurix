# ruff: noqa: F401,F403,E501,E701,I001
from __future__ import annotations

import json
import logging
from django.conf import settings
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Exists, OuterRef, Q, Subquery
from django.http import HttpRequest, HttpResponse, JsonResponse, StreamingHttpResponse
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

    GET /api/v1/normas/?status=<status>&tipo=<tipo>&ano=<ano>&search=<text>&page=<int>&page_size=<int>

    Query Parameters:
        - status (optional): Filter by status (e.g., 'consolidated')
        - page (optional): Page number (default: 1)
        - page_size (optional): Items per page (default: 20, max: 100)
        - tipo (optional): Human label or SAPL type code (e.g. 'Lei' or '1')
        - ano (optional): Publication year
        - search (optional): Search in ementa, numero, tipo

    Returns:
        JSON response with paginated normas
    """
    try:
        # Extract parameters
        status = request.GET.get("status")
        norma_type = request.GET.get("tipo", "").strip()
        year_raw = request.GET.get("ano", "").strip()
        search = request.GET.get("search", "").strip()
        if len(search) > 200:
            return JsonResponse(
                {"success": False, "error": "Busca muito longa (máximo de 200 caracteres)."},
                status=400,
            )

        try:
            page = max(int(request.GET.get("page", 1)), 1)
            page_size = max(1, min(int(request.GET.get("page_size", 20)), 100))
        except ValueError:
            page = 1
            page_size = 20

        # Build queryset
        queryset = Norma.objects.all()

        if status:
            queryset = queryset.filter(status=status)

        if norma_type:
            type_codes = {
                "Lei": "1",
                "Lei Complementar": "2",
                "Decreto": "3",
                "Resolução": "4",
                "Emenda à Lei Orgânica": "5",
                "Portaria": "6",
            }
            raw_type = type_codes.get(norma_type, norma_type)
            label_type = next(
                (label for label, code in type_codes.items() if code == norma_type),
                norma_type,
            )
            queryset = queryset.filter(Q(tipo=norma_type) | Q(tipo=raw_type) | Q(tipo=label_type))

        if year_raw:
            try:
                queryset = queryset.filter(ano=int(year_raw))
            except ValueError:
                return JsonResponse({"success": False, "error": "Ano inválido."}, status=400)

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
                    "tipo": norma.get_tipo_display_name(),
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
                    "page": page_obj.number,
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
        norma = Norma.objects.filter(pk=pk).first()
        if norma is None:
            return JsonResponse(
                {"success": False, "error": f"Norma with ID {pk} not found"},
                status=404,
            )

        # Get dispositivos
        dispositivos = list(
            Dispositivo.objects.filter(norma=norma)
            .annotate(
                _has_embedding=Exists(
                    Dispositivo.objects.filter(pk=OuterRef("pk"), embedding__isnull=False)
                )
            )
            .select_related("dispositivo_pai")
            .defer("embedding")
            .order_by("ordem")
        )

        dispositivos_by_id = {item.id: item for item in dispositivos}

        def hierarchy_for(dispositivo):
            if dispositivo.caminho:
                return dispositivo.caminho
            chain = []
            current = dispositivo
            visited = set()
            while current and current.id not in visited:
                visited.add(current.id)
                chain.insert(0, str(current))
                current = dispositivos_by_id.get(current.dispositivo_pai_id)
            return " > ".join(chain)

        dispositivos_data = [
            {
                "id": d.id,
                "tipo": d.tipo,
                "numero": d.numero,
                "texto": d.texto,
                "ordem": d.ordem,
                "hierarchy": hierarchy_for(d),
                "parent_id": d.dispositivo_pai_id,
                # Dispositivo stores the vector directly; do not call a
                # non-existent model helper here (the detail endpoint must
                # remain usable with both SQLite and pgvector backends).
                "has_embedding": bool(d._has_embedding),
            }
            for d in dispositivos
        ]

        # Get alteration events
        eventos = (
            EventoAlteracao.objects.filter(norma_alvo=norma)
            .select_related("dispositivo_fonte", "dispositivo_fonte__norma", "dispositivo_alvo")
            .distinct()
            .order_by("created_at")
        )

        eventos_data = [
            {
                "id": e.id,
                "acao": e.acao,
                "tipo": e.get_acao_display(),
                "target_text": e.target_text,
                "source_norma": f"{e.dispositivo_fonte.norma.get_tipo_display_name()} nº {e.dispositivo_fonte.norma.numero}/{e.dispositivo_fonte.norma.ano}"
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
                    "tipo": norma.get_tipo_display_name(),
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
