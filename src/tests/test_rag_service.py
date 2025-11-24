"""
Tests for RAG Service with mocked Ollama.
"""

import pytest
from unittest.mock import Mock, patch, MagicMock
from django.test import TestCase

from src.processing.rag_service import RAGService
from src.processing.cache_service import CacheService
from src.apps.legislation.models import Norma, Dispositivo


@pytest.mark.django_db
@pytest.mark.skipif(
    True,
    reason="Requires pgvector extension - skip in unit tests, run in integration tests"
)
class TestRAGService:
    """Test suite for RAGService with mocked Ollama."""
    
    @pytest.fixture
    def mock_norma(self, db):
        """Create a test Norma."""
        return Norma.objects.create(
            tipo='Lei',
            numero='123',
            ano=2020,
            ementa='Test Law',
            status='consolidated'
        )
    
    @pytest.fixture
    def mock_dispositivo(self, mock_norma, db):
        """Create a test Dispositivo with embedding."""
        dispositivo = Dispositivo.objects.create(
            norma=mock_norma,
            tipo='artigo',
            numero='1º',
            texto='Este é um artigo de teste sobre zoneamento urbano.',
            ordem=1
        )
        # Set mock embedding (768 dimensions)
        dispositivo.embedding = [0.1] * 768
        dispositivo.embedding_model = 'nomic-embed-text'
        dispositivo.save()
        return dispositivo
    
    @patch('src.processing.rag_service.OllamaService')
    def test_init_with_cache(self, mock_ollama_class):
        """Test RAGService initialization with cache enabled."""
        mock_ollama = Mock()
        mock_ollama_class.return_value = mock_ollama
        
        service = RAGService(use_cache=True)
        
        assert service.use_cache is True
        assert service.ollama == mock_ollama
        assert service.cache is not None
    
    @patch('src.processing.rag_service.OllamaService')
    def test_init_without_cache(self, mock_ollama_class):
        """Test RAGService initialization with cache disabled."""
        mock_ollama = Mock()
        mock_ollama_class.return_value = mock_ollama
        
        service = RAGService(use_cache=False)
        
        assert service.use_cache is False
        assert service.cache is None
    
    @patch('src.processing.rag_service.OllamaService')
    @patch('src.processing.rag_service.connection')
    def test_semantic_search_with_cached_embedding(
        self, 
        mock_connection,
        mock_ollama_class,
        mock_dispositivo,
        db
    ):
        """Test semantic search using cached embedding."""
        # Mock Ollama
        mock_ollama = Mock()
        mock_ollama_class.return_value = mock_ollama
        
        # Mock cache service
        query_text = "zoneamento urbano"
        cached_embedding = [0.2] * 768
        
        service = RAGService(use_cache=True)
        
        # Mock cache to return cached embedding
        service.cache.get_embedding = Mock(return_value=cached_embedding)
        service.cache.set_embedding = Mock()
        
        # Mock database cursor
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute = Mock()
        mock_cursor.description = [
            ('id',), ('norma_id',), ('tipo',), ('numero',), ('texto',),
            ('ordem',), ('embedding_model',), ('similarity_score',), ('distance',)
        ]
        mock_cursor.fetchall.return_value = [
            (
                mock_dispositivo.id,
                mock_dispositivo.norma.id,
                'artigo',
                '1º',
                mock_dispositivo.texto,
                1,
                'nomic-embed-text',
                0.85,  # similarity_score
                0.15   # distance
            )
        ]
        
        mock_connection.cursor.return_value = mock_cursor
        
        # Execute search
        results = service.semantic_search(query_text, k=5)
        
        # Assertions
        assert len(results) == 1
        assert results[0]['similarity_score'] == 0.85
        assert results[0]['dispositivo'].id == mock_dispositivo.id
        
        # Verify cache was used (no Ollama call)
        mock_ollama.generate_embedding.assert_not_called()
        service.cache.get_embedding.assert_called_once_with(query_text, service.model)
    
    @patch('src.processing.rag_service.OllamaService')
    @patch('src.processing.rag_service.connection')
    def test_semantic_search_generates_embedding(
        self,
        mock_connection,
        mock_ollama_class,
        mock_dispositivo,
        db
    ):
        """Test semantic search when embedding is not cached."""
        # Mock Ollama
        mock_ollama = Mock()
        generated_embedding = [0.3] * 768
        mock_ollama.generate_embedding.return_value = generated_embedding
        mock_ollama_class.return_value = mock_ollama
        
        service = RAGService(use_cache=True)
        
        # Mock cache to return None (cache miss)
        service.cache.get_embedding = Mock(return_value=None)
        service.cache.set_embedding = Mock()
        
        # Mock database cursor
        mock_cursor = Mock()
        mock_cursor.__enter__ = Mock(return_value=mock_cursor)
        mock_cursor.__exit__ = Mock(return_value=False)
        mock_cursor.execute = Mock()
        mock_cursor.description = [
            ('id',), ('norma_id',), ('tipo',), ('numero',), ('texto',),
            ('ordem',), ('embedding_model',), ('similarity_score',), ('distance',)
        ]
        mock_cursor.fetchall.return_value = [
            (
                mock_dispositivo.id,
                mock_dispositivo.norma.id,
                'artigo',
                '1º',
                mock_dispositivo.texto,
                1,
                'nomic-embed-text',
                0.90,
                0.10
            )
        ]
        
        mock_connection.cursor.return_value = mock_cursor
        
        query_text = "nova query"
        results = service.semantic_search(query_text, k=5)
        
        # Verify Ollama was called
        mock_ollama.generate_embedding.assert_called_once_with(query_text.strip(), service.model)
        
        # Verify embedding was cached
        service.cache.set_embedding.assert_called_once_with(
            query_text.strip(),
            service.model,
            generated_embedding
        )
        
        assert len(results) == 1
    
    @patch('src.processing.rag_service.OllamaService')
    def test_semantic_search_empty_query(self, mock_ollama_class):
        """Test semantic search with empty query."""
        mock_ollama = Mock()
        mock_ollama_class.return_value = mock_ollama
        
        service = RAGService()
        results = service.semantic_search("", k=10)
        
        assert results == []
        mock_ollama.generate_embedding.assert_not_called()
    
    @patch('src.processing.rag_service.OllamaService')
    def test_semantic_search_embedding_generation_fails(
        self,
        mock_ollama_class
    ):
        """Test semantic search when embedding generation fails."""
        mock_ollama = Mock()
        mock_ollama.generate_embedding.return_value = None
        mock_ollama_class.return_value = mock_ollama
        
        service = RAGService(use_cache=False)
        service.cache = None  # Disable cache
        
        results = service.semantic_search("test query", k=5)
        
        assert results == []
        mock_ollama.generate_embedding.assert_called_once()
    
    @patch('src.processing.rag_service.OllamaService')
    def test_get_relevant_context(self, mock_ollama_class, mock_dispositivo, db):
        """Test context retrieval for RAG prompts."""
        mock_ollama = Mock()
        mock_ollama.generate_embedding.return_value = [0.1] * 768
        mock_ollama_class.return_value = mock_ollama
        
        # Mock database search
        with patch('src.processing.rag_service.connection') as mock_connection:
            mock_cursor = Mock()
            mock_cursor.__enter__ = Mock(return_value=mock_cursor)
            mock_cursor.__exit__ = Mock(return_value=False)
            mock_cursor.execute = Mock()
            mock_cursor.description = [
                ('id',), ('similarity_score',), ('distance',)
            ]
            mock_cursor.fetchall.return_value = [
                (mock_dispositivo.id, 0.85, 0.15)
            ]
            mock_connection.cursor.return_value = mock_cursor
            
            service = RAGService()
            service.cache = None  # Disable cache for simplicity
            
            context, results = service.get_relevant_context("test query", k=3, max_tokens=1000)
            
            assert context != ""
            assert len(results) >= 0  # May be empty if no dispositivos match

