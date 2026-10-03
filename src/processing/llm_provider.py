"""Streaming text-generation adapters; embeddings remain local in Ollama."""

from __future__ import annotations

import ipaddress
import json
from collections.abc import Callable
from urllib.parse import urlparse

import requests
from django.conf import settings

PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}

_LOCAL_HOSTS = {"localhost", "host.docker.internal"}


class ProviderStreamError(RuntimeError):
    """Sanitized protocol failure from a compatible text-generation provider."""

    def __init__(self, code: str):
        self.code = code
        messages = {
            "provider_error": "O provedor de IA informou uma falha durante a geração.",
            "invalid_event": "O provedor de IA enviou um evento inválido.",
            "truncated": "A geração foi interrompida antes de terminar.",
            "unsupported_finish": "O provedor encerrou a geração sem uma resposta completa.",
        }
        super().__init__(messages.get(code, messages["provider_error"]))


def _canonical_compatible_endpoint(endpoint: str) -> tuple[str, str, int | None, str]:
    """Return a strict base URL and its parsed host parts, rejecting URL ambiguity."""
    if not isinstance(endpoint, str) or not endpoint or endpoint != endpoint.strip():
        raise ValueError("Endpoint próprio inválido.")
    if any(ord(char) < 33 or ord(char) == 127 for char in endpoint):
        raise ValueError("Endpoint próprio contém caracteres inválidos.")
    try:
        parsed = urlparse(endpoint)
        hostname = parsed.hostname
        port = parsed.port
    except ValueError as exc:
        raise ValueError("Endpoint próprio inválido.") from exc
    if (
        parsed.scheme.lower() not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(
            "Endpoint próprio deve ser uma URL HTTP(S) sem credenciais, query ou fragmento."
        )
    path = parsed.path.rstrip("/")
    if path.endswith("/chat/completions"):
        path = path[: -len("/chat/completions")].rstrip("/")
    if path and (
        not path.startswith("/")
        or "//" in path
        or "\\" in path
        or any(part in {".", ".."} for part in path.split("/"))
    ):
        raise ValueError("Caminho do endpoint próprio inválido.")
    host = hostname.lower().rstrip(".")
    if not host or "%" in host:
        raise ValueError("Host do endpoint próprio inválido.")
    rendered_host = f"[{host}]" if ":" in host else host
    authority = rendered_host + (f":{port}" if port is not None else "")
    base_url = f"{parsed.scheme.lower()}://{authority}{path}"
    return base_url, host, port, parsed.scheme.lower()


def _validate_compatible_endpoint(endpoint: str) -> str:
    base_url, host, _port, _scheme = _canonical_compatible_endpoint(endpoint)
    try:
        is_loopback = ipaddress.ip_address(host).is_loopback
    except ValueError:
        is_loopback = host in _LOCAL_HOSTS

    if is_loopback and getattr(settings, "LLM_ALLOW_LOCAL_COMPATIBLE_ENDPOINTS", False):
        return base_url

    allowed = set()
    for configured in getattr(settings, "LLM_COMPATIBLE_ENDPOINT_ALLOWLIST", ()):
        try:
            allowed.add(_canonical_compatible_endpoint(configured)[0])
        except ValueError:
            # Invalid deployment configuration never broadens the allowlist.
            continue
    if base_url not in allowed:
        raise ValueError("Endpoint próprio não está na lista de destinos permitidos.")
    return base_url


def validate_provider_config(value):
    if not isinstance(value, dict):
        return None
    provider = value.get("provider", "ollama")
    if provider not in {
        "ollama",
        "openai",
        "gemini",
        "openrouter",
        "groq",
        "anthropic",
        "compatible",
    }:
        raise ValueError("Provedor de IA inválido.")
    if provider == "ollama":
        return {"provider": "ollama"}
    model = value.get("model", "")
    api_key = value.get("api_key", "")
    endpoint = value.get("endpoint", "")
    if not isinstance(model, str) or not model.strip() or len(model) > 120:
        raise ValueError("Informe um identificador de modelo válido.")
    if not isinstance(api_key, str) or len(api_key) > 4096:
        raise ValueError("Chave de API inválida.")
    if provider == "compatible":
        if not isinstance(endpoint, str) or len(endpoint) > 500:
            raise ValueError("Endpoint inválido.")
        endpoint = _validate_compatible_endpoint(endpoint)
        optional_auth_endpoints = set()
        for configured_endpoint in getattr(settings, "LLM_COMPATIBLE_OPTIONAL_AUTH_ALLOWLIST", ()):
            try:
                optional_auth_endpoints.add(_canonical_compatible_endpoint(configured_endpoint)[0])
            except ValueError:
                continue
        auth_optional = endpoint in optional_auth_endpoints
    else:
        endpoint = (
            "https://api.anthropic.com/v1" if provider == "anthropic" else PROVIDER_URLS[provider]
        )
        auth_optional = False
    if not api_key and not auth_optional:
        raise ValueError("Informe a chave de API deste provedor.")
    return {
        "provider": provider,
        "model": model.strip(),
        "api_key": api_key,
        "endpoint": endpoint,
        "auth_required": not auth_optional,
    }


def stream_text(
    prompt: str,
    config: dict,
    *,
    temperature: float,
    max_tokens: int,
    should_cancel: Callable[[], bool] | None = None,
):
    if should_cancel is not None and should_cancel():
        return
    provider = config["provider"]
    endpoint = (
        _validate_compatible_endpoint(config["endpoint"])
        if provider == "compatible"
        else config["endpoint"]
    )
    if provider == "anthropic":
        url = f"{endpoint}/messages"
        headers = {
            "x-api-key": config["api_key"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }
        payload = {
            "model": config["model"],
            "max_tokens": max_tokens,
            "temperature": temperature,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
    else:
        url = f"{endpoint}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if config.get("api_key"):
            headers["Authorization"] = f"Bearer {config['api_key']}"
        elif config.get("auth_required", True):
            raise ValueError("Este endpoint exige autenticação.")
        payload = {
            "model": config["model"],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
            "messages": [{"role": "user", "content": prompt}],
        }
    with requests.post(
        url, headers=headers, json=payload, stream=True, timeout=(5, 120), allow_redirects=False
    ) as response:
        response.raise_for_status()
        terminal_received = False
        for raw_line in response.iter_lines(decode_unicode=True):
            if should_cancel is not None and should_cancel():
                return
            if not raw_line:
                continue
            line = (
                raw_line.decode("utf-8", errors="replace")
                if isinstance(raw_line, bytes)
                else raw_line
            )
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                if provider == "anthropic":
                    raise ProviderStreamError("invalid_event")
                terminal_received = True
                break
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                raise ProviderStreamError("invalid_event") from None
            if not isinstance(event, dict):
                raise ProviderStreamError("invalid_event")
            if event.get("error") or event.get("type") == "error":
                raise ProviderStreamError("provider_error")
            if provider == "anthropic":
                if event.get("type") == "message_delta":
                    stop_reason = (event.get("delta") or {}).get("stop_reason")
                    if stop_reason == "max_tokens":
                        raise ProviderStreamError("truncated")
                    if stop_reason not in (None, "end_turn", "stop_sequence"):
                        raise ProviderStreamError("unsupported_finish")
                if event.get("type") == "message_stop":
                    terminal_received = True
                    break
                text = (
                    event.get("delta", {}).get("text", "")
                    if event.get("type") == "content_block_delta"
                    else ""
                )
            else:
                choices = event.get("choices") or []
                choice = choices[0] if choices else {}
                finish_reason = choice.get("finish_reason")
                if finish_reason == "length":
                    raise ProviderStreamError("truncated")
                if finish_reason not in (None, "stop"):
                    raise ProviderStreamError("unsupported_finish")
                text = (choice.get("delta") or {}).get("content", "") if choice else ""
            if isinstance(text, str) and text:
                yield text
        if not terminal_received:
            raise ProviderStreamError("truncated")
