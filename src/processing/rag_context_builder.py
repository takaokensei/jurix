"""Retrieve and format bounded legal context for the RAG prompt."""

from __future__ import annotations

import logging
import re
from typing import Any

from django.conf import settings

logger = logging.getLogger(__name__)


def build_relevant_context(
    service: Any, query_text: str, k: int = 5, max_tokens: int = 2000
) -> tuple[str, list[dict[str, Any]]]:
    """Retrieve evidence through ``service`` and build the bounded prompt context."""
    from src.observability.tracing import span

    with span("rag.retrieval", {"rag.k": k, "rag.query_length": len(query_text)}):
        results = service.semantic_search(query_text, k=k)

    if not results:
        return "Nenhum contexto relevante encontrado.", []

    context_parts: list[str] = []
    used_results: list[dict[str, Any]] = []
    used_chars = 0
    max_chars = min(max_tokens * 4, int(getattr(settings, "RAG_MAX_CONTEXT_CHARS", max_tokens * 4)))
    asks_for_norma_summary = bool(
        re.search(r"\b(?:ementa|assunto|tema)\b", query_text, re.IGNORECASE)
    )
    asks_for_temporal_status = bool(
        re.search(
            r"\b(?:vig[êe]ncia|vig[êe]nte|entra\s+em\s+vigor|publica(?:çc)[ãa]o)\b",
            query_text,
            re.IGNORECASE,
        )
    )

    for index, result in enumerate(results, 1):
        dispositivo = result["dispositivo"]
        norma = dispositivo.norma
        score = result["similarity_score"]
        tipo_getter = getattr(norma, "get_tipo_display_name", None)
        tipo_label = tipo_getter() if callable(tipo_getter) else getattr(norma, "tipo", "Lei")
        if str(tipo_label).isdigit():
            tipo_label = "Lei"

        ementa = getattr(norma, "ementa", "") or ""
        ementa_context = f" | Ementa: {ementa}" if asks_for_norma_summary and ementa else ""
        temporal_context = ""
        if asks_for_temporal_status:
            publication = getattr(norma, "data_publicacao", None)
            effective = getattr(norma, "data_vigencia", None)
            temporal_context = (
                f" | Publicação: {publication.isoformat() if publication else 'não informada'}"
                f" | Vigência registrada: {effective.isoformat() if effective else 'não informada'}"
            )

        header = (
            f"{index}. [{score:.2f}] {tipo_label} nº {norma.numero}/{norma.ano} | "
            f"{dispositivo.get_full_identifier()}: "
        )
        full_body = f"{dispositivo.texto}{ementa_context}{temporal_context}"
        separator = "\n\n" if context_parts else ""
        remaining = max_chars - used_chars - len(separator)
        body_budget = remaining - len(header)
        if body_budget <= 0:
            break
        snippet = full_body[:body_budget]
        if not snippet.strip():
            continue
        part = f"{header}{snippet}"
        context_parts.append(part)
        used_chars += len(separator) + len(part)
        used_results.append(result)
        result["full_text"] = dispositivo.texto
        result["snippet"] = snippet
        result["evidence_text"] = snippet
        result["context_start"] = 0
        result["context_end"] = len(snippet)

    formatted_context = "\n\n".join(context_parts)
    total_chars = len(formatted_context)
    logger.info(
        "Generated context of %s characters from %s dispositivos",
        total_chars,
        len(context_parts),
    )
    return formatted_context, used_results
