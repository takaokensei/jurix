"""
Cache Service for RAG optimization.

Provides Redis-based caching for:
- Query embeddings (frequent queries)
- Search results
- Performance improvements
"""

import logging
import json
import hashlib
from typing import Optional, List, Any, Dict
from django.core.cache import cache
from django.conf import settings

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
    
    # Cache TTLs (Time To Live in seconds)
    EMBEDDING_TTL = 3600 * 24 * 7  # 7 days
    SEARCH_TTL = 3600 * 24  # 1 day
    ANSWER_TTL = 3600 * 12  # 12 hours
    
    def __init__(self):
        """Initialize cache service."""
        self.enabled = getattr(settings, 'CACHES', {}).get('default', {}).get('BACKEND') is not None
        if not self.enabled:
            logger.warning("Redis cache not configured, caching disabled")
    
    def _generate_key(self, prefix: str, text: str) -> str:
        """
        Generate cache key from text using MD5 hash.
        
        Args:
            prefix: Cache key prefix
            text: Text to hash
            
        Returns:
            Cache key string
        """
        text_hash = hashlib.md5(text.encode('utf-8')).hexdigest()
        return f"{prefix}{text_hash}"
    
    def get_embedding(self, query_text: str, model: str) -> Optional[List[float]]:
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
    
    def set_embedding(self, query_text: str, model: str, embedding: List[float]) -> bool:
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
    
    def get_search_results(self, query_text: str, k: int, filters: Dict[str, Any]) -> Optional[List[Dict]]:
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
        cache_input = f"{query_text}:k={k}:{filter_str}"
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
        filters: Dict[str, Any],
        results: List[Dict]
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
        cache_input = f"{query_text}:k={k}:{filter_str}"
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
    
    def get_answer(self, question: str, k: int, model: str) -> Optional[Dict[str, Any]]:
        """
        Get cached RAG answer.
        
        Args:
            question: User question
            k: Number of context items
            model: LLM model name
            
        Returns:
            Cached answer dictionary or None
        """
        if not self.enabled:
            return None
        
        cache_input = f"{question}:k={k}:model={model}"
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
        answer_data: Dict[str, Any]
    ) -> bool:
        """
        Cache RAG answer.
        
        Args:
            question: User question
            k: Number of context items
            model: LLM model name
            answer_data: Answer dictionary to cache
            
        Returns:
            True if cached successfully
        """
        if not self.enabled or not answer_data:
            return False
        
        cache_input = f"{question}:k={k}:model={model}"
        key = self._generate_key(self.ANSWER_PREFIX, cache_input)
        
        try:
            # Serialize answer (remove non-serializable objects)
            serializable_answer = {
                'answer': answer_data['answer'],
                'confidence': answer_data['confidence'],
                'model': answer_data.get('model', model),
                'context_length': answer_data.get('context_length', 0),
                'cached': True
            }
            
            cache.set(key, json.dumps(serializable_answer), timeout=self.ANSWER_TTL)
            logger.debug(f"Cached answer for: {question[:50]}...")
            return True
        except Exception as e:
            logger.error(f"Error caching answer: {e}")
            return False
    
    def clear_cache(self, prefix: Optional[str] = None) -> bool:
        """
        Clear cache entries.
        
        Args:
            prefix: Cache key prefix to clear (None = clear all)
            
        Returns:
            True if successful
        """
        if not self.enabled:
            return False
        
        try:
            if prefix:
                logger.info(f"Clearing cache for prefix: {prefix}")
                # Django cache doesn't support pattern deletion natively
                # This requires custom implementation or use cache.clear()
                logger.warning("Prefix-based cache clear not implemented, use cache.clear() for all")
            else:
                cache.clear()
                logger.info("Cleared all cache")
            return True
        except Exception as e:
            logger.error(f"Error clearing cache: {e}")
            return False
    
    def get_stats(self) -> Dict[str, Any]:
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

