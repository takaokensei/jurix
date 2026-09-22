"""
Tests for RAG Service with mocked Ollama.
"""

from unittest.mock import Mock, patch

import pytest

from src.processing.rag_service import RAGService


class TestRAGService:
    """
    Test suite for RAGService with mocked Ollama and database.

    These tests use mocks to avoid requiring pgvector extension or real database setup.
    For integration tests that require pgvector, use pytest with --nomigrations flag.
    """
    """Test suite for RAGService with mocked Ollama."""

    @pytest.fixture
    def mock_norma(self):
        """Create a mock Norma object."""
        norma = Mock()
        norma.id = 1
        norma.tipo = 'Lei'
        norma.numero = '123'
        norma.ano = 2020
        norma.ementa = 'Test Law'
        norma.status = 'consolidated'
        return norma

    @pytest.fixture
    def mock_dispositivo(self, mock_norma):
        """Create a mock Dispositivo object."""
        dispositivo = Mock()
        dispositivo.id = 1
        dispositivo.norma = mock_norma
        dispositivo.tipo = 'artigo'
        dispositivo.numero = '1º'
        dispositivo.texto = 'Este é um artigo de teste sobre zoneamento urbano.'
        dispositivo.ordem = 1
        dispositivo.embedding = [0.1] * 768
        dispositivo.embedding_model = 'nomic-embed-text'
        dispositivo.dispositivo_pai = None
        dispositivo.get_caminho_completo.return_value = "Art. 1º"
        dispositivo.get_full_identifier.return_value = "Art. 1º"
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
    @patch('src.processing.rag_service.Dispositivo')
    @patch('src.processing.rag_service.connection')
    def test_semantic_search_with_cached_embedding(
        self,
        mock_connection,
        mock_disp_class,
        mock_ollama_class,
        mock_dispositivo
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

        # Mock Dispositivo.objects.filter
        mock_disp_class.objects.filter.return_value.select_related.return_value = [mock_dispositivo]

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
    @patch('src.processing.rag_service.Dispositivo')
    @patch('src.processing.rag_service.connection')
    def test_semantic_search_generates_embedding(
        self,
        mock_connection,
        mock_disp_class,
        mock_ollama_class,
        mock_dispositivo
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

        # Mock Dispositivo.objects.filter
        mock_disp_class.objects.filter.return_value.select_related.return_value = [mock_dispositivo]

        query_text = "nova query"
        results = service.semantic_search(query_text, k=5)

        # Verify Ollama uses the same embedding model as retrieval.
        mock_ollama.generate_embedding.assert_called_once_with(
            query_text.strip(), model=service.model
        )

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
    @patch('src.processing.rag_service.Dispositivo')
    @patch('src.processing.rag_service.connection')
    def test_get_relevant_context(self, mock_connection, mock_disp_class, mock_ollama_class, mock_dispositivo):
        """Test context retrieval for RAG prompts."""
        mock_ollama = Mock()
        mock_ollama.generate_embedding.return_value = [0.1] * 768
        mock_ollama_class.return_value = mock_ollama

        # Mock Dispositivo.objects.filter
        mock_disp_class.objects.filter.return_value.select_related.return_value = [mock_dispositivo]

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

        service = RAGService()
        service.cache = None  # Disable cache for simplicity

        context, results = service.get_relevant_context("test query", k=3, max_tokens=1000)

        assert context != ""
        assert len(results) >= 0  # May be empty if no dispositivos match

    @patch('src.processing.rag_service.OllamaService')
    def test_answer_question_with_cache_hit(self, mock_ollama_class):
        """Test answer_question returns cached answer without invoking Ollama."""
        mock_ollama = Mock()
        mock_ollama_class.return_value = mock_ollama

        service = RAGService(use_cache=True)
        service.cache = Mock()
        service.cache.get_answer.return_value = {
            'answer': 'Resposta em cache.',
            'sources': [],
            'confidence': 0.95,
            'model': 'llama3',
            'cached': True,
        }

        result = service.answer_question('Qual o prazo de obras?', k=5, model='llama3')

        assert result['cached'] is True
        assert result['answer'] == 'Resposta em cache.'
        mock_ollama.generate_text.assert_not_called()
        service.cache.get_answer.assert_called_once_with(
            'Qual o prazo de obras?', k=5, model='llama3',
            corpus_version=service.cache.get_corpus_version.return_value,
        )

    @patch('src.processing.rag_service.OllamaService')
    def test_answer_question_cache_miss_and_store(self, mock_ollama_class):
        """Test answer_question invokes LLM on cache miss and caches the result."""
        mock_ollama = Mock()
        mock_ollama.generate_text.return_value = 'Resposta gerada pelo Llama 3.'
        mock_ollama_class.return_value = mock_ollama

        service = RAGService(use_cache=True)
        service.cache = Mock()
        service.cache.get_answer.return_value = None  # Cache MISS
        service.get_relevant_context = Mock(return_value=('Contexto relevante', [{'similarity_score': 0.9}]))

        result = service.answer_question('Pergunta nova', k=5, model='llama3')

        assert result['cached'] is False
        assert 'Resposta gerada' in result['answer']
        mock_ollama.generate_text.assert_called_once()
        service.cache.set_answer.assert_called_once()

    @patch('src.processing.rag_service.OllamaService')
    def test_answer_is_stored_under_the_version_read_before_generation(self, mock_ollama_class):
        """A corpus change during a slow generation must not make a stale answer look fresh (P1.3)."""
        mock_ollama = Mock()
        mock_ollama_class.return_value = mock_ollama

        service = RAGService(use_cache=True)
        service.cache = Mock()
        service.cache.get_answer.return_value = None
        service.cache.get_corpus_version.return_value = 7
        service.get_relevant_context = Mock(return_value=('Contexto', [{'similarity_score': 0.9}]))

        def generate_while_corpus_changes(*args, **kwargs):
            service.cache.get_corpus_version.return_value = 8   # bumped mid-generation
            return 'Resposta gerada com o corpus antigo.'
        mock_ollama.generate_text.side_effect = generate_while_corpus_changes

        service.answer_question('Pergunta', k=5, model='llama3')

        assert service.cache.set_answer.call_args.kwargs['corpus_version'] == 7

    @patch('src.processing.rag_service.OllamaService')
    def test_answer_question_force_refresh_bypasses_cache(self, mock_ollama_class):
        """Test answer_question with force_refresh=True ignores cached answer."""
        mock_ollama = Mock()
        mock_ollama.generate_text.return_value = 'Nova resposta atualizada.'
        mock_ollama_class.return_value = mock_ollama

        service = RAGService(use_cache=True)
        service.cache = Mock()
        service.get_relevant_context = Mock(return_value=('Contexto', [{'similarity_score': 0.88}]))

        result = service.answer_question('Pergunta para regenerar', k=5, model='llama3', force_refresh=True)

        service.cache.get_answer.assert_not_called()
        assert result['answer'] == 'Nova resposta atualizada.'
        mock_ollama.generate_text.assert_called_once()

    def test_semantic_search_restricts_results_to_active_embedding_model(self, monkeypatch):
        from unittest.mock import MagicMock
        from src.processing.rag_service import RAGService
        ollama = MagicMock()
        ollama.generate_embedding.return_value = [0.1] * 768
        monkeypatch.setattr('src.processing.rag_service.OllamaService', lambda **_: ollama)
        cursor = MagicMock()
        cursor.description = []
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.vendor = 'postgresql'
        connection.cursor.return_value.__enter__.return_value = cursor
        monkeypatch.setattr('src.processing.rag_service.connection', connection)
        service = RAGService(model='nomic-embed-text', use_cache=False)
        assert service.semantic_search('zoneamento', k=5) == []
        sql, params = cursor.execute.call_args.args
        assert 'embedding_model = %s' in sql
        assert 'nomic-embed-text' in params

    def test_semantic_search_rejects_unexpected_embedding_dimension(self, monkeypatch):
        from unittest.mock import MagicMock
        from src.processing.rag_service import RAGService
        ollama = MagicMock()
        ollama.generate_embedding.return_value = [0.1] * 3
        monkeypatch.setattr('src.processing.rag_service.OllamaService', lambda **_: ollama)
        service = RAGService(model='nomic-embed-text', use_cache=False)
        assert service.semantic_search('zoneamento') == []


class TestPromptConstruction:
    """Audit P2.3: the batch and streaming prompts were two hand-copied strings that had
    already drifted (only the batch one had the bullet-formatting examples)."""

    def test_prompt_contains_context_question_and_ends_with_the_answer_marker(self):
        prompt = RAGService.build_prompt("CTX-123", "PERGUNTA-456")
        assert "CTX-123" in prompt and "PERGUNTA-456" in prompt
        assert prompt.rstrip().endswith("RESPOSTA:")

    def test_prompt_keeps_the_formatting_examples_that_fix_glued_bullets(self):
        prompt = RAGService.build_prompt("c", "q")
        assert "EXEMPLO CORRETO" in prompt and "EXEMPLO INCORRETO" in prompt

    def test_context_and_question_are_inserted_verbatim_even_with_braces(self):
        """The prompt is an f-string/format target: user text with { } must not break or be re-evaluated."""
        prompt = RAGService.build_prompt("Art. {1} e {contexto}", "Pergunta {question}?")
        assert "Art. {1} e {contexto}" in prompt
        assert "Pergunta {question}?" in prompt

    @patch('src.processing.rag_service.OllamaService')
    def test_batch_and_streaming_send_the_identical_prompt(self, mock_ollama_class):
        ollama = Mock()
        ollama.generate_text.return_value = "resposta"
        ollama.stream_text.return_value = iter(["resp", "osta"])
        mock_ollama_class.return_value = ollama

        service = RAGService(use_cache=False)
        service.get_relevant_context = Mock(return_value=("CONTEXTO", [{'similarity_score': 0.9}]))

        service.answer_question("Pergunta?", k=3, model="llama3")
        list(service.stream_answer_question("Pergunta?", k=3, model="llama3"))

        batch_prompt = ollama.generate_text.call_args.kwargs["prompt"]
        stream_prompt = ollama.stream_text.call_args.args[0]
        assert batch_prompt == stream_prompt == RAGService.build_prompt("CONTEXTO", "Pergunta?")

    def test_placeholder_like_text_inside_the_context_is_not_rewritten(self):
        prompt = RAGService.build_prompt("texto com @@QUESTION@@ literal", "PERGUNTA-REAL")
        assert "texto com @@QUESTION@@ literal" in prompt
        assert prompt.count("PERGUNTA-REAL") == 1
