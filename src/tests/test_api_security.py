"""
Security tests for the JSON/SSE API (audit P0.1 / P0.4).

CSRF is exercised with ``Client(enforce_csrf_checks=True)``: Django's default test
client silently disables CSRF, which is how this hole went unnoticed.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from django.contrib.auth.models import User
from django.core.cache import cache
from django.test import Client
from django.urls import reverse

from src.apps.legislation.models import ChatSession

pytestmark = pytest.mark.django_db

STREAM = "/api/v1/search/answer/stream/"
ANSWER = "/api/v1/search/answer/"
SESSIONS = "/api/v1/chat/sessions/"


@pytest.fixture(autouse=True)
def locmem_cache(settings):
    """Rate limiting uses the cache; tests must not depend on a running Redis."""
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "api-security-tests",
        }
    }
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def user():
    return User.objects.create_user("vitima", password="x")


@pytest.fixture
def csrf_client(user):
    """Logged-in client that ENFORCES CSRF (like a real browser)."""
    c = Client(enforce_csrf_checks=True)
    c.force_login(user)
    return c


def _token(client):
    """Fetch the chat page the way a browser does and return the csrftoken cookie."""
    client.get(reverse("legislation:chatbot"))
    return client.cookies["csrftoken"].value


def _post_json(client, path, payload, **extra):
    return client.post(path, data=json.dumps(payload), content_type="application/json", **extra)


def _fake_rag(events=None):
    rag = MagicMock()
    rag.stream_answer_question.return_value = iter(
        events or [{"event": "done", "answer": "ok"}]
    )
    rag.answer_question.return_value = {
        "answer": "ok", "sources": [], "confidence": 0.5, "model": "llama3",
    }
    return rag


# ---------------------------------------------------------------- P0.1: CSRF
class TestCsrf:
    def test_chat_page_sets_the_csrf_cookie(self, csrf_client):
        """Without the cookie the frontend cannot send X-CSRFToken at all."""
        csrf_client.get(reverse("legislation:chatbot"))
        assert "csrftoken" in csrf_client.cookies

    def test_delete_session_without_token_is_forbidden_and_keeps_data(self, csrf_client, user):
        s = ChatSession.objects.create(user=user, title="Conversa importante")
        r = csrf_client.delete(f"{SESSIONS}{s.id}/")
        assert r.status_code == 403
        assert ChatSession.objects.filter(id=s.id).exists()

    def test_delete_session_with_token_succeeds(self, csrf_client, user):
        s = ChatSession.objects.create(user=user, title="x")
        token = _token(csrf_client)
        r = csrf_client.delete(f"{SESSIONS}{s.id}/", HTTP_X_CSRFTOKEN=token)
        assert r.status_code == 200
        assert not ChatSession.objects.filter(id=s.id).exists()

    def test_create_session_without_token_is_forbidden(self, csrf_client):
        assert _post_json(csrf_client, SESSIONS, {}).status_code == 403

    def test_regenerate_without_token_is_forbidden(self, csrf_client, user):
        s = ChatSession.objects.create(user=user, title="x")
        assert _post_json(csrf_client, f"{SESSIONS}{s.id}/regenerate/", {}).status_code == 403

    def test_stream_without_token_is_forbidden_and_writes_nothing(self, csrf_client, user):
        with patch("src.apps.legislation.api_views.RAGService", return_value=_fake_rag()):
            r = _post_json(csrf_client, STREAM, {"question": "oi"})
        assert r.status_code == 403
        assert ChatSession.objects.filter(user=user).count() == 0

    def test_stream_with_token_works(self, csrf_client):
        token = _token(csrf_client)
        with patch("src.apps.legislation.api_views.RAGService", return_value=_fake_rag()):
            r = _post_json(csrf_client, STREAM, {"question": "oi"}, HTTP_X_CSRFTOKEN=token)
            body = b"".join(r.streaming_content).decode()
        assert r.status_code == 200
        assert '"type": "done"' in body

    def test_public_answer_endpoint_needs_no_csrf_token(self):
        """Anonymous, session-less and side-effect free: nothing for CSRF to protect."""
        c = Client(enforce_csrf_checks=True)
        with patch("src.apps.legislation.api_views.RAGService", return_value=_fake_rag()):
            r = _post_json(c, ANSWER, {"question": "oi"})
        assert r.status_code == 200


# ------------------------------------------------------ P0.4: input validation
class TestLlmInputValidation:
    def _stream(self, client, payload):
        token = _token(client)
        rag = _fake_rag()
        with patch("src.apps.legislation.api_views.RAGService", return_value=rag):
            r = _post_json(client, STREAM, payload, HTTP_X_CSRFTOKEN=token)
            if r.status_code == 200:
                b"".join(r.streaming_content)
        return r, rag

    def test_k_is_clamped_to_the_configured_maximum(self, csrf_client, settings):
        settings.LLM_MAX_K = 20
        r, rag = self._stream(csrf_client, {"question": "oi", "k": 10**9})
        assert r.status_code == 200
        assert rag.stream_answer_question.call_args.kwargs["k"] == 20

    def test_k_below_one_is_raised_to_one(self, csrf_client):
        r, rag = self._stream(csrf_client, {"question": "oi", "k": -5})
        assert rag.stream_answer_question.call_args.kwargs["k"] == 1

    @pytest.mark.parametrize("bad_k", ["abc", [1], {"a": 1}, True])
    def test_non_integer_k_is_a_400(self, csrf_client, bad_k):
        r, _ = self._stream(csrf_client, {"question": "oi", "k": bad_k})
        assert r.status_code == 400

    def test_default_model_comes_from_settings(self, csrf_client, settings):
        settings.OLLAMA_MODEL = "modelo-padrao"
        settings.OLLAMA_ALLOWED_MODELS = ["modelo-padrao"]
        r, rag = self._stream(csrf_client, {"question": "oi"})
        assert rag.stream_answer_question.call_args.kwargs["model"] == "modelo-padrao"

    def test_model_outside_the_allowlist_is_rejected_before_reaching_ollama(self, csrf_client, settings):
        settings.OLLAMA_ALLOWED_MODELS = ["llama3"]
        r, rag = self._stream(csrf_client, {"question": "oi", "model": "modelo-gigante:405b"})
        assert r.status_code == 400
        rag.stream_answer_question.assert_not_called()

    def test_allowed_model_is_accepted(self, csrf_client, settings):
        settings.OLLAMA_ALLOWED_MODELS = ["llama3", "outro"]
        r, rag = self._stream(csrf_client, {"question": "oi", "model": "outro"})
        assert rag.stream_answer_question.call_args.kwargs["model"] == "outro"

    def test_question_over_the_length_limit_is_rejected(self, csrf_client, settings):
        settings.LLM_MAX_QUESTION_LENGTH = 50
        r, rag = self._stream(csrf_client, {"question": "x" * 51})
        assert r.status_code == 400
        rag.stream_answer_question.assert_not_called()

    def test_non_string_question_is_a_400_not_a_500(self, csrf_client):
        r, _ = self._stream(csrf_client, {"question": 123})
        assert r.status_code == 400

    def test_non_integer_session_id_is_a_400_not_a_500(self, csrf_client):
        r, _ = self._stream(csrf_client, {"question": "oi", "session_id": "abc"})
        assert r.status_code == 400

    def test_stream_rejects_get(self, csrf_client):
        assert csrf_client.get(STREAM).status_code == 405

    def test_public_answer_get_with_garbage_k_is_a_400_not_a_500(self):
        c = Client()
        with patch("src.apps.legislation.api_views.RAGService", return_value=_fake_rag()):
            r = c.get(ANSWER, {"question": "oi", "k": "abc"})
        assert r.status_code == 400

    def test_public_answer_rejects_disallowed_model(self, settings):
        settings.OLLAMA_ALLOWED_MODELS = ["llama3"]
        c = Client()
        rag = _fake_rag()
        with patch("src.apps.legislation.api_views.RAGService", return_value=rag):
            r = _post_json(c, ANSWER, {"question": "oi", "model": "x:70b"})
        assert r.status_code == 400
        rag.answer_question.assert_not_called()


# ------------------------------------------------------ P0.4: rate limiting
class TestRateLimit:
    def _hit(self, client, **extra):
        with patch("src.apps.legislation.api_views.RAGService", return_value=_fake_rag()):
            return _post_json(client, ANSWER, {"question": "oi"}, **extra)

    def test_requests_over_the_limit_get_429_with_retry_after(self, settings):
        settings.LLM_RATE_LIMIT_REQUESTS = 2
        settings.LLM_RATE_LIMIT_WINDOW_SECONDS = 60
        c = Client()
        assert self._hit(c).status_code == 200
        assert self._hit(c).status_code == 200
        r = self._hit(c)
        assert r.status_code == 429
        assert 1 <= int(r["Retry-After"]) <= 60
        assert r.json()["success"] is False

    def test_limit_is_per_client(self, settings):
        settings.LLM_RATE_LIMIT_REQUESTS = 1
        assert self._hit(Client(), REMOTE_ADDR="10.0.0.1").status_code == 200
        assert self._hit(Client(), REMOTE_ADDR="10.0.0.1").status_code == 429
        assert self._hit(Client(), REMOTE_ADDR="10.0.0.2").status_code == 200

    def test_limit_is_shared_across_llm_endpoints(self, settings, csrf_client):
        """Alternating endpoints must not multiply the allowance."""
        settings.LLM_RATE_LIMIT_REQUESTS = 1
        token = _token(csrf_client)
        with patch("src.apps.legislation.api_views.RAGService", return_value=_fake_rag()):
            first = _post_json(csrf_client, STREAM, {"question": "oi"}, HTTP_X_CSRFTOKEN=token)
            b"".join(first.streaming_content)
            second = _post_json(csrf_client, ANSWER, {"question": "oi"})
        assert first.status_code == 200
        assert second.status_code == 429

    def test_zero_disables_the_limit(self, settings):
        settings.LLM_RATE_LIMIT_REQUESTS = 0
        c = Client()
        assert all(self._hit(c).status_code == 200 for _ in range(5))

    def test_x_forwarded_for_is_ignored_without_trusted_proxies(self, settings):
        """A client must not dodge the limit by inventing X-Forwarded-For."""
        settings.LLM_RATE_LIMIT_REQUESTS = 1
        settings.NUM_PROXIES = 0
        assert self._hit(Client(), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="1.1.1.1").status_code == 200
        assert self._hit(Client(), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="2.2.2.2").status_code == 429

    def test_trusted_proxy_entry_is_used_and_client_supplied_prefix_ignored(self, settings):
        settings.LLM_RATE_LIMIT_REQUESTS = 1
        settings.NUM_PROXIES = 1
        # The proxy appends the real client IP LAST; anything before it is attacker-controlled.
        a = self._hit(Client(), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="6.6.6.6, 9.9.9.9")
        b = self._hit(Client(), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="7.7.7.7, 9.9.9.9")
        c = self._hit(Client(), REMOTE_ADDR="10.0.0.1", HTTP_X_FORWARDED_FOR="7.7.7.7, 8.8.8.8")
        assert (a.status_code, b.status_code, c.status_code) == (200, 429, 200)

    def test_cache_outage_fails_closed(self, settings):
        """A Redis outage must not disable rate limiting for LLM endpoints."""
        settings.LLM_RATE_LIMIT_REQUESTS = 1
        broken = MagicMock()
        broken.add.side_effect = ConnectionError("redis down")
        with patch("src.apps.legislation.api_limits.cache", broken):
            first = self._hit(Client())
            second = self._hit(Client())
        assert first.status_code == 503
        assert second.status_code == 503
        assert first["Retry-After"] == "5"
