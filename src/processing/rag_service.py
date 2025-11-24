"""
RAG (Retrieval-Augmented Generation) Service.

This module provides semantic search capabilities using pgvector
and Ollama embeddings for legal document retrieval.
"""

import logging
from typing import List, Dict, Any, Optional, Tuple
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
        norma_id: Optional[int] = None,
        min_similarity: float = 0.0
    ) -> List[Dict[str, Any]]:
        """
        Perform semantic search on Dispositivos using pgvector similarity.
        
        This method:
        1. Generates embedding for the query text using Ollama
        2. Executes cosine similarity search using pgvector (<-> operator)
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
        # Using <-> operator for cosine distance (pgvector)
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
                GREATEST(0.0, LEAST(1.0, 1 - (embedding <-> %s::vector))) as similarity_score,
                (embedding <-> %s::vector) as distance
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
            sql_query += " AND (embedding <-> %s::vector) < %s"
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
                    dict(zip(columns, row))
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
                
                # Ensure similarity_score is normalized between 0.0 and 1.0
                raw_score = float(raw_result['similarity_score'])
                normalized_score = max(0.0, min(1.0, raw_score))
                
                results.append({
                    'dispositivo': dispositivo,
                    'similarity_score': normalized_score,
                    'distance': float(raw_result['distance']),
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
    ) -> Tuple[str, List[Dict[str, Any]]]:
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
        model: str = "llama3"
    ) -> Dict[str, Any]:
        """
        Answer a legal question using RAG (Retrieval + Generation).
        
        Combines semantic search with LLM generation to provide
        context-aware answers.
        
        Args:
            question: The legal question to answer
            k: Number of relevant dispositivos to retrieve
            model: LLM model to use for generation
            
        Returns:
            Dictionary with answer, sources, and metadata
        """
        logger.info(f"Answering question with RAG: '{question[:100]}...'")
        
        # Step 1: Retrieve relevant context
        context, results = self.get_relevant_context(question, k=k)
        
        if not results:
            return {
                'answer': "Não encontrei informações relevantes para responder esta pergunta.",
                'sources': [],
                'confidence': 0.0
            }
        
        # Step 2: Build prompt for LLM with Markdown formatting instructions
        prompt = f"""Você é um assistente jurídico especializado em legislação brasileira.

IMPORTANTE: Formate sua resposta em Markdown para melhor legibilidade:
- Use **negrito** para destacar nomes de leis, artigos e termos jurídicos importantes
- Use listas com bullet points (- ou •) para enumerar regras, requisitos ou condições
- Separe parágrafos claramente com quebras de linha duplas
- Use ### para subtítulos quando necessário organizar a resposta

Com base nos seguintes dispositivos legais relevantes, responda a pergunta do usuário de forma clara e objetiva.

CONTEXTO LEGAL:
{context}

PERGUNTA DO USUÁRIO:
{question}

INSTRUÇÕES:
- Responda em português claro e objetivo
- Cite os dispositivos específicos usando **negrito** para as referências legais
- Se não houver informação suficiente, seja honesto sobre as limitações
- NUNCA invente ou alucine informações legais

RESPOSTA:"""
        
        # Step 3: Generate answer using LLM
        answer = self.ollama.generate_text(
            prompt=prompt,
            model=model,
            temperature=0.3,  # Lower temperature for factual answers
            max_tokens=500
        )
        
        if not answer:
            return {
                'answer': "Erro ao gerar resposta. Por favor, tente novamente.",
                'sources': results,
                'confidence': 0.0
            }
        
        # Calculate average confidence from similarity scores
        avg_confidence = sum(r['similarity_score'] for r in results) / len(results)
        
        return {
            'answer': answer.strip(),
            'sources': results,
            'confidence': avg_confidence,
            'model': model,
            'context_length': len(context)
        }


# Convenience function for quick searches
def semantic_search(query_text: str, k: int = 10, **kwargs) -> List[Dict[str, Any]]:
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

