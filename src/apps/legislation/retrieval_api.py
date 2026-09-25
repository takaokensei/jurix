"""Translate public API search options into the internal retrieval contract."""

from __future__ import annotations

from typing import Any

from src.apps.legislation.api_limits import parse_search_options
from src.apps.legislation.attachment_service import get_attachment_texts
from src.processing.adaptive_retrieval import RetrievalOptions


def build_retrieval_options(request, data: Any, k: int) -> RetrievalOptions:
    values = parse_search_options(data)
    attachment_ids = values.get("attachment_ids", [])
    texts = get_attachment_texts(request, attachment_ids) if attachment_ids else []
    return RetrievalOptions(
        mode=values["mode"],
        norma_status=values["norma_status"],
        source_scope=values["source_scope"],
        max_sources=max(1, min(values["max_sources"], k, 20)),
        min_similarity=values["min_similarity"],
        attachment_texts=tuple(texts),
    )
