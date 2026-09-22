"""
RAG (Retrieval-Augmented Generation) Service.

This module provides semantic search capabilities using pgvector
and Ollama embeddings for legal document retrieval.
"""

import logging
import re
from collections.abc import Generator
from typing import Any

from django.db import connection

from src.apps.legislation.models import Dispositivo
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service

logger = logging.getLogger(__name__)


class RAGService:
    """
    Service for Retrieval-Augmented Generation using semantic search.

    Provides methods for:
    - Semantic search using vector similarity
    - Context retrieval for LLM prompts
    - Ranked results by relevance
    """

    # Single source of truth for the answer prompt, shared by the batch and streaming
    # paths (they used to be two hand-copied strings and had drifted apart).
    # Placeholders are filled with str.replace, never str.format, so braces in legal text
    # or in a user question cannot break or be interpreted.
    PROMPT_TEMPLATE = """Você é um assistente jurídico especializado em legislação brasileira.

IMPORTANTE: Formate sua resposta em Markdown para melhor legibilidade:
- Use **negrito** para destacar nomes de leis, artigos e termos jurídicos importantes
- Use listas com bullet points (- ou •) para enumerar regras, requisitos ou condições
- **CRÍTICO**: Cada item de lista DEVE estar em uma linha separada. Use quebra de linha ANTES de cada bullet point
- Separe parágrafos claramente com quebras de linha duplas
- Use ### para subtítulos quando necessário organizar a resposta

EXEMPLO CORRETO:
• Item 1
• Item 2
• Item 3

EXEMPLO INCORRETO (NÃO FAÇA ISSO):
• Item 1; • Item 2; • Item 3

Com base nos seguintes dispositivos legais relevantes, responda a pergunta do usuário de forma clara e objetiva.

CONTEXTO LEGAL:
@@CONTEXT@@

PERGUNTA DO USUÁRIO:
@@QUESTION@@

INSTRUÇÕES:
- Responda em português claro e objetivo
- Cite os dispositivos específicos usando **negrito** para as referências legais
- Se não houver informação suficiente, seja honesto sobre as limitações
- NUNCA invente ou alucine informações legais

RESPOSTA:"""

    @classmethod
    def build_prompt(cls, context: str, question: str) -> str:
        """Build the LLM prompt for a question and its retrieved legal context."""
        values = {"CONTEXT": context, "QUESTION": question}
        # One pass: text that was already inserted is never scanned again, so a context
        # that happens to contain '@@QUESTION@@' is not rewritten.
        return re.sub(r"@@(CONTEXT|QUESTION)@@", lambda m: values[m.group(1)], cls.PROMPT_TEMPLATE)

    def __init__(self, model: str = "nomic-embed-text", use_cache: bool = True):
        """
        Initialize RAG service.

        Args:
            model: Ollama model to use for query embeddings
            use_cache: Enable Redis caching for embeddings and results
        """
        self.ollama = OllamaService(model=model)
        self.model = model
        self.use_cache = use_cache
        self.cache = get_cache_service() if use_cache else None

    def semantic_search(
        self,
        query_text: str,
        k: int = 10,
        norma_id: int | None = None,
        min_similarity: float = 0.0
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

        # Step 1: Try to get cached embedding
        query_embedding = None
        if self.use_cache and self.cache:
            query_embedding = self.cache.get_embedding(query_text.strip(), self.model)

        # Step 2: Generate embedding if not cached
        if not query_embedding:
            query_embedding = self.ollama.generate_embedding(query_text.strip())

            if not query_embedding:
                logger.error("Failed to generate embedding for query")
                return []

            # Cache the generated embedding
            if self.use_cache and self.cache:
                self.cache.set_embedding(query_text.strip(), self.model, query_embedding)

        logger.debug(f"Query embedding dimension: {len(query_embedding)}")

        # Step 2: Execute vector similarity search using raw SQL
        if getattr(connection, 'vendor', '') == 'sqlite':
            # Fallback for SQLite in local development without pgvector extension
            qs = Dispositivo.objects.all().select_related('norma', 'dispositivo_pai')
            if norma_id:
                qs = qs.filter(norma_id=norma_id)
            query_terms = [t.lower() for t in query_text.split() if len(t) > 2]
            results = []
            for d in qs[:50]:
                text = (d.texto or '').lower()
                matches = sum(1 for term in query_terms if term in text) if query_terms else 1
                sim = min(0.95, 0.4 + (matches / max(len(query_terms), 1)) * 0.5) if matches > 0 else 0.3
                results.append({
                    'dispositivo': d,
                    'similarity_score': sim,
                    'distance': 1.0 - sim,
                    'context': {
                        'norma': {
                            'id': d.norma.id,
                            'tipo': d.norma.tipo,
                            'numero': d.norma.numero,
                            'ano': d.norma.ano,
                            'ementa': d.norma.ementa[:200] if d.norma.ementa else None,
                        },
                        'hierarchy': d.get_caminho_completo(),
                        'parent': str(d.dispositivo_pai) if d.dispositivo_pai else None,
                    },
                    'embedding_model': 'sqlite-fallback',
                })
            results.sort(key=lambda r: r['similarity_score'], reverse=True)
            return results[:k]


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
        """

        params = [query_embedding, query_embedding]

        # Add norma filter if specified
        if norma_id:
            sql_query += " AND norma_id = %s"
            params.append(norma_id)

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
                raw_results = [
                    dict(zip(columns, row, strict=False))
                    for row in cursor.fetchall()
                ]

            logger.info(f"Found {len(raw_results)} results for semantic search")

            # Step 3: Enrich results with Dispositivo instances
            results = []
            dispositivo_ids = [r['id'] for r in raw_results]

            # Fetch all dispositivos in one query (optimization)
            dispositivos_map = {
                d.id: d
                for d in Dispositivo.objects.filter(id__in=dispositivo_ids).select_related('norma', 'dispositivo_pai')
            }

            for raw_result in raw_results:
                dispositivo_id = raw_result['id']
                dispositivo = dispositivos_map.get(dispositivo_id)

                if not dispositivo:
                    continue

                # Build context
                context = {
                    'norma': {
                        'id': dispositivo.norma.id,
                        'tipo': dispositivo.norma.tipo,
                        'numero': dispositivo.norma.numero,
                        'ano': dispositivo.norma.ano,
                        'ementa': dispositivo.norma.ementa[:200] if dispositivo.norma.ementa else None,
                    },
                    'hierarchy': dispositivo.get_caminho_completo(),
                    'parent': str(dispositivo.dispositivo_pai) if dispositivo.dispositivo_pai else None,
                }

                # Cosine similarity mathematically defined as 1 - distance, bounded to [0.0, 1.0]
                raw_distance = float(raw_result['distance'])
                normalized_score = max(0.0, min(1.0, 1.0 - raw_distance))

                results.append({
                    'dispositivo': dispositivo,
                    'similarity_score': normalized_score,
                    'distance': raw_distance,
                    'context': context,
                    'embedding_model': raw_result['embedding_model'],
                })

            return results

        except Exception as e:
            logger.error(f"Error executing semantic search: {e}", exc_info=True)
            return []

    def get_relevant_context(
        self,
        query_text: str,
        k: int = 5,
        max_tokens: int = 2000
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
        results = self.semantic_search(query_text, k=k)

        if not results:
            return "Nenhum contexto relevante encontrado.", []

        # Format context
        context_parts = []
        total_chars = 0
        max_chars = max_tokens * 4  # Rough approximation: 1 token ≈ 4 chars

        for idx, result in enumerate(results, 1):
            disp = result['dispositivo']
            score = result['similarity_score']

            # Format: [Score] Norma | Dispositivo: Texto
            part = (
                f"[{score:.2f}] {disp.norma.tipo} {disp.norma.numero}/{disp.norma.ano} | "
                f"{disp.get_full_identifier()}: {disp.texto}"
            )

            if total_chars + len(part) > max_chars:
                break

            context_parts.append(f"{idx}. {part}")
            total_chars += len(part)

        formatted_context = "\n\n".join(context_parts)

        logger.info(
            f"Generated context of {total_chars} characters "
            f"from {len(context_parts)} dispositivos"
        )

        return formatted_context, results

    def answer_question(
        self,
        question: str,
        k: int = 5,
        model: str = "llama3",
        force_refresh: bool = False
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
        logger.info(f"Answering question with RAG: '{clean_question[:100]}...'")

        # Read the corpus version BEFORE the (slow) generation: if the corpus changes
        # meanwhile, the result is stored under the old version and never served.
        corpus_version = self.cache.get_corpus_version() if (self.use_cache and self.cache) else 0

        # Step 0: Check cache if enabled and not forced to refresh
        if not force_refresh and self.use_cache and self.cache:
            cached_result = self.cache.get_answer(
                clean_question, k=k, model=model, corpus_version=corpus_version
            )
            if cached_result:
                logger.info(f"Cache HIT for RAG answer: '{clean_question[:50]}...'")
                # Rehydrate Dispositivo instances for sources if available
                cached_sources = cached_result.get('sources', [])
                disp_ids = [
                    s['dispositivo_id'] for s in cached_sources
                    if isinstance(s, dict) and s.get('dispositivo_id')
                ]
                if disp_ids:
                    disps = {
                        d.id: d for d in Dispositivo.objects.filter(id__in=disp_ids).select_related('norma', 'dispositivo_pai')
                    }
                    for s in cached_sources:
                        did = s.get('dispositivo_id')
                        if did in disps:
                            s['dispositivo'] = disps[did]
                cached_result['sources'] = cached_sources
                cached_result['cached'] = True
                return cached_result

        # Step 1: Retrieve relevant context
        context, results = self.get_relevant_context(clean_question, k=k)

        if not results:
            return {
                'answer': "Não encontrei informações relevantes para responder esta pergunta.",
                'sources': [],
                'confidence': 0.0,
                'cached': False
            }

        # Step 2: Build prompt for LLM with Markdown formatting instructions
        prompt = self.build_prompt(context, clean_question)

        # Step 3: Generate answer using LLM
        answer = self.ollama.generate_text(
            prompt=prompt,
            model=model,
            temperature=0.3,  # Lower temperature for factual answers
            max_tokens=2048  # Increased for longer, complete answers
        )

        if not answer:
            return {
                'answer': "Erro ao gerar resposta. Por favor, tente novamente.",
                'sources': results,
                'confidence': 0.0,
                'cached': False
            }

        # Step 4: Post-process markdown to fix formatting issues
        answer = self._fix_markdown_formatting(answer)

        # Calculate average confidence from similarity scores
        avg_confidence = sum(r['similarity_score'] for r in results) / len(results)

        result_payload = {
            'answer': answer.strip(),
            'sources': results,
            'confidence': avg_confidence,
            'model': model,
            'context_length': len(context),
            'cached': False
        }

        # Step 5: Save to cache if enabled
        if self.use_cache and self.cache:
            self.cache.set_answer(
                clean_question, k=k, model=model, answer_data=result_payload,
                corpus_version=corpus_version
            )

        return result_payload

    def stream_answer_question(
        self,
        question: str,
        k: int = 5,
        model: str = "llama3"
    ) -> Generator[dict[str, Any], None, None]:
        """
        Stream answer generation for legal question using RAG.
        Yields dictionaries with event types:
        - {'event': 'sources', 'sources': results, 'confidence': float, 'cached': bool}
        - {'event': 'chunk', 'chunk': str}
        - {'event': 'done', 'answer': str}
        """
        clean_question = question.strip()
        corpus_version = self.cache.get_corpus_version() if (self.use_cache and self.cache) else 0

        # Check cache first
        if self.use_cache and self.cache:
            cached_result = self.cache.get_answer(
                clean_question, k=k, model=model, corpus_version=corpus_version
            )
            if cached_result:
                cached_sources = cached_result.get('sources', [])
                disp_ids = [
                    s['dispositivo_id'] for s in cached_sources
                    if isinstance(s, dict) and s.get('dispositivo_id')
                ]
                if disp_ids:
                    disps = {
                        d.id: d for d in Dispositivo.objects.filter(id__in=disp_ids).select_related('norma', 'dispositivo_pai')
                    }
                    for s in cached_sources:
                        did = s.get('dispositivo_id')
                        if did in disps:
                            s['dispositivo'] = disps[did]
                yield {
                    'event': 'sources',
                    'sources': cached_sources,
                    'confidence': cached_result.get('confidence', 0.0),
                    'cached': True
                }
                cached_ans = cached_result.get('answer', '')
                yield {'event': 'chunk', 'chunk': cached_ans}
                yield {'event': 'done', 'answer': cached_ans}
                return

        # Retrieve relevant context
        context, results = self.get_relevant_context(clean_question, k=k)
        if not results:
            yield {
                'event': 'sources',
                'sources': [],
                'confidence': 0.0,
                'cached': False
            }
            empty_msg = "Não encontrei informações relevantes para responder esta pergunta."
            yield {'event': 'chunk', 'chunk': empty_msg}
            yield {'event': 'done', 'answer': empty_msg}
            return

        avg_confidence = sum(r['similarity_score'] for r in results) / len(results)
        yield {
            'event': 'sources',
            'sources': results,
            'confidence': avg_confidence,
            'cached': False
        }

        # Build prompt
        prompt = self.build_prompt(context, clean_question)

        full_chunks = []
        for chunk in self.ollama.stream_text(prompt, model=model, temperature=0.3, max_tokens=2048):
            full_chunks.append(chunk)
            yield {'event': 'chunk', 'chunk': chunk}

        full_answer = "".join(full_chunks)
        full_answer = self._fix_markdown_formatting(full_answer).strip()

        # Cache result
        if self.use_cache and self.cache:
            result_payload = {
                'answer': full_answer,
                'sources': results,
                'confidence': avg_confidence,
                'model': model,
                'context_length': len(context),
                'cached': False
            }
            self.cache.set_answer(
                clean_question, k=k, model=model, answer_data=result_payload,
                corpus_version=corpus_version
            )

        yield {'event': 'done', 'answer': full_answer}

    def _fix_markdown_formatting(self, text: str) -> str:
        """
        Post-process markdown to fix common formatting issues.

        Fixes:
        - Lists without proper line breaks (e.g., "• Item 1; • Item 2" → "• Item 1\n• Item 2")
        - Multiple bullet points on same line
        """
        import re

        # Fix: Multiple bullet points on same line separated by semicolons
        # Pattern: "• Text1; • Text2" → "• Text1\n• Text2"
        text = re.sub(
            r'([•\-])\s+([^•\n]+?);\s+([•\-])',
            r'\1 \2\n\3',
            text
        )

        # Fix: Multiple bullet points on same line (no semicolon, just space)
        # Pattern: "• Text1 • Text2" → "• Text1\n• Text2"
        text = re.sub(
            r'([•\-])\s+([^•\n]+?)\s+([•\-])\s+',
            r'\1 \2\n\3 ',
            text
        )

        # Fix: Ensure bullet points are on separate lines
        # Replace "; •" or "; -" with newline + bullet
        text = re.sub(r';\s+([•\-])', r'\n\1', text)

        # Fix: Ensure proper spacing before bullet points
        # Add newline before bullet if not already there
        text = re.sub(r'([^\n])([•\-])\s+', r'\1\n\2 ', text)

        # Clean up: Remove multiple consecutive newlines (max 2)
        text = re.sub(r'\n{3,}', '\n\n', text)

        return text


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

