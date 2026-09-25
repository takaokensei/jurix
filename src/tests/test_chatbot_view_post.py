"""
Legacy form/JSON POST of chatbot_view (the non-streaming fallback used by chat.js).

views.py had 0% coverage, so a change to how sessions get their slug could not be verified
(audit P2.1). These tests exercise the real view against the real database with only the
LLM stubbed.
"""

from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.test import Client
from django.urls import reverse

from src.apps.legislation.models import ChatMessage, ChatSession

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user("ana", password="x")


@pytest.fixture
def client(user):
    c = Client()
    c.force_login(user)
    return c


@pytest.fixture(autouse=True)
def fake_llm(settings):
    settings.CACHES = {"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}}
    rag = MagicMock()
    rag.answer_question.return_value = {
        "answer": "Resposta.",
        "sources": [],
        "confidence": 0.8,
        "model": "llama3",
        "context_length": 5,
    }
    ollama = MagicMock()
    ollama.generate_text.return_value = "Título gerado"
    with (
        patch("src.apps.legislation.views.RAGService", return_value=rag),
        patch("src.llm_engine.ollama_service.OllamaService", return_value=ollama),
        patch("src.apps.legislation.views.OllamaService", return_value=ollama, create=True),
    ):
        yield rag


def post(client, payload):
    import json

    return client.post(
        reverse("legislation:chatbot"), data=json.dumps(payload), content_type="application/json"
    )


def test_first_question_creates_session_with_slug_and_both_messages(client, user):
    r = post(client, {"question": "Qual o prazo do alvará?"})
    body = r.json()

    assert r.status_code == 200 and body["success"] is True
    session = ChatSession.objects.get(user=user)
    assert session.slug and body["session_slug"] == session.slug
    assert body["session_id"] == session.id
    assert list(
        ChatMessage.objects.filter(session=session).order_by("id").values_list("role", flat=True)
    ) == ["user", "assistant"]


def test_follow_up_reuses_the_session_and_its_slug(client, user):
    first = post(client, {"question": "Primeira?"}).json()
    second = post(client, {"question": "Segunda?", "session_id": first["session_id"]}).json()

    assert second["session_id"] == first["session_id"]
    assert second["session_slug"] == first["session_slug"]
    assert ChatSession.objects.filter(user=user).count() == 1
    assert ChatMessage.objects.filter(session_id=first["session_id"]).count() == 4


def test_anonymous_user_gets_an_answer_without_a_session():
    c = Client()
    r = post(c, {"question": "Oi?"})
    assert r.status_code == 200
    assert r.json()["session_id"] is None and r.json()["session_slug"] is None
    assert ChatSession.objects.count() == 0


def test_invalid_and_empty_input_are_400(client):
    assert post(client, {"question": "   "}).status_code == 400
    assert post(client, {"question": "x", "k": "abc"}).status_code == 400
    assert post(client, {"question": "x", "model": "modelo-nao-permitido"}).status_code == 400


def test_server_error_does_not_leak_details(client, fake_llm):
    fake_llm.answer_question.side_effect = RuntimeError("segredo-interno")
    r = post(client, {"question": "Oi?"})
    assert r.status_code == 500
    assert (
        "segredo-interno" not in r.content.decode()
        and "traceback" not in r.content.decode().lower()
    )
