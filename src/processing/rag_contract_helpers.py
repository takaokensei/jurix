"""Small response-contract helpers shared by sync and streaming RAG paths."""

from __future__ import annotations

from typing import Any


def contract(
    *,
    answer: str,
    sources: list[dict[str, Any]],
    source_relevance: float,
    grounded: bool,
    grounding: dict[str, Any],
    model: str,
    cached: bool = False,
) -> dict[str, Any]:
    return {
        "answer": answer,
        "sources": sources,
        "source_relevance": source_relevance,
        "confidence": None,
        "confidence_calibrated": False,
        "grounded": bool(grounded),
        "grounding": grounding,
        "model": model,
        "cached": cached,
    }


def grounding_fallback() -> str:
    return "Não encontrei evidências suficientes nas fontes recuperadas para sustentar essa resposta com segurança."
