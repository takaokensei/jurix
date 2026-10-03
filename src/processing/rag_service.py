"""
RAG (Retrieval-Augmented Generation) Service.

This module provides semantic search capabilities using pgvector
and Ollama embeddings for legal document retrieval.
"""

import logging
import time
from collections.abc import Callable, Generator
from typing import Any

from django.conf import settings
from django.db import connection

from src.apps.legislation.models import Dispositivo
from src.llm_engine.ollama_service import OllamaService
from src.observability.safe_logging import log_exception_safely
from src.processing.cache_service import CacheService, get_cache_service
from src.processing.rag_answer_pipeline import (
    build_done_event,
    insufficient_evidence_events,
    iter_answer_chunks,
    raise_if_cancelled,
    run_grounded_generation,
    stream_model_attempt,
)
from src.processing.rag_cache_helpers import hydrate_cached_sources
from src.processing.rag_contract_helpers import contract, grounding_fallback
from src.processing.rag_deterministic import deterministic_answer
from src.processing.rag_generation import (
    answer_uses_only_sources,
    fix_markdown_formatting,
    ground_answer,
    has_unsupported_absence_claim,
    source_relevance,
    validate_generated_answer,
)
from src.processing.rag_prompt import PROMPT_TEMPLATE as RAG_PROMPT_TEMPLATE
from src.processing.rag_prompt import build_prompt

logger = logging.getLogger(__name__)


def _no_retrieval_message(reason_code: str | None) -> str:
    if reason_code == "norm_not_in_corpus":
        return (
            "Não localizei essa norma no acervo do Jurix. Confira o tipo, número e ano ou "
            "consulte a fonte oficial."
        )
    if reason_code == "requested_device_not_in_corpus":
        return (
            "Não localizei esse dispositivo no acervo do Jurix. Confira a identificação ou "
            "consulte o texto oficial da norma."
        )
    if reason_code == "norm_content_not_in_corpus":
        return (
            "A norma foi identificada, mas seus dispositivos não estão disponíveis no acervo "
            "do Jurix. Consulte a fonte oficial."
        )
    return "Não encontrei informações suficientes no acervo para responder com segurança."


class RAGService:
    """
    Service for Retrieval-Augmented Generation using semantic search.

    Provides methods for:
    - Semantic search using vector similarity
    - Context retrieval for LLM prompts
    - Ranked results by relevance
    """

    _iter_answer_chunks = staticmethod(iter_answer_chunks)

    PROMPT_TEMPLATE = RAG_PROMPT_TEMPLATE

    @classmethod
    def build_prompt(cls, context: str, question: str) -> str:
        """Build the LLM prompt for a question and its retrieved legal context."""
        return build_prompt(context, question)

    @staticmethod
    def _contract(
        *,
        answer: str,
        sources: list[dict[str, Any]],
        source_relevance: float,
        grounded: bool,
        grounding: dict[str, Any],
        model: str,
        cached: bool = False,
    ) -> dict[str, Any]:
        """Keep the historical class-level contract API stable.

        The response construction lives in ``rag_contract_helpers`` so the
        synchronous and streaming paths share one implementation.  This
        facade is intentionally retained for callers and tests that used the
        previous ``RAGService._contract`` entry point.
        """
        return contract(
            answer=answer,
            sources=sources,
            source_relevance=source_relevance,
            grounded=grounded,
            grounding=grounding,
            model=model,
            cached=cached,
        )

    def __init__(self, model: str | None = None, use_cache: bool = True):
        """
        Initialize RAG service.

        Args:
            model: Ollama model to use for query embeddings
            use_cache: Enable Redis caching for embeddings and results
        """
        self.model = model or settings.OLLAMA_EMBEDDING_MODEL
        self.ollama = OllamaService(model=self.model)
        self.use_cache = use_cache
        self.cache = get_cache_service() if use_cache else None

    def semantic_search(
        self,
        query_text: str,
        k: int = 10,
        norma_id: int | None = None,
        min_similarity: float = 0.0,
        norma_type: str | None = None,
        year: int | None = None,
        include_metadata: bool = False,
    ) -> list[dict[str, Any]] | dict[str, Any]:
        """
        Perform semantic search on Dispositivos using pgvector similarity.

        This method:
        1. Generates embedding for the query text using Ollama
        2. Executes cosine similarity search using pgvector (<=> operator)
        3. Returns top-k most similar dispositivos with scores

        Args:
            query_text: The search query in natural language
            k: Number of results to return (default: 10)
            norma_id: Optional filter by specific norma ID
            min_similarity: Minimum similarity score (0-1, default: 0)

        Returns:
            List of dictionaries containing:
            - dispositivo: Dispositivo instance
            - similarity_score: Cosine similarity (0-1, higher is better)
            - distance: Vector distance (lower is better)
            - context: Additional context information
        """

        def result_with_mode(rows: list[dict[str, Any]], mode: str):
            return {"results": rows, "mode": mode} if include_metadata else rows

        if not query_text or not query_text.strip():
            logger.warning("Empty query provided for semantic search")
            return result_with_mode([], "not_executed")

        logger.info("Performing semantic search (query_length=%s)", len(query_text))

        if getattr(connection, "vendor", "") == "sqlite":
            from src.processing.adaptive_retrieval import AdaptiveRetriever, RetrievalOptions

            rows = AdaptiveRetriever(self)._lexical(
                query_text,
                max(1, k),
                RetrievalOptions(
                    norma_status="all",
                    source_scope="all",
                    norma_type=norma_type,
                    year=year,
                ),
                norma_id=norma_id,
            )
            return result_with_mode(
                [
                    row
                    for row in rows
                    if row["similarity_score"] >= min_similarity
                    and (norma_id is None or row["dispositivo"].norma_id == norma_id)
                    and (norma_type is None or row["dispositivo"].norma.tipo == norma_type)
                    and (year is None or row["dispositivo"].norma.ano == year)
                ][:k],
                "lexical",
            )

        # Step 1: Try to get cached embedding
        query_embedding = None
        if self.use_cache and self.cache:
            query_embedding = self.cache.get_embedding(query_text.strip(), self.model)

        # Step 2: Generate embedding if not cached
        if not query_embedding:
            query_embedding = self.ollama.generate_embedding(query_text.strip(), model=self.model)

            if not query_embedding:
                logger.error("Failed to generate embedding for query")
                return result_with_mode([], "unavailable")

            # Cache the generated embedding
            if self.use_cache and self.cache:
                self.cache.set_embedding(query_text.strip(), self.model, query_embedding)

        logger.debug(f"Query embedding dimension: {len(query_embedding)}")
        if len(query_embedding) != 768:
            logger.error(
                "Embedding model %s returned dimension %s; expected 768",
                self.model,
                len(query_embedding),
            )
            return result_with_mode([], "unavailable")

        # Using <=> operator for cosine distance (pgvector vector_cosine_ops)
        # Lower distance = more similar
        # Similarity = 1 - distance

        sql_query = """
            SELECT
                id,
                norma_id,
                tipo,
                numero,
                texto,
                ordem,
                embedding_model,
                GREATEST(0.0, LEAST(1.0, 1 - (embedding <=> %s::vector))) as similarity_score,
                (embedding <=> %s::vector) as distance
            FROM legislation_dispositivo
            WHERE embedding IS NOT NULL
              AND embedding_model = %s
              AND is_active = TRUE
              AND revision_fingerprint <> ''
              AND embedding_revision_fingerprint = revision_fingerprint
        """

        params = [query_embedding, query_embedding, self.model]

        # Add norma filter if specified
        if norma_id:
            sql_query += " AND norma_id = %s"
            params.append(norma_id)

        norma_table = Dispositivo._meta.get_field("norma").remote_field.model._meta.db_table
        if norma_type is not None or year is not None:
            sql_query += f" AND norma_id IN (SELECT id FROM {norma_table} WHERE 1 = 1"
            if norma_type is not None:
                sql_query += " AND tipo = %s"
                params.append(norma_type)
            if year is not None:
                sql_query += " AND ano = %s"
                params.append(year)
            sql_query += ")"

        # Filter by minimum similarity (convert to distance: distance = 1 - similarity)
        if min_similarity > 0:
            max_distance = 1 - min_similarity
            sql_query += " AND (embedding <=> %s::vector) < %s"
            params.extend([query_embedding, max_distance])

        # Order by similarity (ascending distance) and limit
        sql_query += """
            ORDER BY distance ASC
            LIMIT %s
        """
        params.append(k)

        # Execute query
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql_query, params)
                columns = [col[0] for col in cursor.description]
                raw_results = [dict(zip(columns, row, strict=False)) for row in cursor.fetchall()]

            logger.info(f"Found {len(raw_results)} results for semantic search")

            # Step 3: Enrich results with Dispositivo instances
            results = []
            dispositivo_ids = [r["id"] for r in raw_results]

            # Fetch all dispositivos in one query (optimization)
            dispositivos_map = {
                d.id: d
                for d in Dispositivo.objects.filter(
                    id__in=dispositivo_ids, is_active=True
                ).select_related("norma", "dispositivo_pai")
            }

            for raw_result in raw_results:
                dispositivo_id = raw_result["id"]
                dispositivo = dispositivos_map.get(dispositivo_id)

                if not dispositivo:
                    continue

                # Build context
                context = {
                    "norma": {
                        "id": dispositivo.norma.id,
                        "tipo": dispositivo.norma.tipo,
                        "numero": dispositivo.norma.numero,
                        "ano": dispositivo.norma.ano,
                        "ementa": dispositivo.norma.ementa[:200]
                        if dispositivo.norma.ementa
                        else None,
                    },
                    "hierarchy": dispositivo.get_caminho_completo(),
                    "parent": str(dispositivo.dispositivo_pai)
                    if dispositivo.dispositivo_pai
                    else None,
                }

                # Cosine similarity mathematically defined as 1 - distance, bounded to [0.0, 1.0]
                raw_distance = float(raw_result["distance"])
                normalized_score = max(0.0, min(1.0, 1.0 - raw_distance))

                results.append(
                    {
                        "dispositivo": dispositivo,
                        "similarity_score": normalized_score,
                        "distance": raw_distance,
                        "context": context,
                        "embedding_model": raw_result["embedding_model"],
                    }
                )

            return result_with_mode(results, "semantic")

        except Exception as e:
            log_exception_safely(logger, "Error executing semantic search", e)
            return result_with_mode([], "unavailable")

    def get_relevant_context(
        self, query_text: str, k: int = 5, max_tokens: int = 2000
    ) -> tuple[str, list[dict[str, Any]]]:
        """
        Retrieve relevant context for RAG prompting.

        Performs semantic search and formats results as context
        for LLM prompts, respecting token limits.

        Args:
            query_text: The user query
            k: Number of results to retrieve
            max_tokens: Approximate maximum tokens for context (characters * 0.25)

        Returns:
            Tuple of (formatted_context_string, results_list)
        """
        from src.processing.rag_context_builder import build_relevant_context

        return build_relevant_context(self, query_text, k=k, max_tokens=max_tokens)

    def answer_question(
        self,
        question: str,
        k: int = 5,
        model: str | None = None,
        temperature: float = 0.3,
        force_refresh: bool = False,
        retrieval_fingerprint: str = "",
    ) -> dict[str, Any]:
        """
        Answer a legal question using RAG (Retrieval + Generation).

        Combines semantic search with LLM generation to provide
        context-aware answers. Leverages Redis caching for sub-second responses.

        Args:
            question: The legal question to answer
            k: Number of relevant dispositivos to retrieve
            model: LLM model to use for generation
            force_refresh: If True, bypasses cache and re-generates

        Returns:
            Dictionary with answer, sources, and metadata
        """
        clean_question = question.strip()
        model = model or settings.OLLAMA_MODEL
        temperature = max(0.0, min(float(temperature), 1.0))
        generation_fingerprint = CacheService.generation_fingerprint(
            provider="ollama",
            model=model,
            endpoint=getattr(settings, "OLLAMA_BASE_URL", ""),
            temperature=temperature,
        )
        logger.info("Answering question with RAG (question_length=%s)", len(clean_question))

        # Read the corpus version BEFORE the (slow) generation: if the corpus changes
        # meanwhile, the result is stored under the old version and never served.
        corpus_version = self.cache.get_corpus_version() if (self.use_cache and self.cache) else 0
        corpus_revision = (
            self.cache.get_corpus_revision_digest()
            if (self.use_cache and self.cache)
            else "unavailable"
        )

        from src.observability.metrics import RAG_CACHE_HITS, RAG_CACHE_MISSES

        # Step 0: Check cache if enabled and not forced to refresh
        if not force_refresh and self.use_cache and self.cache:
            cached_result = self.cache.get_answer(
                clean_question,
                k=k,
                model=model,
                corpus_version=corpus_version,
                retrieval_fingerprint=retrieval_fingerprint,
                corpus_revision=corpus_revision,
                generation_fingerprint=generation_fingerprint,
            )
            if cached_result:
                logger.info("Cache HIT for RAG answer")
                RAG_CACHE_HITS.inc()
                cached_sources = hydrate_cached_sources(
                    cached_result.get("sources", []), dispositivo_model=Dispositivo
                )
                cached_result["sources"] = cached_sources
                cached_result["source_relevance"] = float(
                    cached_result.get(
                        "source_relevance",
                        self._source_relevance(cached_sources),
                    )
                    or 0.0
                )
                cached_result["confidence"] = None
                cached_result["confidence_calibrated"] = False
                cached_result.setdefault("grounding", {})
                cached_result["cached"] = True
                return cached_result
            RAG_CACHE_MISSES.inc()

        # Step 1: Retrieve relevant context
        context, results = self.get_relevant_context(clean_question, k=k)

        if not results:
            from src.observability.metrics import RAG_REQUESTS

            RAG_REQUESTS.labels("no_retrieval").inc()
            reason_code = getattr(results, "reason_code", None)
            response = contract(
                answer=_no_retrieval_message(reason_code),
                sources=[],
                source_relevance=0.0,
                grounded=False,
                grounding={
                    "grounded": False,
                    "score": 0.0,
                    "claims": [],
                    "failed_claims": [],
                },
                model=model,
            )
            response["reason_code"] = reason_code
            return response

        deterministic = deterministic_answer(clean_question, results)

        # Step 2: Build prompt for LLM with Markdown formatting instructions
        prompt = self.build_prompt(context, clean_question)

        # Step 3: Generate answer using LLM
        from src.observability.tracing import span

        with span("rag.generation", {"llm.model": model, "rag.context_sources": len(results)}):
            answer = deterministic or self.ollama.generate_text(
                prompt=prompt,
                model=model,
                temperature=temperature,
                max_tokens=2048,
            )

        if not answer:
            from src.observability.metrics import RAG_REQUESTS

            RAG_REQUESTS.labels("generation_empty").inc()
            return contract(
                answer="Não foi possível gerar uma resposta com segurança. Tente novamente.",
                sources=results,
                source_relevance=self._source_relevance(results),
                grounded=False,
                grounding={
                    "grounded": False,
                    "score": 0.0,
                    "claims": [],
                    "failed_claims": ["O mecanismo de geração não retornou conteúdo."],
                    "reason": "generation_empty",
                },
                model=model,
            )

        # Step 4: Post-process markdown to fix formatting issues
        answer = self._fix_markdown_formatting(answer).strip()
        if len(answer) > int(getattr(settings, "RAG_MAX_ANSWER_CHARS", 24000)):
            logger.warning(
                "RAG answer exceeds the configured output limit; strict assurance will reject it"
            )

        from src.observability.metrics import (
            RAG_GROUNDING_FAILURES,
            RAG_REQUESTS,
        )

        source_relevance = self._source_relevance(results)
        validation = self._validate_answer(answer, results)
        answer = validation["answer"]
        grounding_report = validation["grounding"]
        grounded = validation["grounded"]

        if not grounded:
            RAG_GROUNDING_FAILURES.inc()
            RAG_REQUESTS.labels("grounding_rejected").inc()
            final_answer = grounding_fallback()
        else:
            RAG_REQUESTS.labels("grounded").inc()
            final_answer = answer.strip()

        result_payload = contract(
            answer=final_answer,
            sources=results,
            source_relevance=source_relevance,
            grounded=grounded,
            grounding=grounding_report,
            model=model,
        )
        result_payload["context_length"] = len(context)

        # Only grounded answers are eligible for the durable answer cache.
        if grounded and self.use_cache and self.cache:
            self.cache.set_answer(
                clean_question,
                k=k,
                model=model,
                answer_data=result_payload,
                corpus_version=corpus_version,
                retrieval_fingerprint=retrieval_fingerprint,
                corpus_revision=corpus_revision,
                generation_fingerprint=generation_fingerprint,
            )

        return result_payload

    @staticmethod
    def _ground_answer(answer: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        return ground_answer(answer, results)

    @staticmethod
    def _has_unsupported_absence_claim(answer: str, results: list[dict[str, Any]]) -> bool:
        return has_unsupported_absence_claim(answer, results)

    @staticmethod
    def _source_relevance(results: list[dict[str, Any]]) -> float:
        return source_relevance(results)

    def stream_answer_question(
        self,
        question: str,
        k: int = 5,
        model: str | None = None,
        retrieval_fingerprint: str = "",
        temperature: float = 0.3,
        text_provider: dict[str, Any] | None = None,
        skip_cache: bool = False,
        should_cancel: Callable[[], bool] | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        """
        Stream answer generation for legal question using RAG.
        Yields dictionaries with event types:
        - {'event': 'status', 'status': str}
        - {'event': 'sources', 'sources': results, 'confidence': float, 'cached': bool}
        - {'event': 'chunk', 'chunk': str}
        - {'event': 'done', 'answer': str}
        """
        clean_question = question.strip()
        request_started = time.perf_counter()
        model = model or settings.OLLAMA_MODEL
        if text_provider and text_provider.get("provider") != "ollama":
            model = f"{text_provider.get('provider')}:{text_provider.get('model', 'unknown')}"
        temperature = max(0.0, min(float(temperature), 1.0))
        provider_name = (text_provider or {}).get("provider", "ollama")
        provider_model = (text_provider or {}).get("model") or model
        generation_fingerprint = CacheService.generation_fingerprint(
            provider=provider_name,
            model=provider_model,
            endpoint=(text_provider or {}).get("endpoint")
            or getattr(settings, "OLLAMA_BASE_URL", ""),
            temperature=temperature,
        )
        corpus_version = self.cache.get_corpus_version() if (self.use_cache and self.cache) else 0
        corpus_revision = (
            self.cache.get_corpus_revision_digest()
            if (self.use_cache and self.cache)
            else "unavailable"
        )

        raise_if_cancelled(should_cancel)
        yield {"event": "status", "status": "retrieving"}

        from src.observability.metrics import RAG_CACHE_HITS, RAG_CACHE_MISSES

        # Check cache first
        if self.use_cache and self.cache and not skip_cache:
            cache_started = time.perf_counter()
            cached_result = self.cache.get_answer(
                clean_question,
                k=k,
                model=model,
                corpus_version=corpus_version,
                retrieval_fingerprint=retrieval_fingerprint,
                corpus_revision=corpus_revision,
                generation_fingerprint=generation_fingerprint,
            )
            raise_if_cancelled(should_cancel)
            if cached_result:
                cache_ms = round((time.perf_counter() - cache_started) * 1000)
                RAG_CACHE_HITS.inc()
                yield {"event": "status", "status": "finalizing"}
                cached_sources = hydrate_cached_sources(
                    cached_result.get("sources", []), dispositivo_model=Dispositivo
                )
                cached_source_relevance = float(
                    cached_result.get(
                        "source_relevance",
                        self._source_relevance(cached_sources),
                    )
                    or 0.0
                )
                yield {
                    "event": "sources",
                    "sources": cached_sources,
                    "source_relevance": cached_source_relevance,
                    "cached": True,
                }
                cached_ans = cached_result.get("answer", "")
                for chunk in self._iter_answer_chunks(cached_ans):
                    raise_if_cancelled(should_cancel)
                    yield {"event": "chunk", "chunk": chunk, "provisional": False}
                raise_if_cancelled(should_cancel)
                yield {
                    "event": "done",
                    "answer": cached_ans,
                    "sources": cached_sources,
                    "source_relevance": cached_source_relevance,
                    "confidence": None,
                    "confidence_calibrated": False,
                    "grounded": bool(cached_result.get("grounded", False)),
                    "grounding": cached_result.get("grounding", {}),
                    "timings_ms": {
                        "cache_lookup": cache_ms,
                        "total_before_done": round((time.perf_counter() - request_started) * 1000),
                    },
                    "generation_attempts": [],
                    "cached": True,
                }
                return
            RAG_CACHE_MISSES.inc()

        # Retrieve relevant context
        retrieval_started = time.perf_counter()
        raise_if_cancelled(should_cancel)
        context, results = self.get_relevant_context(clean_question, k=k)
        raise_if_cancelled(should_cancel)
        retrieval_ms = round((time.perf_counter() - retrieval_started) * 1000)
        if not results:
            from src.observability.metrics import RAG_REQUESTS

            RAG_REQUESTS.labels("no_retrieval").inc()
            reason_code = getattr(results, "reason_code", None)
            coverage = getattr(results, "coverage", {})
            empty_msg = _no_retrieval_message(reason_code)
            yield from insufficient_evidence_events(
                answer=empty_msg,
                reason_code=reason_code,
                coverage=coverage,
                retrieval_ms=retrieval_ms,
                total_before_done_ms=lambda: round(
                    (time.perf_counter() - request_started) * 1000
                ),
            )
            return
        source_relevance = self._source_relevance(results)
        yield {"event": "status", "status": "reranking"}
        yield {
            "event": "sources",
            "sources": results,
            "source_relevance": source_relevance,
            "cached": False,
            "retrieval_strategy": next(
                (row.get("retrieval_strategy") for row in results if row.get("retrieval_strategy")),
                None,
            ),
            "coverage": next((row.get("coverage") for row in results if row.get("coverage")), None),
        }

        deterministic = deterministic_answer(clean_question, results)
        if deterministic:
            grounding_started = time.perf_counter()
            grounding_report = self._ground_answer(deterministic, results)
            grounding_ms = round((time.perf_counter() - grounding_started) * 1000)
            yield {"event": "status", "status": "grounding"}
            is_grounded = bool(grounding_report.get("grounded"))
            final_answer = deterministic if is_grounded else grounding_fallback()
            for chunk in self._iter_answer_chunks(final_answer):
                raise_if_cancelled(should_cancel)
                yield {"event": "chunk", "chunk": chunk, "provisional": False}
            raise_if_cancelled(should_cancel)
            yield {
                "event": "done",
                "answer": final_answer,
                "sources": results,
                "source_relevance": source_relevance,
                "confidence": None,
                "confidence_calibrated": False,
                "grounded": is_grounded,
                "grounding": grounding_report,
                "timings_ms": {
                    "retrieval": retrieval_ms,
                    "grounding": grounding_ms,
                    "total_before_done": round((time.perf_counter() - request_started) * 1000),
                },
                "generation_attempts": [],
            }
            return

        # Build prompt
        prompt = self.build_prompt(context, clean_question)

        from src.observability.metrics import (
            RAG_GROUNDING_FAILURES,
            RAG_REQUESTS,
        )

        yield {"event": "status", "status": "generating"}

        generation = run_grounded_generation(
            prompt,
            stream_attempt=lambda attempt_prompt: stream_model_attempt(
                attempt_prompt,
                ollama=self.ollama,
                model=model,
                temperature=temperature,
                text_provider=text_provider,
                should_cancel=should_cancel,
            ),
            validate_attempt=lambda answer: self._validate_answer(answer, results),
            should_cancel=should_cancel,
        )
        full_answer = generation["answer"]
        grounding_report = generation["grounding"]
        source_only = generation["source_only"]
        generation_attempts = generation["generation_attempts"]
        grounding_total_ms = generation["grounding_ms"]

        yield {"event": "status", "status": "grounding"}
        is_grounded = bool(grounding_report.get("grounded")) and source_only
        if not is_grounded:
            RAG_GROUNDING_FAILURES.inc()
            RAG_REQUESTS.labels("grounding_rejected").inc()
            final_answer = grounding_fallback()
            yield {"event": "status", "status": "insufficient_evidence"}
        else:
            RAG_REQUESTS.labels("grounded").inc()
            final_answer = full_answer

        # Stream only after grounding has accepted/rejected the complete model
        # output. Users still get incremental rendering, but never see a draft
        # that may later be replaced by the safe fallback.
        for chunk in self._iter_answer_chunks(final_answer):
            raise_if_cancelled(should_cancel)
            yield {"event": "chunk", "chunk": chunk, "provisional": False}

        raise_if_cancelled(should_cancel)
        yield {"event": "status", "status": "finalizing"}

        if is_grounded and self.use_cache and self.cache:
            raise_if_cancelled(should_cancel)
            result_payload = contract(
                answer=final_answer,
                sources=results,
                source_relevance=source_relevance,
                grounded=True,
                grounding=grounding_report,
                model=model,
            )
            result_payload["context_length"] = len(context)
            self.cache.set_answer(
                clean_question,
                k=k,
                model=model,
                answer_data=result_payload,
                corpus_version=corpus_version,
                retrieval_fingerprint=retrieval_fingerprint,
                corpus_revision=corpus_revision,
                generation_fingerprint=generation_fingerprint,
            )
        raise_if_cancelled(should_cancel)
        yield build_done_event(
            answer=final_answer,
            sources=results,
            source_relevance=source_relevance,
            grounded=is_grounded,
            grounding=grounding_report,
            retrieval_ms=retrieval_ms,
            grounding_ms=grounding_total_ms,
            total_before_done_ms=round((time.perf_counter() - request_started) * 1000),
            generation_attempts=generation_attempts,
        )

    def _fix_markdown_formatting(self, text: str) -> str:
        return fix_markdown_formatting(text)

    def _validate_answer(self, answer: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        return validate_generated_answer(
            answer,
            results,
            format_answer=self._fix_markdown_formatting,
            citation_policy=self._answer_uses_only_sources,
            absence_policy=self._has_unsupported_absence_claim,
            grounding_policy=self._ground_answer,
        )

    @staticmethod
    def _answer_uses_only_sources(answer: str, results: list[dict[str, Any]]) -> bool:
        return answer_uses_only_sources(answer, results)


# Convenience function for quick searches
def semantic_search(query_text: str, k: int = 10, **kwargs) -> list[dict[str, Any]]:
    """
    Convenience function for semantic search.

    Args:
        query_text: Search query
        k: Number of results
        **kwargs: Additional arguments for RAGService.semantic_search

    Returns:
        List of search results
    """
    service = RAGService()
    return service.semantic_search(query_text, k=k, **kwargs)
