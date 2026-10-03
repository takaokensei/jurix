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
    reason_code: str | None = None,
) -> dict[str, Any]:
    if reason_code is None and not grounded:
        if grounding.get("reason") in {"generation_empty", "generation_failed"}:
            reason_code = "generation_failed"
        elif sources:
            reason_code = "evidence_insufficient"
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
        **({"reason_code": reason_code} if reason_code else {}),
    }


def grounding_fallback() -> str:
    return (
        "As fontes consultadas não permitem confirmar essa conclusão com segurança. "
        "Tente delimitar a pergunta a um dispositivo específico ou consulte o texto oficial."
    )


def no_retrieval_message(reason_code: str | None) -> str | None:
    """Return concise, non-repetitive copy for known retrieval outcomes."""
    messages = {
        "norm_not_in_corpus": (
            "A norma indicada não foi localizada no acervo do Jurix. Confira se o tipo da norma "
            "está correto ou pesquise diretamente na biblioteca de normas."
        ),
        "requested_device_not_in_corpus": (
            "O dispositivo solicitado não foi localizado no acervo do Jurix. Confira a referência "
            "ou consulte o texto oficial da norma."
        ),
        "norm_content_not_in_corpus": (
            "A norma foi identificada, mas o acervo do Jurix não contém seus dispositivos para "
            "fundamentar a resposta. Consulte o texto oficial."
        ),
    }
    return messages.get(reason_code)
