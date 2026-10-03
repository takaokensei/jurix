"""Security and lifecycle contracts for per-turn generation cancellation."""

import json
from unittest.mock import patch

import pytest
from django.conf import settings
from django.contrib.auth.models import AnonymousUser, User
from django.contrib.sessions.backends.db import SessionStore
from django.core.cache import cache
from django.middleware.csrf import _get_new_csrf_string
from django.test import Client, RequestFactory

from src.apps.legislation import api_views
from src.apps.legislation.models import ChatMessage, ChatTurn
from src.processing.adaptive_rag_service import AdaptiveRAGService
from src.processing.generation_control import (
    finish_generation,
    is_generation_cancelled,
    register_generation,
)
from src.processing.rag_answer_pipeline import GenerationCancelled, run_grounded_generation

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def clear_generation_control_cache():
    cache.clear()
    yield
    cache.clear()


def _request_for(user=None, session=None):
    request = RequestFactory().post("/api/v1/search/cancel/")
    request.user = user or AnonymousUser()
    request.session = session or SessionStore()
    if not request.user.is_authenticated and not request.session.session_key:
        request.session.create()
    return request


def _post_cancel(client, token, *, csrf_token=None):
    headers = {"HTTP_X_CSRFTOKEN": csrf_token} if csrf_token else {}
    return client.post(
        "/api/v1/search/cancel/",
        data=json.dumps({"cancel_token": token}),
        content_type="application/json",
        **headers,
    )


def test_cancel_token_is_scoped_to_one_turn_and_is_idempotent():
    owner = User.objects.create_user("cancel-owner", password="secret")
    request = _request_for(owner)
    first_id, first_token = register_generation(request)
    second_id, second_token = register_generation(request)
    client = Client()
    client.force_login(owner)

    first_cancel = _post_cancel(client, first_token)
    repeated_cancel = _post_cancel(client, first_token)

    assert first_cancel.status_code == 200
    assert first_cancel.json() == {"success": True, "cancelled": True, "state": "cancelled"}
    assert repeated_cancel.json() == first_cancel.json()
    assert is_generation_cancelled(first_id)
    assert not is_generation_cancelled(second_id)

    finish_generation(second_id, "completed")
    late_cancel = _post_cancel(client, second_token)
    assert late_cancel.status_code == 200
    assert late_cancel.json() == {"success": True, "cancelled": False, "state": "completed"}


def test_cancel_rejects_forged_and_other_owner_tokens():
    owner = User.objects.create_user("cancel-token-owner", password="secret")
    other = User.objects.create_user("cancel-token-other", password="secret")
    _generation_id, token = register_generation(_request_for(owner))
    owner_client = Client()
    owner_client.force_login(owner)
    other_client = Client()
    other_client.force_login(other)

    forged = _post_cancel(owner_client, token + "forged")
    cross_owner = _post_cancel(other_client, token)

    assert forged.status_code == 403
    assert cross_owner.status_code == 403


def test_anonymous_cancel_token_is_bound_to_django_session():
    session = SessionStore()
    session.create()
    _generation_id, token = register_generation(_request_for(session=session))
    owner_client = Client()
    owner_client.cookies[settings.SESSION_COOKIE_NAME] = session.session_key
    other_client = Client()

    owner_result = _post_cancel(owner_client, token)
    other_result = _post_cancel(other_client, token)

    assert owner_result.status_code == 200
    assert owner_result.json()["cancelled"] is True
    assert other_result.status_code == 403


def test_cancel_token_expires_after_ten_minutes():
    owner = User.objects.create_user("cancel-expiry-owner", password="secret")
    with patch("django.core.signing.time.time", return_value=1_000):
        _generation_id, token = register_generation(_request_for(owner))
    client = Client()
    client.force_login(owner)

    with patch("django.core.signing.time.time", return_value=1_601):
        response = _post_cancel(client, token)

    assert response.status_code == 410
    assert response.json() == {"success": False, "error": "Cancellation token expired"}


def test_cancel_endpoint_requires_csrf_for_cookie_authenticated_browser():
    owner = User.objects.create_user("cancel-csrf-owner", password="secret")
    request = _request_for(owner)
    _generation_id, token = register_generation(request)
    client = Client(enforce_csrf_checks=True)
    client.force_login(owner)

    rejected = _post_cancel(client, token)
    csrf_token = _get_new_csrf_string()
    client.cookies[settings.CSRF_COOKIE_NAME] = csrf_token
    accepted = _post_cancel(client, token, csrf_token=csrf_token)

    assert rejected.status_code == 403
    assert accepted.status_code == 200
    assert accepted.json()["cancelled"] is True


def test_stream_issues_cancel_token_in_queued_event(monkeypatch):
    class CompletedService:
        def stream_answer_question(self, *_args, **_kwargs):
            yield {
                "event": "done",
                "answer": "Resposta de teste.",
                "sources": [],
                "grounded": False,
                "grounding": {"grounded": False, "claims": [], "failed_claims": []},
            }

    monkeypatch.setattr(api_views, "RAGService", CompletedService)
    client = Client()
    response = client.post(
        "/api/v1/search/answer/stream/",
        data=json.dumps({"question": "Pergunta de teste"}),
        content_type="application/json",
    )
    events = [
        json.loads(line.removeprefix("data: "))
        for line in b"".join(response.streaming_content).decode().splitlines()
        if line.startswith("data: ")
    ]
    queued = next(event for event in events if event.get("status") == "queued")

    assert response.status_code == 200
    assert isinstance(queued.get("cancel_token"), str)
    assert queued["cancel_token"]
    assert any(event.get("type") == "done" for event in events)
    late_cancel = _post_cancel(client, queued["cancel_token"])
    assert late_cancel.status_code == 200
    assert late_cancel.json() == {"success": True, "cancelled": False, "state": "completed"}


def test_cancel_from_queued_event_stops_before_retrieval(monkeypatch):
    class DeferredService:
        started = False

        def stream_answer_question(self, *_args, **_kwargs):
            self.started = True
            yield {"event": "status", "status": "retrieving"}

    service = DeferredService()
    monkeypatch.setattr(api_views, "RAGService", lambda: service)
    client = Client()
    response = client.post(
        "/api/v1/search/answer/stream/",
        data=json.dumps({"question": "Pergunta cancelada antes da pesquisa"}),
        content_type="application/json",
    )
    events = iter(response.streaming_content)
    queued = json.loads(next(events).decode().removeprefix("data: ").strip())

    cancelled = _post_cancel(client, queued["cancel_token"])
    next_event = json.loads(next(events).decode().removeprefix("data: ").strip())

    assert cancelled.status_code == 200
    assert cancelled.json()["cancelled"] is True
    assert next_event == {"type": "status", "status": "cancelled"}
    assert service.started is False


def test_cancel_during_provider_attempt_reaches_rag_and_prevents_completed_persistence(monkeypatch):
    User.objects.create_user(username="cancel-during-generation", password="pass")
    client = Client()
    assert client.login(username="cancel-during-generation", password="pass")
    cancel_token = {"value": None}
    control_result = {"value": None}

    class GeneratingService:
        def stream_answer_question(self, *_args, should_cancel=None, **_kwargs):
            assert callable(should_cancel)
            yield {"event": "status", "status": "generating"}
            control = _post_cancel(client, cancel_token["value"])
            control_result["value"] = control.json()
            assert should_cancel() is True
            raise GenerationCancelled("synthetic cancellation")

    monkeypatch.setattr(api_views, "RAGService", GeneratingService)
    response = client.post(
        "/api/v1/search/answer/stream/",
        data=json.dumps(
            {
                "question": "Pergunta sintética cancelada durante a geração",
                "client_session_id": "test-cancel-generation",
                "client_turn_id": "a5936f90-fdb2-4e64-96a8-70f740d84d5c",
            }
        ),
        content_type="application/json",
    )
    events = iter(response.streaming_content)
    queued = json.loads(next(events).decode().removeprefix("data: ").strip())
    cancel_token["value"] = queued["cancel_token"]
    payloads = [
        json.loads(line.removeprefix("data: "))
        for chunk in events
        for line in chunk.decode().splitlines()
        if line.startswith("data: ")
    ]

    turn = ChatTurn.objects.get(client_turn_id="a5936f90-fdb2-4e64-96a8-70f740d84d5c")
    assert response.status_code == 200
    assert control_result["value"]["cancelled"] is True
    assert sum(item.get("status") == "cancelled" for item in payloads) == 1
    assert not any(item.get("status") == "completed" for item in payloads)
    assert not any(item.get("type") == "done" for item in payloads)
    assert turn.state == "cancelled"
    assert list(
        ChatMessage.objects.filter(turn=turn, role="user").values_list("content", flat=True)
    ) == ["Pergunta sintética cancelada durante a geração"]
    assert not ChatMessage.objects.filter(turn=turn, role="assistant").exists()


def test_adaptive_rag_forwards_cancel_callback_to_generation_service(monkeypatch):
    from src.processing import adaptive_rag_service
    from src.processing.adaptive_retrieval import RetrievalOptions

    service = AdaptiveRAGService.__new__(AdaptiveRAGService)
    service._options = lambda: RetrievalOptions(max_sources=3)
    service._has_unambiguous_versioned_reference = lambda _question: False

    def cancelled():
        return True

    captured = {}

    def stream_answer_question(_service, **kwargs):
        captured.update(kwargs)
        yield {"event": "status", "status": "generating"}

    monkeypatch.setattr(
        adaptive_rag_service.RAGService, "stream_answer_question", stream_answer_question
    )
    events = list(service.stream_answer_question("Pergunta", should_cancel=cancelled))

    assert events == [{"event": "status", "status": "generating"}]
    assert captured["should_cancel"] is cancelled


def test_cancel_after_grounding_validation_prevents_answer_cache_write(monkeypatch):
    from src.processing import rag_service as rag_module

    class FakeCache:
        writes = 0

        def get_corpus_version(self):
            return 1

        def get_corpus_revision_digest(self):
            return "qa-corpus"

        def get_answer(self, *_args, **_kwargs):
            return None

        def set_answer(self, *_args, **_kwargs):
            self.writes += 1

    class FakeOllama:
        def stream_text(self, *_args, **_kwargs):
            yield "Fato apoiado pela fonte."

    service = rag_module.RAGService.__new__(rag_module.RAGService)
    service.use_cache = True
    service.cache = FakeCache()
    service.ollama = FakeOllama()
    service.get_relevant_context = lambda *_args, **_kwargs: ("contexto", [{"id": 1}])
    service._source_relevance = lambda _results: 0.9
    cancelled = {"value": False}

    def validate(_answer, _results):
        cancelled["value"] = True
        return {
            "answer": "Fato apoiado pela fonte.",
            "grounded": True,
            "source_only": True,
            "grounding": {"grounded": True, "claims": [], "failed_claims": []},
        }

    service._validate_answer = validate
    monkeypatch.setattr(rag_module, "deterministic_answer", lambda *_args: None)
    with pytest.raises(GenerationCancelled):
        list(service.stream_answer_question("Pergunta", should_cancel=lambda: cancelled["value"]))

    assert service.cache.writes == 0


def test_grounded_pipeline_closes_cancelled_attempt_and_skips_retry_and_validation():
    state = {"cancelled": False, "attempts": 0, "closed": False, "validated": False}

    def stream_attempt(_prompt):
        state["attempts"] += 1
        try:
            yield "supported draft"
            state["cancelled"] = True
            yield "must not be accepted"
        finally:
            state["closed"] = True

    def validate_attempt(_answer):
        state["validated"] = True
        return {"grounded": False, "source_only": False}

    with pytest.raises(GenerationCancelled):
        run_grounded_generation(
            "prompt",
            stream_attempt=stream_attempt,
            validate_attempt=validate_attempt,
            should_cancel=lambda: state["cancelled"],
        )

    assert state == {"cancelled": True, "attempts": 1, "closed": True, "validated": False}


def test_compatible_provider_closes_response_when_cancelled_between_events(monkeypatch):
    from src.processing import llm_provider

    class FakeResponse:
        closed = False

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.closed = True

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield 'data: {"choices":[{"delta":{"content":"primeiro"}}]}'
            yield 'data: {"choices":[{"delta":{"content":"segundo"}}]}'

    response = FakeResponse()
    cancelled = {"value": False}
    monkeypatch.setattr(llm_provider.requests, "post", lambda *_args, **_kwargs: response)
    stream = llm_provider.stream_text(
        "prompt",
        {
            "provider": "openai",
            "endpoint": "https://api.openai.com/v1",
            "model": "test-model",
            "api_key": "test-key",
        },
        temperature=0,
        max_tokens=10,
        should_cancel=lambda: cancelled["value"],
    )

    assert next(stream) == "primeiro"
    cancelled["value"] = True
    with pytest.raises(StopIteration):
        next(stream)
    assert response.closed is True


def test_ollama_closes_response_when_cancelled_between_lines(monkeypatch):
    from src.llm_engine.ollama_service import OllamaService

    class FakeResponse:
        closed = False

        def raise_for_status(self):
            return None

        def iter_lines(self, decode_unicode=True):
            yield '{"response":"primeiro"}'
            yield '{"response":"segundo"}'

        def close(self):
            self.closed = True

    response = FakeResponse()
    cancelled = {"value": False}
    service = OllamaService(base_url="http://127.0.0.1:11434")
    assert service.stream_session.get_adapter("http://").max_retries.total == 0
    monkeypatch.setattr(service.stream_session, "post", lambda *_args, **_kwargs: response)
    stream = service.stream_text(
        "prompt",
        model="test-model",
        should_cancel=lambda: cancelled["value"],
    )

    assert next(stream) == "primeiro"
    cancelled["value"] = True
    with pytest.raises(StopIteration):
        next(stream)
    assert response.closed is True
