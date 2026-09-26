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
