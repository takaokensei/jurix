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

from src.apps.legislation import api_search
from src.processing.generation_control import (
    finish_generation,
    is_generation_cancelled,
    register_generation,
)

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

    monkeypatch.setattr(api_search, "RAGService", CompletedService)
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
    monkeypatch.setattr(api_search, "RAGService", lambda: service)
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
