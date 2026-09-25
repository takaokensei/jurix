"""
Input validation and rate limiting for LLM-backed endpoints.

Every request that reaches Ollama costs an embedding plus a generation on the
host, and several parameters are client-controlled. This module keeps the rules
in one place so that every LLM endpoint (JSON, SSE and the legacy form POST)
applies exactly the same limits.

- ``k`` is clamped to ``settings.LLM_MAX_K`` (it used to reach the SQL ``LIMIT``
  and the prompt size unchecked).
- ``model`` must be in ``settings.OLLAMA_ALLOWED_MODELS``; the client can no
  longer make the host load an arbitrary model.
- The question length is bounded.
- Requests are throttled per client with a fixed window kept in the Django
  cache (Redis in production). If the cache is unavailable the limiter fails
  OPEN: an outage of Redis must not take the whole site down.
"""

import hashlib
import logging
import time
from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.core.cache import cache
from django.http import HttpRequest, JsonResponse

logger = logging.getLogger(__name__)

DEFAULT_K = 12


class InvalidLLMParams(ValueError):
    """The client sent a parameter that is malformed or not allowed (HTTP 400)."""


class RateLimitBackendUnavailable(RuntimeError):
    """The rate-limit cache backend is unavailable."""


def parse_k(value: Any) -> int:
    """Return ``k`` clamped to [1, LLM_MAX_K]; reject non-integers."""
    if value is None or value == "":
        return DEFAULT_K
    if isinstance(value, bool):
        raise InvalidLLMParams("Parâmetro 'k' deve ser um número inteiro.")
    try:
        k = int(value)
    except (TypeError, ValueError):
        raise InvalidLLMParams("Parâmetro 'k' deve ser um número inteiro.") from None
    return max(1, min(k, settings.LLM_MAX_K))


def parse_model(value: Any) -> str:
    """Return the requested model if allowed, else the configured default."""
    if value is None or value == "":
        return settings.OLLAMA_MODEL
    if not isinstance(value, str) or value not in settings.OLLAMA_ALLOWED_MODELS:
        raise InvalidLLMParams("Modelo não permitido.")
    return value


def parse_question(value: Any) -> str:
    """Return the stripped question; reject non-strings and oversized input.

    An empty result is returned as ``''`` so each caller keeps its own message.
    """
    if value is None:
        return ""
    if not isinstance(value, str):
        raise InvalidLLMParams("Pergunta inválida.")
    question = value.strip()
    if len(question) > settings.LLM_MAX_QUESTION_LENGTH:
        raise InvalidLLMParams(
            f"Pergunta muito longa (máximo de {settings.LLM_MAX_QUESTION_LENGTH} caracteres)."
        )
    return question


def parse_llm_request(data: Any) -> tuple[str, int, str]:
    """Validate ``question``, ``k`` and ``model`` from a decoded JSON body or query."""
    if not isinstance(data, Mapping):
        raise InvalidLLMParams("Corpo da requisição inválido.")
    return (
        parse_question(data.get("question")),
        parse_k(data.get("k")),
        parse_model(data.get("model")),
    )


def parse_search_options(data: Any) -> dict[str, Any]:
    """Validate optional retrieval controls independently of the LLM model."""
    if not isinstance(data, Mapping):
        raise InvalidLLMParams("Corpo da requisição inválido.")

    mode = data.get("search_mode", data.get("mode", "hybrid"))
    if mode not in {"semantic", "lexical", "hybrid"}:
        raise InvalidLLMParams("Modo de pesquisa inválido.")

    norma_status = data.get("norma_status", "consolidated")
    if norma_status not in {"consolidated", "all"}:
        raise InvalidLLMParams("Escopo de normas inválido.")

    source_scope = data.get("source_scope", "municipal")
    if source_scope not in {"municipal", "all"}:
        raise InvalidLLMParams("Escopo de fontes inválido.")

    max_sources = parse_k(data.get("max_sources", data.get("k")))
    raw_min_similarity = data.get("min_similarity", 0.0)
    try:
        min_similarity = float(raw_min_similarity)
    except (TypeError, ValueError):
        raise InvalidLLMParams("min_similarity inválido.") from None
    if not 0.0 <= min_similarity <= 1.0:
        raise InvalidLLMParams("min_similarity deve estar entre 0 e 1.")

    attachment_ids = data.get("attachment_ids", [])
    if attachment_ids is None:
        attachment_ids = []
    if not isinstance(attachment_ids, list) or any(
        not isinstance(item, str) or len(item) > 80 for item in attachment_ids
    ):
        raise InvalidLLMParams("attachment_ids inválido.")
    if len(attachment_ids) > 5:
        raise InvalidLLMParams("No máximo 5 documentos podem ser usados em uma pesquisa.")

    return {
        "mode": mode,
        "norma_status": norma_status,
        "source_scope": source_scope,
        "max_sources": max_sources,
        "min_similarity": min_similarity,
        "attachment_ids": attachment_ids,
    }


def client_ip(request: HttpRequest) -> str:
    """
    Best-effort client IP that a client cannot forge.

    ``X-Forwarded-For`` is only trusted for the entries appended by OUR reverse
    proxies: with ``NUM_PROXIES = n`` the n-th entry from the right is used, and
    anything a client put before it is ignored. With 0 (default) the header is
    ignored entirely and ``REMOTE_ADDR`` is used.
    """
    remote = request.META.get("REMOTE_ADDR", "") or "unknown"
    proxies = getattr(settings, "NUM_PROXIES", 0)
    if proxies > 0:
        forwarded = [
            p.strip() for p in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if p.strip()
        ]
        if len(forwarded) >= proxies:
            return forwarded[-proxies]
    return remote


def client_identity(request: HttpRequest) -> str:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return f"user:{user.pk}"
    return f"ip:{client_ip(request)}"


def check_rate_limit(request: HttpRequest, scope: str = "llm") -> int | None:
    """
    Count this request and return the seconds to wait if the client is over the
    limit, or None if it may proceed. A limit <= 0 disables throttling.
    """
    limit = settings.LLM_RATE_LIMIT_REQUESTS
    window = settings.LLM_RATE_LIMIT_WINDOW_SECONDS
    if limit <= 0 or window <= 0:
        return None

    now = int(time.time())
    # Hash the identity: keeps the key short and free of characters that some
    # cache backends reject (IPv6 colons, spaces, non-ASCII).
    identity = hashlib.sha256(client_identity(request).encode("utf-8")).hexdigest()[:32]
    key = f"ratelimit:{scope}:{identity}:{now // window}"
    try:
        cache.add(key, 0, timeout=window)
        count = cache.incr(key)
    except Exception as exc:
        # Redis outage must not turn the limiter into unlimited model access.
        logger.error("Rate limiter backend unavailable", exc_info=True)
        raise RateLimitBackendUnavailable from exc

    if count > limit:
        return max(1, window - (now % window))
    return None


def rate_limit_response(request: HttpRequest, scope: str = "llm") -> JsonResponse | None:
    """Return a 429 response when the client is over the limit, else None."""
    try:
        retry_after = check_rate_limit(request, scope)
    except RateLimitBackendUnavailable:
        return JsonResponse(
            {
                "success": False,
                "error": "Serviço temporariamente indisponível. Tente novamente em instantes.",
            },
            status=503,
            headers={"Retry-After": "5"},
        )
    if retry_after is None:
        return None
    response = JsonResponse(
        {
            "success": False,
            "error": "Muitas requisições. Aguarde alguns instantes e tente novamente.",
            "retry_after": retry_after,
        },
        status=429,
    )
    response["Retry-After"] = str(retry_after)
    return response
