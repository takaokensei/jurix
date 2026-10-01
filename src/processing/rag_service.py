"""
RAG (Retrieval-Augmented Generation) Service.

This module provides semantic search capabilities using pgvector
and Ollama embeddings for legal document retrieval.
"""

import logging
import re
from collections.abc import Generator
from typing import Any

from django.conf import settings
from django.db import connection

from src.apps.legislation.models import Dispositivo
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service
from src.processing.rag_contract_helpers import contract, grounding_fallback
from src.processing.rag_deterministic import deterministic_answer
from src.processing.rag_prompt import PROMPT_TEMPLATE as RAG_PROMPT_TEMPLATE
from src.processing.rag_prompt import build_prompt

_UNSUPPORTED_ABSENCE_RE = re.compile(
    r"\b(?:não\s+(?:há|existe|foi\s+encontrad[oa]|se\s+encontram)|"
    r"nenhum(?:a)?\s+(?:outro|outra)|únic[oa]|unico|única|nada\s+mais|"
    r"não\s+se\s+aplica)\b",
    re.IGNORECASE,
)

logger = logging.getLogger(__name__)


class RAGService:
    """
    Service for Retrieval-Augmented Generation using semantic search.

    Provides methods for:
    - Semantic search using vector similarity
    - Context retrieval for LLM prompts
    - Ranked results by relevance
    """

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
    ) -> list[dict[str, Any]]:
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
        if not query_text or not query_text.strip():
            logger.warning("Empty query provided for semantic search")
            return []

        logger.info(f"Performing semantic search for query: '{query_text[:100]}...'")

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
            return [
                row
                for row in rows
                if row["similarity_score"] >= min_similarity
                and (norma_id is None or row["dispositivo"].norma_id == norma_id)
                and (norma_type is None or row["dispositivo"].norma.tipo == norma_type)
                and (year is None or row["dispositivo"].norma.ano == year)
            ][:k]

        # Step 1: Try to get cached embedding
        query_embedding = None
        if self.use_cache and self.cache:
            query_embedding = self.cache.get_embedding(query_text.strip(), self.model)

        # Step 2: Generate embedding if not cached
        if not query_embedding:
            query_embedding = self.ollama.generate_embedding(query_text.strip(), model=self.model)

            if not query_embedding:
                logger.error("Failed to generate embedding for query")
                return []

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
            return []

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
                for d in Dispositivo.objects.filter(id__in=dispositivo_ids).select_related(
                    "norma", "dispositivo_pai"
                )
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

            return results

        except Exception as e:
            logger.error(f"Error executing semantic search: {e}", exc_info=True)
            return []

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
        logger.info(f"Answering question with RAG: '{clean_question[:100]}...'")

        # Read the corpus version BEFORE the (slow) generation: if the corpus changes
        # meanwhile, the result is stored under the old version and never served.
        corpus_version = self.cache.get_corpus_version() if (self.use_cache and self.cache) else 0

        from src.observability.metrics import RAG_CACHE_HITS, RAG_CACHE_MISSES

        # Step 0: Check cache if enabled and not forced to refresh
        if not force_refresh and self.use_cache and self.cache:
            cached_result = self.cache.get_answer(
                clean_question,
                k=k,
                model=model,
                corpus_version=corpus_version,
                retrieval_fingerprint=retrieval_fingerprint,
            )
            if cached_result:
                logger.info(f"Cache HIT for RAG answer: '{clean_question[:50]}...'")
                RAG_CACHE_HITS.inc()
                cached_sources = cached_result.get("sources", [])
                disp_ids = [
                    s["dispositivo_id"]
                    for s in cached_sources
                    if isinstance(s, dict) and s.get("dispositivo_id")
                ]
                if disp_ids:
                    disps = {
                        d.id: d
                        for d in Dispositivo.objects.filter(id__in=disp_ids).select_related(
                            "norma", "dispositivo_pai"
                        )
                    }
                    for s in cached_sources:
                        did = s.get("dispositivo_id")
                        if did in disps:
                            s["dispositivo"] = disps[did]
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
            return contract(
                answer="Não encontrei informações relevantes para responder esta pergunta.",
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
        source_only = self._answer_uses_only_sources(
            answer, results
        ) and not self._has_unsupported_absence_claim(answer, results)
        grounding_report = (
            self._ground_answer(answer, results)
            if source_only
            else {
                "grounded": False,
                "score": 0.0,
                "claims": [],
                "failed_claims": [
                    "A resposta contém referências ou afirmações que não foram encontradas nas fontes recuperadas."
                ],
            }
        )
        grounded = bool(grounding_report.get("grounded")) and source_only

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
            )

        return result_payload

    @staticmethod
    def _ground_answer(answer: str, results: list[dict[str, Any]]) -> dict[str, Any]:
        """Evaluate grounding of the answer against retrieved evidence."""
        from src.processing.strict_grounding import evaluate_strict_grounding

        from .grounding_service import evaluate_grounding

        baseline = evaluate_grounding(answer, results)
        if not getattr(settings, "RAG_STRICT_GROUNDING", True):
            return baseline
        strict = evaluate_strict_grounding(answer, results)
        from src.processing.rag_policy import decide_grounding, response_metadata

        policy = decide_grounding(strict, True)
        strict["grounded"] = policy.accepted
        strict["policy"] = response_metadata(policy)
        strict["baseline_score"] = baseline.get("score", 0.0)
        strict["baseline_grounded"] = baseline.get("grounded", False)
        return strict

    @staticmethod
    def _has_unsupported_absence_claim(answer: str, results: list[dict[str, Any]]) -> bool:
        """Reject completeness/absence claims unless the corpus states them explicitly."""
        if not _UNSUPPORTED_ABSENCE_RE.search(answer or ""):
            return False
        evidence = " ".join(
            str(item.get("evidence_text") or item.get("text") or item.get("full_text") or "")
            for item in results
        )
        return not _UNSUPPORTED_ABSENCE_RE.search(evidence)

    @staticmethod
    def _source_relevance(results: list[dict[str, Any]]) -> float:
        if not results:
            return 0.0
        scores = [float(item.get("similarity_score", 0.0) or 0.0) for item in results]
        return round(sum(scores) / len(scores), 4)

    def stream_answer_question(
        self,
        question: str,
        k: int = 5,
        model: str | None = None,
        retrieval_fingerprint: str = "",
        temperature: float = 0.3,
        text_provider: dict[str, Any] | None = None,
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
        model = model or settings.OLLAMA_MODEL
        if text_provider and text_provider.get("provider") != "ollama":
            model = f"{text_provider.get('provider')}:{text_provider.get('model', 'unknown')}"
        temperature = max(0.0, min(float(temperature), 1.0))
        corpus_version = self.cache.get_corpus_version() if (self.use_cache and self.cache) else 0

        yield {"event": "status", "status": "retrieving"}

        from src.observability.metrics import RAG_CACHE_HITS, RAG_CACHE_MISSES

        # Check cache first
        if self.use_cache and self.cache:
            cached_result = self.cache.get_answer(
                clean_question,
                k=k,
                model=model,
                corpus_version=corpus_version,
                retrieval_fingerprint=retrieval_fingerprint,
            )
            if cached_result:
                RAG_CACHE_HITS.inc()
                yield {"event": "status", "status": "finalizing"}
                cached_sources = cached_result.get("sources", [])
                disp_ids = [
                    s["dispositivo_id"]
                    for s in cached_sources
                    if isinstance(s, dict) and s.get("dispositivo_id")
                ]
                if disp_ids:
                    disps = {
                        d.id: d
                        for d in Dispositivo.objects.filter(id__in=disp_ids).select_related(
                            "norma", "dispositivo_pai"
                        )
                    }
                    for s in cached_sources:
                        did = s.get("dispositivo_id")
                        if did in disps:
                            s["dispositivo"] = disps[did]
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
                yield {"event": "chunk", "chunk": cached_ans, "provisional": False}
                yield {
                    "event": "done",
                    "answer": cached_ans,
                    "sources": cached_sources,
                    "source_relevance": cached_source_relevance,
                    "confidence": None,
                    "confidence_calibrated": False,
                    "grounded": bool(cached_result.get("grounded", False)),
                    "grounding": cached_result.get("grounding", {}),
                }
                return
            RAG_CACHE_MISSES.inc()

        # Retrieve relevant context
        context, results = self.get_relevant_context(clean_question, k=k)
        if not results:
            from src.observability.metrics import RAG_REQUESTS

            RAG_REQUESTS.labels("no_retrieval").inc()
            yield {"event": "status", "status": "insufficient_evidence"}
            yield {"event": "sources", "sources": [], "source_relevance": 0.0, "cached": False}
            empty_msg = "Não encontrei informações relevantes para responder esta pergunta."
            yield {"event": "chunk", "chunk": empty_msg, "provisional": False}
            yield {
                "event": "done",
                "answer": empty_msg,
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
            }
            return
        source_relevance = self._source_relevance(results)
        yield {"event": "status", "status": "reranking"}
        yield {
            "event": "sources",
            "sources": results,
            "source_relevance": source_relevance,
            "cached": False,
        }

        deterministic = deterministic_answer(clean_question, results)
        if deterministic:
            grounding_report = self._ground_answer(deterministic, results)
            yield {"event": "status", "status": "grounding"}
            is_grounded = bool(grounding_report.get("grounded"))
            final_answer = deterministic if is_grounded else grounding_fallback()
            yield {"event": "chunk", "chunk": final_answer, "provisional": False}
            yield {
                "event": "done",
                "answer": final_answer,
                "sources": results,
                "source_relevance": source_relevance,
                "confidence": None,
                "confidence_calibrated": False,
                "grounded": is_grounded,
                "grounding": grounding_report,
            }
            return

        # Build prompt
        prompt = self.build_prompt(context, clean_question)

        from src.observability.metrics import (
            RAG_GROUNDING_FAILURES,
            RAG_REQUESTS,
        )

        stream_provisional = bool(getattr(settings, "RAG_STREAM_PROVISIONAL_OUTPUT", False))
        yield {"event": "status", "status": "generating"}
        grounding_report = None
        full_answer = ""
        for attempt in range(2):
            attempt_prompt = prompt
            if attempt:
                attempt_prompt += (
                    "\n\nREVISÃO OBRIGATÓRIA: sua resposta anterior foi rejeitada porque continha "
                    "afirmações não demonstradas pelo contexto. Reescreva usando apenas frases "
                    "diretamente apoiadas pelos dispositivos acima. Não mencione ausência, "
                    "exclusividade, completude ou consequências que não estejam literalmente "
                    "no contexto. Entregue somente a resposta factual curta e cite o dispositivo."
                )
            chunks = []
            if text_provider and text_provider.get("provider") != "ollama":
                from src.processing.llm_provider import stream_text as stream_external_text

                generation_stream = stream_external_text(
                    attempt_prompt, text_provider, temperature=temperature, max_tokens=2048
                )
            else:
                generation_stream = self.ollama.stream_text(
                    attempt_prompt, model=model, temperature=temperature, max_tokens=2048
                )
            for chunk in generation_stream:
                chunks.append(chunk)
                if stream_provisional and attempt == 0:
                    yield {"event": "chunk", "chunk": chunk, "provisional": True}
            full_answer = self._fix_markdown_formatting("".join(chunks)).strip()
            source_only = self._answer_uses_only_sources(
                full_answer, results
            ) and not self._has_unsupported_absence_claim(full_answer, results)
            grounding_report = (
                self._ground_answer(full_answer, results)
                if source_only
                else {
                    "grounded": False,
                    "score": 0.0,
                    "claims": [],
                    "failed_claims": [
                        "A resposta contém referências ou afirmações que não foram encontradas nas fontes recuperadas."
                    ],
                }
            )
            if bool(grounding_report.get("grounded")) and source_only:
                break

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

        if not stream_provisional:
            yield {"event": "chunk", "chunk": final_answer, "provisional": False}

        yield {"event": "status", "status": "finalizing"}

        if is_grounded and self.use_cache and self.cache:
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
            )
        yield {
            "event": "done",
            "answer": final_answer,
            "sources": results,
            "confidence": None,
            "confidence_calibrated": False,
            "source_relevance": source_relevance,
            "grounded": is_grounded,
            "grounding": grounding_report,
        }

    def _fix_markdown_formatting(self, text: str) -> str:
        """
        Post-process markdown to fix common formatting issues.

        Fixes:
        - Lists without proper line breaks (e.g., "• Item 1; • Item 2" → "• Item 1\n• Item 2")
        - Multiple bullet points on same line
        """
        # Fix: Multiple bullet points on same line separated by semicolons
        # Pattern: "• Text1; • Text2" → "• Text1\n• Text2"
        text = re.sub(r"([•\-])\s+([^•\n]+?);\s+([•\-])", r"\1 \2\n\3", text)

        # Fix: Multiple bullet points on same line (no semicolon, just space)
        # Pattern: "• Text1 • Text2" → "• Text1\n• Text2"
        text = re.sub(r"([•\-])\s+([^•\n]+?)\s+([•\-])\s+", r"\1 \2\n\3 ", text)

        # Fix: Ensure bullet points are on separate lines
        # Replace "; •" or "; -" with newline + bullet
        text = re.sub(r";\s+([•\-])", r"\n\1", text)

        # Fix: Ensure proper spacing before bullet points
        # Add newline before bullet if not already there
        text = re.sub(r"([^\n])([•\-])\s+", r"\1\n\2 ", text)

        # Clean up: Remove multiple consecutive newlines (max 2)
        text = re.sub(r"\n{3,}", "\n\n", text)

        return text

    @staticmethod
    def _answer_uses_only_sources(answer: str, results: list[dict[str, Any]]) -> bool:
        """Reject legal citations that were not present in retrieved sources."""
        if any(result.get("attachment") for result in results):
            return True
        allowed = set()
        for result in results:
            disp = result.get("dispositivo")
            norma = getattr(disp, "norma", None)
            if norma:
                num = str(norma.numero or "").replace(".", "").strip()
                ano = str(norma.ano or "").strip()
                if num and ano:
                    allowed.add(f"{num}/{ano}")
                    allowed.add(f"{norma.numero}/{ano}")
        cited_raw = re.findall(
            r"\b(?:Lei|Decreto|Resolução|Portaria)\s*(?:n[º°o.]*\s*)?(\d[\d.]*/\d{4})",
            answer,
            re.IGNORECASE,
        )
        cited = {c.replace(".", "") for c in cited_raw}
        if not cited:
            return True
        return cited.issubset(allowed)


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
