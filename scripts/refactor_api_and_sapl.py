"""Split the two remaining large application modules while preserving imports."""
from __future__ import annotations
import ast
from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
LEG = ROOT / "src/apps/legislation"
SAPL = ROOT / "src/clients/sapl"
API_GROUPS = {
    "api_health.py": ["health_live_api", "_check_database", "_check_pgvector", "_check_redis", "_check_migrations", "_check_ollama", "health_ready_api", "health_check_api"],
    "api_search.py": ["semantic_search_api", "rag_answer_api", "chatbot_stream_api"],
    "api_normas.py": ["norma_list_api", "norma_detail_api"],
    "api_chat.py": ["chat_sessions_api", "chat_session_by_slug_api", "chat_session_detail_api", "chat_session_regenerate_api"],
    "api_attachments.py": ["chat_attachment_api", "chat_attachment_detail_api", "dynamic_suggestions_api"],
}
API_IMPORTS = '''from __future__ import annotations
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
'''
HELPERS = '''
def _format_error_message(e: Exception) -> str:
    """Format a safe client-facing error message."""
    if settings.DEBUG:
        return str(e)
    return "Internal server error"


def _server_error(context: str, exc: Exception) -> JsonResponse:
    """Log the failure with its traceback; never expose internal details."""
    logger.error(f"Error in {context}: {exc}", exc_info=True)
    return JsonResponse({"success": False, "error": _format_error_message(exc)}, status=500)
'''

def top_nodes(source: str) -> dict[str, str]:
    tree = ast.parse(source); lines = source.splitlines(); result = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            result[node.name] = "\n".join(lines[start - 1 : node.end_lineno])
    return result

def split_api() -> None:
    path = LEG / "api_views.py"; ns = top_nodes(path.read_text(encoding="utf-8"))
    for filename, names in API_GROUPS.items():
        missing = [n for n in names if n not in ns]
        if missing: raise SystemExit(f"missing API symbols in legacy module: {missing}")
        prefix = API_IMPORTS if filename != "api_health.py" else API_IMPORTS + HELPERS
        if filename != "api_health.py": prefix += "\nfrom .api_health import _format_error_message, _server_error\n"
        (LEG / filename).write_text(prefix + "\n" + "\n\n".join(ns[n] for n in names) + "\n", encoding="utf-8")
    (LEG / "api_views.py").write_text('''"""Stable API view import surface; implementations are split by concern."""
from . import api_attachments, api_chat, api_health, api_normas, api_search
from .api_health import *
from .api_search import *
from .api_normas import *
from .api_chat import *
from .api_attachments import *

def _sync(module) -> None:
    for name in ("RAGService", "ChatMessage", "ChatSession", "Dispositivo", "EventoAlteracao", "Norma", "rate_limit_response", "parse_k", "parse_llm_request", "parse_model", "build_retrieval_options", "serialize_dispositivo_source", "transaction", "timezone", "InvalidLLMParams", "_format_error_message", "_server_error", "_check_database", "_check_pgvector", "_check_redis", "_check_migrations", "_check_ollama", "list_attachments", "upload_attachment", "delete_attachment", "AttachmentError", "build_dynamic_suggestions", "_chat_session_response", "_parse_limit", "_preview"):
        if name in globals(): setattr(module, name, globals()[name])

def _delegate(module, name, *args, **kwargs):
    _sync(module); return getattr(module, name)(*args, **kwargs)

def health_live_api(request): return _delegate(api_health, "health_live_api", request)
def health_ready_api(request): return _delegate(api_health, "health_ready_api", request)
def health_check_api(request): return _delegate(api_health, "health_check_api", request)
def semantic_search_api(request): return _delegate(api_search, "semantic_search_api", request)
def rag_answer_api(request): return _delegate(api_search, "rag_answer_api", request)
def chatbot_stream_api(request): return _delegate(api_search, "chatbot_stream_api", request)
def norma_list_api(request): return _delegate(api_normas, "norma_list_api", request)
def norma_detail_api(request, pk): return _delegate(api_normas, "norma_detail_api", request, pk)
def chat_sessions_api(request): return _delegate(api_chat, "chat_sessions_api", request)
def chat_session_by_slug_api(request, slug): return _delegate(api_chat, "chat_session_by_slug_api", request, slug)
def chat_session_detail_api(request, session_id): return _delegate(api_chat, "chat_session_detail_api", request, session_id)
def chat_session_regenerate_api(request, session_id): return _delegate(api_chat, "chat_session_regenerate_api", request, session_id)
def chat_attachment_api(request): return _delegate(api_attachments, "chat_attachment_api", request)
def chat_attachment_detail_api(request, attachment_id): return _delegate(api_attachments, "chat_attachment_detail_api", request, attachment_id)
def dynamic_suggestions_api(request): return _delegate(api_attachments, "dynamic_suggestions_api", request)
''', encoding="utf-8")

SAPL_GROUPS = {
    "sapl_transport.py": ["_create_session", "_get_headers", "get_public_norma_url", "_make_request", "_make_request_url", "close"],
    "sapl_normas.py": ["fetch_normas_page", "fetch_normas", "fetch_norma_by_id", "fetch_normas_by_year_range"],
    "sapl_corpus.py": ["fetch_all_normas", "fetch_normas_for_corpus"],
    "sapl_download.py": ["download_pdf"],
}

def class_methods(source: str) -> dict[str, str]:
    tree = ast.parse(source); lines = source.splitlines(); cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "SaplAPIClient")
    return {n.name: "\n".join(lines[n.lineno - 1 : n.end_lineno]) for n in cls.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}

def split_sapl() -> None:
    path = SAPL / "sapl_client.py"; methods = class_methods(path.read_text(encoding="utf-8"))
    imports = '''from __future__ import annotations
import logging
import os
import time
from typing import Any
import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
logger = logging.getLogger(__name__)
'''
    for filename, names in SAPL_GROUPS.items():
        missing = [n for n in names if n not in methods]
        if missing: raise SystemExit(f"missing SAPL methods: {missing}")
        cls = filename[:-3].title().replace("_", "") + "Mixin"
        body = "\n\n".join("    " + methods[n].replace("\n", "\n    ") for n in names)
        (SAPL / filename).write_text(imports + f"\nclass {cls}:\n" + body + "\n", encoding="utf-8")
    (SAPL / "sapl_client.py").write_text('''"""Compatibility facade for the SAPL client, split into focused mixins."""
from __future__ import annotations
import logging
import os
from django.conf import settings
from .sapl_transport import SaplTransportMixin
from .sapl_normas import SaplNormasMixin
from .sapl_corpus import SaplCorpusMixin
from .sapl_download import SaplDownloadMixin
logger = logging.getLogger(__name__)
class SaplAPIClient(SaplTransportMixin, SaplNormasMixin, SaplCorpusMixin, SaplDownloadMixin):
    DEFAULT_BASE_URL = getattr(settings, "SAPL_BASE_URL", os.getenv("SAPL_BASE_URL", "https://sapl.natal.rn.leg.br/api"))
    BASE_URL = DEFAULT_BASE_URL
    NORMA_ENDPOINT = "/norma/normajuridica/"
    USER_AGENTS = ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36", "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36", "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"]
    def __init__(self, base_url: str | None = None, timeout: int = 30, max_retries: int = 3):
        resolved_url = base_url or getattr(settings, "SAPL_BASE_URL", self.BASE_URL)
        self.base_url = str(resolved_url).rstrip("/")
        self.timeout = timeout
        self.session = self._create_session(max_retries)
        self._request_count = 0
        logger.info("SaplAPIClient inicializado: base_url=%s, timeout=%ss, max_retries=%s", self.base_url, timeout, max_retries)
''', encoding="utf-8")

def main() -> None:
    split_api(); split_sapl()
if __name__ == "__main__": main()
