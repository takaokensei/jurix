"""Pure orchestration for generating and validating grounded RAG answers.

The caller supplies model streaming and evidence-validation callbacks so this
module remains independent of Django models, persistence, and provider setup.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterable, Iterator
from typing import Any

REVISION_INSTRUCTION = (
    "\n\nREVISÃO OBRIGATÓRIA: sua resposta anterior foi rejeitada porque continha "
    "afirmações não demonstradas pelo contexto. Reescreva usando apenas frases "
    "diretamente apoiadas pelos dispositivos acima. Não mencione ausência, "
    "exclusividade, completude ou consequências que não estejam literalmente "
    "no contexto. Entregue somente a resposta factual curta e cite o dispositivo."
)


def iter_answer_chunks(answer: str, max_chars: int = 72) -> Iterator[str]:
    """Yield a validated answer progressively without exposing ungrounded drafts."""
    words = re.findall(r"\S+\s*", str(answer or ""))
    pending = ""
    for word in words:
        if pending and len(pending) + len(word) > max_chars:
            yield pending
            pending = word
        else:
            pending += word
    if pending:
        yield pending


class GenerationCancelled(RuntimeError):
    """Raised when an authorized caller cancels a generation attempt."""


def raise_if_cancelled(should_cancel: Callable[[], bool] | None) -> None:
    if should_cancel is not None and should_cancel():
        raise GenerationCancelled("Generation cancelled by its owner.")


def run_grounded_generation(
    prompt: str,
    *,
    stream_attempt: Callable[[str], Iterable[str]],
    validate_attempt: Callable[[str], dict[str, Any]],
    should_cancel: Callable[[], bool] | None = None,
) -> dict[str, Any]:
    """Run the existing two-attempt generation/grounding contract.

    Timing boundaries and retry behavior intentionally match RAGService's
    previous inline implementation.
    """
    generation_attempts: list[dict[str, int | None]] = []
    grounding_total_ms = 0
    validation: dict[str, Any] = {}

    for attempt in range(2):
        raise_if_cancelled(should_cancel)
        attempt_prompt = prompt + (REVISION_INSTRUCTION if attempt else "")
        chunks: list[str] = []
        generation_stream = stream_attempt(attempt_prompt)
        generation_started = time.perf_counter()
        first_chunk_ms = None
        try:
            for chunk in generation_stream:
                raise_if_cancelled(should_cancel)
                if first_chunk_ms is None:
                    first_chunk_ms = round((time.perf_counter() - generation_started) * 1000)
                chunks.append(chunk)
        finally:
            close_stream = getattr(generation_stream, "close", None)
            if callable(close_stream):
                close_stream()
        raise_if_cancelled(should_cancel)
        generation_ms = round((time.perf_counter() - generation_started) * 1000)
        generation_attempts.append(
            {
                "attempt": attempt + 1,
                "duration_ms": generation_ms,
                "time_to_first_chunk_ms": first_chunk_ms,
                "output_characters": sum(len(part) for part in chunks),
            }
        )

        grounding_started = time.perf_counter()
        validation = validate_attempt("".join(chunks))
        raise_if_cancelled(should_cancel)
        grounding_total_ms += round((time.perf_counter() - grounding_started) * 1000)
        if validation["grounded"] and validation["source_only"]:
            break

    return {
        "answer": validation["answer"],
        "grounding": validation["grounding"],
        "source_only": validation["source_only"],
        "generation_attempts": generation_attempts,
        "grounding_ms": grounding_total_ms,
    }


def stream_model_attempt(
    prompt: str,
    *,
    ollama: Any,
    model: str,
    temperature: float,
    text_provider: dict[str, Any] | None,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterable[str]:
    """Select the configured text provider without owning provider state."""
    if text_provider and text_provider.get("provider") != "ollama":
        from src.processing.llm_provider import stream_text

        return stream_text(
            prompt,
            text_provider,
            temperature=temperature,
            max_tokens=2048,
            should_cancel=should_cancel,
        )
    return ollama.stream_text(
        prompt,
        model=model,
        temperature=temperature,
        max_tokens=2048,
        should_cancel=should_cancel,
    )


def build_done_event(
    *,
    answer: str,
    sources: list[dict[str, Any]],
    source_relevance: float,
    grounded: bool,
    grounding: dict[str, Any],
    retrieval_ms: int,
    grounding_ms: int,
    total_before_done_ms: int,
    generation_attempts: list[dict[str, int | None]],
) -> dict[str, Any]:
    """Serialize the existing completed SSE event without changing its contract."""
    return {
        "event": "done",
        "answer": answer,
        "sources": sources,
        "confidence": None,
        "confidence_calibrated": False,
        "source_relevance": source_relevance,
        "grounded": grounded,
        "grounding": grounding,
        "timings_ms": {
            "retrieval": retrieval_ms,
            "generation": sum(item["duration_ms"] for item in generation_attempts),
            "grounding": grounding_ms,
            "total_before_done": total_before_done_ms,
        },
        "generation_attempts": generation_attempts,
        "cached": False,
    }


def insufficient_evidence_events(
    *,
    answer: str,
    reason_code: str | None,
    coverage: dict[str, Any],
    retrieval_ms: int,
    total_before_done_ms: Callable[[], int],
) -> Iterator[dict[str, Any]]:
    """Yield the established SSE sequence for an empty retrieval result."""
    yield {"event": "status", "status": "insufficient_evidence"}
    yield {
        "event": "sources",
        "sources": [],
        "source_relevance": 0.0,
        "cached": False,
        "reason_code": reason_code,
        "coverage": coverage,
    }
    yield {"event": "chunk", "chunk": answer, "provisional": False}
    yield {
        "event": "done",
        "answer": answer,
        "sources": [],
        "source_relevance": 0.0,
        "confidence": None,
        "confidence_calibrated": False,
        "grounded": False,
        "grounding": {
            "grounded": False,
            "score": 0.0,
            "claims": [],
            "failed_claims": [],
        },
        "timings_ms": {
            "retrieval": retrieval_ms,
            "total_before_done": total_before_done_ms(),
        },
        "generation_attempts": [],
        "reason_code": reason_code,
        "coverage": coverage,
    }
