"""Streaming text-generation adapters; embeddings remain local in Ollama."""

from __future__ import annotations

import json
from urllib.parse import urlparse

import requests

PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "gemini": "https://generativelanguage.googleapis.com/v1beta/openai",
    "openrouter": "https://openrouter.ai/api/v1",
    "groq": "https://api.groq.com/openai/v1",
}


def validate_provider_config(value):
    if not isinstance(value, dict):
        return None
    provider = value.get("provider", "ollama")
    if provider not in {"ollama", "openai", "gemini", "openrouter", "groq", "anthropic", "compatible"}:
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
        parsed = urlparse(endpoint)
        if parsed.scheme != "http" or parsed.hostname not in {"localhost", "127.0.0.1", "::1", "host.docker.internal"} or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("Endpoint próprio deve ser HTTP em um host local permitido, sem credenciais, query ou fragmento.")
        endpoint = endpoint.rstrip("/")
        if endpoint.endswith("/chat/completions"):
            endpoint = endpoint.rsplit("/chat/completions", 1)[0]
    else:
        endpoint = "https://api.anthropic.com/v1" if provider == "anthropic" else PROVIDER_URLS[provider]
    if not api_key:
        raise ValueError("Informe a chave de API deste provedor.")
    return {"provider": provider, "model": model.strip(), "api_key": api_key, "endpoint": endpoint}


def stream_text(prompt: str, config: dict, *, temperature: float, max_tokens: int):
    provider = config["provider"]
    if provider == "anthropic":
        url = f"{config['endpoint']}/messages"
        headers = {"x-api-key": config["api_key"], "anthropic-version": "2023-06-01", "content-type": "application/json"}
        payload = {"model": config["model"], "max_tokens": max_tokens, "temperature": temperature, "stream": True, "messages": [{"role": "user", "content": prompt}]}
    else:
        url = f"{config['endpoint']}/chat/completions"
        headers = {"Authorization": f"Bearer {config['api_key']}", "Content-Type": "application/json"}
        payload = {"model": config["model"], "temperature": temperature, "max_tokens": max_tokens, "stream": True, "messages": [{"role": "user", "content": prompt}]}
    with requests.post(url, headers=headers, json=payload, stream=True, timeout=(5, 120), allow_redirects=False) as response:
        response.raise_for_status()
        for raw_line in response.iter_lines(decode_unicode=True):
            if not raw_line:
                continue
            line = raw_line.decode("utf-8", errors="replace") if isinstance(raw_line, bytes) else raw_line
            if not line.startswith("data:"):
                continue
            raw = line[5:].strip()
            if raw == "[DONE]":
                break
            try:
                event = json.loads(raw)
            except (json.JSONDecodeError, TypeError):
                continue
            if provider == "anthropic":
                text = event.get("delta", {}).get("text", "") if event.get("type") == "content_block_delta" else ""
            else:
                choices = event.get("choices") or []
                text = (choices[0].get("delta") or {}).get("content", "") if choices else ""
            if isinstance(text, str) and text:
                yield text
