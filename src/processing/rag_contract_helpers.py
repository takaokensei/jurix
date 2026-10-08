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
    """Return the established safe message for each known retrieval outcome."""
    messages = {
        "norm_not_in_corpus": (
            "Não localizei essa norma no acervo do Jurix. Confira se o tipo da norma está correto, "
            "além do número e ano, ou pesquise diretamente na biblioteca de normas."
        ),
        "requested_device_not_in_corpus": (
            "Não localizei esse dispositivo no acervo do Jurix. Confira a referência ou consulte "
            "o texto oficial da norma."
        ),
        "norm_content_not_in_corpus": (
            "A norma foi identificada, mas o acervo do Jurix não contém seus dispositivos para "
            "fundamentar a resposta. Consulte o texto oficial."
        ),
        "historical_version_unavailable": (
            "Não encontrei uma versão histórica verificável desta norma para a data informada. "
            "Para evitar atribuir ao passado um texto atual, não vou presumir qual redação estava vigente."
        ),
        "historical_snapshot_unavailable": (
            "A versão desta norma para a data informada não está materializada no acervo. "
            "Sem uma reconstrução verificável, não vou usar o texto atual como substituto histórico."
        ),
        "historical_evidence_unavailable": (
            "Não encontrei evidências históricas suficientes para responder sobre essa data. "
            "A redação atual não será apresentada como se fosse a redação histórica."
        ),
        "historical_publication_outside_scope": (
            "Não consegui confirmar que a norma já havia sido publicada na data selecionada. "
            "Sem essa confirmação, não vou atribuir uma redação a esse período."
        ),
        "ambiguous_historical_norma_scope": (
            "A pergunta inclui mais de uma norma e a data histórica pode corresponder a redações diferentes. "
            "Indique qual norma deseja consultar."
        ),
    }
    return messages.get(reason_code)
