"""
Cache Service for RAG optimization.

Provides Redis-based caching for:
- Query embeddings (frequent queries)
- Search results
- Performance improvements
"""

import hashlib
import json
import logging
from typing import Any

from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)


class CacheService:
    """
    Service for caching embeddings and search results using Redis.

    Caches:
    - Query embeddings (reduce Ollama API calls)
    - Search results (reduce pgvector queries)
    - Answer cache (reduce LLM generation)
    """

    # Cache key prefixes
    EMBEDDING_PREFIX = "emb:"
    SEARCH_PREFIX = "search:"
    ANSWER_PREFIX = "answer:"

    # Monotonic counter mixed into every key derived from the corpus (search results
    # and answers). Bumping it invalidates them all at once and leaves query
    # embeddings alone, which depend only on the query and the model. This replaces
    # cache.clear(), which on Redis is FLUSHDB and must never touch the Celery broker
    # database.
    VERSION_KEY = "corpus_version"

    # Cache TTLs (Time To Live in seconds)
    EMBEDDING_TTL = 3600 * 24 * 7  # 7 days
    SEARCH_TTL = 3600 * 24  # 1 day
    ANSWER_TTL = 3600 * 12  # 12 hours

    def __init__(self):
        """Initialize cache service."""
        self.enabled = getattr(settings, 'CACHES', {}).get('default', {}).get('BACKEND') is not None
        if not self.enabled:
            logger.warning("Redis cache not configured, caching disabled")

    def get_corpus_version(self) -> int:
        """Current corpus version (0 when never bumped or when the cache is down)."""
        if not self.enabled:
            return 0
        try:
            return int(cache.get(self.VERSION_KEY, 0))
        except Exception as e:
            logger.warning(f"Could not read corpus version: {e}")
            return 0

    def bump_corpus_version(self) -> int | None:
        """
        Invalidate every cached search result and answer.

        Call after anything that changes what the RAG can retrieve or say
        (re-segmentation, embeddings, consolidation). Returns the new version, or
        None if the cache is unavailable (stale entries then live until their TTL).
        """
        if not self.enabled:
            return None
        try:
            cache.add(self.VERSION_KEY, 0, timeout=None)
            return cache.incr(self.VERSION_KEY)
        except Exception as e:
            logger.error(f"Could not bump corpus version; cached answers may be stale: {e}")
            return None

    def _generate_key(self, prefix: str, text: str) -> str:
        """
        Generate cache key from text using SHA-256 hash.

        Args:
            prefix: Cache key prefix
            text: Text to hash

        Returns:
            Cache key string
        """
        text_hash = hashlib.sha256(text.encode('utf-8')).hexdigest()
        return f"{prefix}{text_hash}"

    def get_embedding(self, query_text: str, model: str) -> list[float] | None:
        """
        Get cached embedding for query text.

        Args:
            query_text: Query text
            model: Model name used for embedding

        Returns:
            Cached embedding vector or None
        """
        if not self.enabled:
            return None

        key = self._generate_key(self.EMBEDDING_PREFIX, f"{model}:{query_text}")

        try:
            cached = cache.get(key)
            if cached:
                logger.debug(f"Cache HIT for embedding: {query_text[:50]}...")
                return json.loads(cached)
            else:
                logger.debug(f"Cache MISS for embedding: {query_text[:50]}...")
                return None
        except Exception as e:
            logger.error(f"Error getting cached embedding: {e}")
            return None

    def set_embedding(self, query_text: str, model: str, embedding: list[float]) -> bool:
        """
        Cache embedding for query text.

        Args:
            query_text: Query text
            model: Model name
            embedding: Embedding vector

        Returns:
            True if cached successfully
        """
        if not self.enabled or not embedding:
            return False

        key = self._generate_key(self.EMBEDDING_PREFIX, f"{model}:{query_text}")

        try:
            cache.set(key, json.dumps(embedding), timeout=self.EMBEDDING_TTL)
            logger.debug(f"Cached embedding for: {query_text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Error caching embedding: {e}")
            return False

    def get_search_results(self, query_text: str, k: int, filters: dict[str, Any]) -> list[dict] | None:
        """
        Get cached search results.

        Args:
            query_text: Search query
            k: Number of results
            filters: Search filters (norma_id, min_similarity, etc)

        Returns:
            Cached search results or None
        """
        if not self.enabled:
            return None

        filter_str = json.dumps(filters, sort_keys=True)
        cache_input = f"v{self.get_corpus_version()}:{query_text}:k={k}:{filter_str}"
        key = self._generate_key(self.SEARCH_PREFIX, cache_input)

        try:
            cached = cache.get(key)
            if cached:
                logger.debug(f"Cache HIT for search: {query_text[:50]}...")
                return json.loads(cached)
            else:
                logger.debug(f"Cache MISS for search: {query_text[:50]}...")
                return None
        except Exception as e:
            logger.error(f"Error getting cached search results: {e}")
            return None

    def set_search_results(
        self,
        query_text: str,
        k: int,
        filters: dict[str, Any],
        results: list[dict]
    ) -> bool:
        """
        Cache search results.

        Args:
            query_text: Search query
            k: Number of results
            filters: Search filters
            results: Search results to cache

        Returns:
            True if cached successfully
        """
        if not self.enabled or not results:
            return False

        filter_str = json.dumps(filters, sort_keys=True)
        cache_input = f"v{self.get_corpus_version()}:{query_text}:k={k}:{filter_str}"
        key = self._generate_key(self.SEARCH_PREFIX, cache_input)

        try:
            # Serialize results (remove non-serializable objects)
            serializable_results = []
            for result in results:
                serializable_results.append({
                    'dispositivo_id': result['dispositivo'].id,
                    'similarity_score': result['similarity_score'],
                    'distance': result['distance'],
                    'context': result['context'],
                    'embedding_model': result['embedding_model']
                })

            cache.set(key, json.dumps(serializable_results), timeout=self.SEARCH_TTL)
            logger.debug(f"Cached search results for: {query_text[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Error caching search results: {e}")
            return False

    def get_answer(
        self,
        question: str,
        k: int,
        model: str,
        corpus_version: int | None = None,
        retrieval_fingerprint: str = ""
    ) -> dict[str, Any] | None:
        """
        Get cached RAG answer.

        Args:
            question: User question
            k: Number of context items
            model: LLM model name
            corpus_version: Version captured by the caller (defaults to the current one)

        Returns:
            Cached answer dictionary or None
        """
        if not self.enabled:
            return None

        if corpus_version is None:
            corpus_version = self.get_corpus_version()
        cache_input = f"v{corpus_version}:{question}:k={k}:model={model}:retrieval={retrieval_fingerprint}"
        key = self._generate_key(self.ANSWER_PREFIX, cache_input)

        try:
            cached = cache.get(key)
            if cached:
                logger.info(f"Cache HIT for answer: {question[:50]}...")
                return json.loads(cached)
            else:
                logger.debug(f"Cache MISS for answer: {question[:50]}...")
                return None
        except Exception as e:
            logger.error(f"Error getting cached answer: {e}")
            return None

    def set_answer(
        self,
        question: str,
        k: int,
        model: str,
        answer_data: dict[str, Any],
        corpus_version: int | None = None,
        retrieval_fingerprint: str = ""
    ) -> bool:
        """
        Cache RAG answer.

        Args:
            question: User question
            k: Number of context items
            model: LLM model name
            answer_data: Answer dictionary to cache
            corpus_version: Version read BEFORE generating the answer. If the corpus
                changes while a slow generation runs, the result lands under the old
                version and is never served as fresh.

        Returns:
            True if cached successfully
        """
        if not self.enabled or not answer_data:
            return False

        if corpus_version is None:
            corpus_version = self.get_corpus_version()
        cache_input = f"v{corpus_version}:{question}:k={k}:model={model}:retrieval={retrieval_fingerprint}"
        key = self._generate_key(self.ANSWER_PREFIX, cache_input)

        try:
            # Serialize answer and sources (remove non-serializable objects)
            serializable_sources = []
            for src in answer_data.get('sources', []):
                if isinstance(src, dict):
                    disp = src.get('dispositivo')
                    if disp and hasattr(disp, 'id'):
                        serializable_sources.append({
                            'dispositivo_id': disp.id,
                            'similarity_score': float(src.get('similarity_score') if src.get('similarity_score') is not None else 0.0),
                            'distance': float(src.get('distance') if src.get('distance') is not None else 0.0),
                            'context': src.get('context', ''),
                            'embedding_model': src.get('embedding_model', ''),
                            'identifier': disp.get_full_identifier() if hasattr(disp, 'get_full_identifier') else '',
                            'texto': disp.texto if hasattr(disp, 'texto') else ''
                        })
                    else:
                        serializable_sources.append(src)

            serializable_answer = {
                'answer': answer_data['answer'],
                'source_relevance': float(
                    answer_data.get('source_relevance', answer_data.get('confidence', 0.0)) or 0.0
                ),
                'confidence': answer_data.get('confidence'),
                'model': answer_data.get('model', model),
                'context_length': answer_data.get('context_length', 0),
                'sources': serializable_sources,
                'grounded': bool(answer_data.get('grounded', True)),
                'cached': True
            }

            cache.set(key, json.dumps(serializable_answer), timeout=self.ANSWER_TTL)
            logger.debug(f"Cached answer for: {question[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Error caching answer: {e}")
            return False

    def clear_cache(self, prefix: str | None = None) -> bool:
        """
        Invalidate cached answers and search results (corpus-derived entries).

        Implemented by bumping the corpus version, NOT with cache.clear(): on Redis
        that is FLUSHDB, which would also delete the Celery queue stored in the same
        database. Query embeddings are kept on purpose (they do not depend on the
        corpus). A prefix is only accepted for the corpus-derived kinds.

        Args:
            prefix: SEARCH_PREFIX, ANSWER_PREFIX or None (both)

        Returns:
            True if the entries were invalidated, False otherwise
        """
        if not self.enabled:
            return False
        if prefix not in (None, self.SEARCH_PREFIX, self.ANSWER_PREFIX):
            logger.warning(f"clear_cache: unsupported prefix {prefix!r}; nothing cleared")
            return False
        return self.bump_corpus_version() is not None

    def get_stats(self) -> dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with cache stats
        """
        return {
            'enabled': self.enabled,
            'backend': getattr(settings, 'CACHES', {}).get('default', {}).get('BACKEND', 'Not configured'),
            'ttl': {
                'embedding': self.EMBEDDING_TTL,
                'search': self.SEARCH_TTL,
                'answer': self.ANSWER_TTL
            }
        }


# Singleton instance
_cache_service = None

def get_cache_service() -> CacheService:
    """
    Get singleton CacheService instance.

    Returns:
        CacheService instance
    """
    global _cache_service
    if _cache_service is None:
        _cache_service = CacheService()
    return _cache_service

