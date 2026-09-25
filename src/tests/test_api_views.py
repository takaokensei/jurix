"""
Unit tests for legislation API views.

Verifies:
- Input validation and proper HTTP error codes
- Sanitization of 500 internal errors (no internal exception leakage)
- Non-destructive regenerate behavior
"""

import json
from unittest.mock import Mock, patch

import pytest
from django.test import RequestFactory, override_settings

from src.apps.legislation.api_views import (
    chat_session_regenerate_api,
    semantic_search_api,
)


class TestAPIViews:
    """Test suite for legislation API endpoints."""

    @pytest.fixture
    def factory(self):
        return RequestFactory()

    def test_semantic_search_requires_query(self, factory):
        """Verify semantic search returns 400 when query parameter is missing."""
        request = factory.get("/api/v1/search/semantic/")
        response = semantic_search_api(request)

        assert response.status_code == 400
        data = json.loads(response.content)
        assert data["success"] is False
        assert "Query parameter is required" in data["error"]

    @override_settings(DEBUG=False)
    @patch("src.apps.legislation.api_views.RAGService")
    def test_semantic_search_sanitizes_500_error(self, mock_rag_class, factory):
        """Verify internal exception details are not leaked in 500 responses when DEBUG=False."""
        mock_rag = Mock()
        mock_rag.semantic_search.side_effect = RuntimeError(
            "FATAL: Secret database connection password leaked!"
        )
        mock_rag_class.return_value = mock_rag

        request = factory.get("/api/v1/search/semantic/?query=zoneamento")
        response = semantic_search_api(request)

        assert response.status_code == 500
        data = json.loads(response.content)
        assert data["success"] is False
        assert "FATAL: Secret" not in data["error"]
        assert "Ocorreu um erro interno" in data["error"]

    @patch("src.apps.legislation.api_views.ChatMessage.objects.filter")
    @patch("src.apps.legislation.api_views.ChatSession.objects.get")
    @patch("src.apps.legislation.api_views.RAGService")
    def test_regenerate_does_not_delete_on_generation_failure(
        self, mock_rag_class, mock_session_get, mock_msg_filter, factory
    ):
        """Verify regenerate does not delete previous message if RAGService raises an exception."""
        user = Mock()
        user.is_authenticated = True

        mock_session = Mock()
        mock_session.id = 10
        mock_session_get.return_value = mock_session

        last_user_msg = Mock()
        last_user_msg.content = "Pergunta anterior"

        last_assistant_msg = Mock()

        def filter_side_effect(session_id, role):
            mock_qs = Mock()
            if role == "user":
                mock_qs.order_by.return_value.first.return_value = last_user_msg
            elif role == "assistant":
                mock_qs.order_by.return_value.first.return_value = last_assistant_msg
            return mock_qs

        mock_msg_filter.side_effect = filter_side_effect

        # Simulate RAG generation failure
        mock_rag = Mock()
        mock_rag.answer_question.side_effect = Exception("Ollama service timeout")
        mock_rag_class.return_value = mock_rag

        request = factory.post(
            "/api/v1/chat/sessions/10/regenerate/",
            data=json.dumps({}),
            content_type="application/json",
        )
        request.user = user

        response = chat_session_regenerate_api(request, session_id=10)

        assert response.status_code == 500
        # CRITICAL: delete() MUST NOT have been called because generation failed
        last_assistant_msg.delete.assert_not_called()
