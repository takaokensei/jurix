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
_SENTENCE_END = re.compile(r"[.!?](?=\s|$)")
_ABBREVIATION_END = re.compile(r"\b(?:art|arts|inc|incs|n|no|etc)\.$", re.IGNORECASE)
_CITATION_MARKER = re.compile(r"\s*\[\[\d{1,3}\]\]")
_PARTIAL_ANSWER_NOTICE = (
    "\n\nA resposta foi limitada ao que as fontes consultadas permitem confirmar."
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


def _complete_sentence_ends(text: str, start: int) -> Iterator[int]:
    """Yield safe validation boundaries, retaining citation markers with claims."""
    for match in _SENTENCE_END.finditer(text, start):
        end = match.end()
        if _ABBREVIATION_END.search(text[:end].rstrip()):
            continue
        while True:
            citation = _CITATION_MARKER.match(text, end)
            if not citation:
                break
            end = citation.end()
        yield end


def stream_grounded_generation(
    prompt: str,
    *,
    stream_attempt: Callable[[str], Iterable[str]],
    validate_attempt: Callable[[str], dict[str, Any]],
    should_cancel: Callable[[], bool] | None = None,
    retry_after_partial_rejection: bool = False,
    should_retry_after_partial: Callable[[str, dict[str, Any]], bool] | None = None,
    include_partial_notice: bool = True,
    revision_instruction: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Yield only complete cumulative prefixes accepted by the normal validator.

    A later unsupported sentence is never sent. If an already verified prefix
    exists, it remains the final answer with an explicit truncation notice;
    otherwise the established one-time model revision is attempted.
    The generator's return value is the same result shape as
    ``run_grounded_generation`` plus ``streamed_answer`` and ``partial``.
    """
    generation_attempts: list[dict[str, int | None]] = []
    grounding_total_ms = 0
    last_validation: dict[str, Any] = {}
    streamed_answer = ""
    validated_prefix_candidates: list[dict[str, Any]] = []

    for attempt in range(2):
        raise_if_cancelled(should_cancel)
        chunks: list[str] = []
        raw_text = ""
        checked_end = 0
        stopped_on_rejection = False
        attempt_instruction = revision_instruction or REVISION_INSTRUCTION
        generation_stream = stream_attempt(prompt + (attempt_instruction if attempt else ""))
        generation_started = time.perf_counter()
        first_chunk_ms = None
        try:
            for chunk in generation_stream:
                raise_if_cancelled(should_cancel)
                if first_chunk_ms is None:
                    first_chunk_ms = round((time.perf_counter() - generation_started) * 1000)
                chunks.append(chunk)
                raw_text += chunk
                for end in _complete_sentence_ends(raw_text, checked_end):
                    candidate = raw_text[:end].strip()
                    checked_end = end
                    if not candidate:
                        continue
                    validation_started = time.perf_counter()
                    candidate_validation = validate_attempt(candidate)
                    grounding_total_ms += round((time.perf_counter() - validation_started) * 1000)
                    raise_if_cancelled(should_cancel)
                    if not (
                        candidate_validation.get("grounded")
                        and candidate_validation.get("source_only")
                    ):
                        stopped_on_rejection = True
                        break
                    validated_prefix = str(candidate_validation.get("answer") or "").strip()
                    if not validated_prefix.startswith(streamed_answer):
                        # Citation enrichment or normalization changed an already
                        # rendered prefix; keep the earlier verified text stable.
                        if streamed_answer:
                            stopped_on_rejection = True
                            break
                        # No prior text was exposed, so wait for final validation.
                        continue
                    delta = validated_prefix[len(streamed_answer) :]
                    if delta:
                        yield {"event": "chunk", "chunk": delta, "provisional": False}
                        streamed_answer = validated_prefix
                    last_validation = candidate_validation
                if stopped_on_rejection:
                    break
        finally:
            close_stream = getattr(generation_stream, "close", None)
            if callable(close_stream):
                close_stream()

        generation_ms = round((time.perf_counter() - generation_started) * 1000)
        generation_attempts.append(
            {
                "attempt": attempt + 1,
                "duration_ms": generation_ms,
                "time_to_first_chunk_ms": first_chunk_ms,
                "output_characters": sum(len(part) for part in chunks),
            }
        )
        raise_if_cancelled(should_cancel)

        if stopped_on_rejection and streamed_answer:
            retry_partial = retry_after_partial_rejection and attempt == 0
            if retry_partial and should_retry_after_partial is not None:
                retry_partial = bool(
                    should_retry_after_partial(streamed_answer, last_validation)
                )
            if retry_partial:
                # Callers that buffer chunks (for example, a broad overview
                # awaiting a complete-scope check) may discard this validated
                # prefix from the stream while retaining it for a later,
                # caller-specific breadth check after the revision attempt.
                if (
                    streamed_answer
                    and last_validation.get("grounded")
                    and last_validation.get("source_only")
                ):
                    validated_prefix_candidates.append({
                        "answer": streamed_answer,
                        "grounding": last_validation.get("grounding", {}),
                        "source_only": True,
                    })
                streamed_answer = ""
                last_validation = {}
                continue
            validated_prefix = streamed_answer
            answer = validated_prefix + (
                _PARTIAL_ANSWER_NOTICE if include_partial_notice else ""
            )
            if include_partial_notice:
                yield {"event": "chunk", "chunk": _PARTIAL_ANSWER_NOTICE, "provisional": False}
            return {
                "answer": answer,
                "validated_prefix": validated_prefix,
                "validated_prefix_candidates": [
                    *validated_prefix_candidates,
                    {
                        "answer": validated_prefix,
                        "grounding": last_validation.get("grounding", {}),
                        "source_only": True,
                    },
                ],
                "grounding": last_validation.get("grounding", {}),
                "source_only": True,
                "generation_attempts": generation_attempts,
                "grounding_ms": grounding_total_ms,
                "streamed_answer": answer,
                "partial": True,
            }

        validation_started = time.perf_counter()
        final_validation = validate_attempt("".join(chunks))
        grounding_total_ms += round((time.perf_counter() - validation_started) * 1000)
        raise_if_cancelled(should_cancel)
        if final_validation.get("grounded") and final_validation.get("source_only"):
            answer = str(final_validation.get("answer") or "")
            if answer.startswith(streamed_answer):
                for chunk in iter_answer_chunks(answer[len(streamed_answer) :]):
                    raise_if_cancelled(should_cancel)
                    yield {"event": "chunk", "chunk": chunk, "provisional": False}
                    streamed_answer += chunk
                return {
                    "answer": answer,
                    "grounding": final_validation.get("grounding", {}),
                    "source_only": True,
                    "generation_attempts": generation_attempts,
                    "grounding_ms": grounding_total_ms,
                    "streamed_answer": answer,
                    "partial": False,
                }

        if streamed_answer:
            validated_prefix = streamed_answer
            answer = validated_prefix + (
                _PARTIAL_ANSWER_NOTICE if include_partial_notice else ""
            )
            if include_partial_notice:
                yield {"event": "chunk", "chunk": _PARTIAL_ANSWER_NOTICE, "provisional": False}
            return {
                "answer": answer,
                "validated_prefix": validated_prefix,
                "validated_prefix_candidates": [
                    *validated_prefix_candidates,
                    {
                        "answer": validated_prefix,
                        "grounding": last_validation.get("grounding", {}),
                        "source_only": True,
                    },
                ],
                "grounding": last_validation.get("grounding", {}),
                "source_only": True,
                "generation_attempts": generation_attempts,
                "grounding_ms": grounding_total_ms,
                "streamed_answer": answer,
                "partial": True,
            }

        last_validation = final_validation
        if final_validation.get("grounded") and final_validation.get("source_only"):
            break

    return {
        "answer": last_validation.get("answer", ""),
        "validated_prefix": (
            validated_prefix_candidates[-1]["answer"]
            if validated_prefix_candidates
            else ""
        ),
        "grounding": last_validation.get("grounding", {}),
        "source_only": bool(last_validation.get("source_only")),
        "generation_attempts": generation_attempts,
        "grounding_ms": grounding_total_ms,
        "streamed_answer": streamed_answer,
        "validated_prefix_candidates": validated_prefix_candidates,
        "partial": bool(validated_prefix_candidates),
    }


def forward_grounded_generation(
    events: Iterator[dict[str, Any]],
) -> Iterator[dict[str, Any]]:
    """Forward validated answer chunks and return both the result and visible text."""
    streamed_answer = ""
    while True:
        try:
            event = next(events)
        except StopIteration as completed:
            return completed.value, streamed_answer
        if event.get("event") == "chunk":
            streamed_answer += event.get("chunk", "")
            yield event


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
