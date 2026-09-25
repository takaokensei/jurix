"""
Chat-session API contract + behaviour (audit P2.1).

The first group pins the JSON contract the frontend depends on, so the refactor of
api_views (removing ~300 lines of defensive code) can be proven behaviour-preserving.
The second group covers what the old code got wrong: N+1 queries in the list, a database
failure reported as an empty successful list, and a non-string title causing a 500.
"""
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.auth.models import User
from django.db import DatabaseError, connection
from django.test import Client
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from src.apps.legislation.models import ChatMessage, ChatSession

pytestmark = pytest.mark.django_db

SESSIONS = "/api/v1/chat/sessions/"


@pytest.fixture
def user():
    return User.objects.create_user("ana", password="x")


@pytest.fixture
def client(user):
    c = Client()
    c.force_login(user)
    return c


def add_messages(session, n, *, first_user_text="Pergunta"):
    """n alternating user/assistant messages with strictly increasing timestamps."""
    base = timezone.now() - timedelta(hours=1)
    out = []
    for i in range(n):
        role = "user" if i % 2 == 0 else "assistant"
        m = ChatMessage.objects.create(
            session=session, role=role,
            content=first_user_text if i == 0 else f"msg {i}",
            sources_json=[{"n": i}] if role == "assistant" else [],
            metadata_json={"m": i} if role == "assistant" else {},
        )
        ChatMessage.objects.filter(pk=m.pk).update(created_at=base + timedelta(seconds=i))
        out.append(m)
    return out


SESSION_KEYS = {"id", "title", "slug", "is_active", "created_at", "updated_at"}


# ------------------------------------------------------------- contract: list
class TestListContract:
    def test_guest_list_exposes_no_database_sessions(self):
        response = Client().get(SESSIONS)
        assert response.status_code == 200
        assert response.json()['sessions'] == []

    def test_shape_order_preview_and_count(self, client, user):
        old = ChatSession.objects.create(user=user, title="Antiga")
        new = ChatSession.objects.create(user=user, title="Nova")
        ChatSession.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=2))
        add_messages(new, 3, first_user_text="x" * 60)
        ChatSession.objects.create(user=User.objects.create_user("outra"), title="De outra pessoa")

        body = client.get(SESSIONS).json()

        assert body["success"] is True and body["count"] == 2
        assert [s["title"] for s in body["sessions"]] == ["Nova", "Antiga"]      # -updated_at
        first = body["sessions"][0]
        assert set(first) == SESSION_KEYS | {"message_count", "latest_message_preview"}
        assert first["message_count"] == 3
        assert first["latest_message_preview"] == "msg 2"
        assert first["slug"]
        assert body["sessions"][1]["message_count"] == 0
        assert body["sessions"][1]["latest_message_preview"] == ""

    def test_short_preview_has_no_ellipsis(self, client, user):
        s = ChatSession.objects.create(user=user, title="t")
        add_messages(s, 1, first_user_text="curta")
        assert client.get(SESSIONS).json()["sessions"][0]["latest_message_preview"] == "curta"

    @pytest.mark.parametrize("raw,expected", [("5", 5), ("abc", 20), ("100000", 100), ("", 20)])
    def test_limit_parameter(self, client, user, raw, expected):
        for i in range(7):
            ChatSession.objects.create(user=user, title=f"s{i}")
        n = client.get(SESSIONS, {"limit": raw}).json()["count"]
        assert n == min(expected, 7)


# ------------------------------------------------------------ contract: create
class TestCreateContract:
    def test_creates_active_session_and_deactivates_previous(self, client, user):
        prev = ChatSession.objects.create(user=user, title="prev", is_active=True)
        r = client.post(SESSIONS, data='{"title": "Minha conversa"}', content_type="application/json")
        assert r.status_code == 201
        s = r.json()["session"]
        assert {"id", "title", "is_active", "created_at"} <= set(s)
        assert s["title"] == "Minha conversa" and s["is_active"] is True
        prev.refresh_from_db()
        assert prev.is_active is False

    def test_default_title_and_truncation(self, client):
        assert client.post(SESSIONS, data="{}", content_type="application/json").json()["session"]["title"] == "Nova Conversa"
        long = client.post(SESSIONS, data='{"title": "%s"}' % ("y" * 500), content_type="application/json")
        assert len(long.json()["session"]["title"]) == 200

    def test_invalid_json_is_400(self, client):
        assert client.post(SESSIONS, data="{oops", content_type="application/json").status_code == 400


# ------------------------------------------------- contract: detail & by slug
@pytest.fixture(params=["detail", "slug"])
def fetch(request, client):
    def _fetch(session, **kw):
        url = (f"{SESSIONS}{session.id}/" if request.param == "detail"
               else f"{SESSIONS}slug/{session.slug}/")
        return client.get(url, **kw)
    return _fetch


class TestDetailAndSlugContract:
    def test_last_25_messages_chronological_with_metadata(self, fetch, user):
        s = ChatSession.objects.create(user=user, title="t")
        add_messages(s, 30)

        body = fetch(s).json()

        assert body["success"] is True
        assert set(body["session"]) == SESSION_KEYS
        assert body["count"] == 25 and body["total_count"] == 30 and body["has_more"] is True
        contents = [m["content"] for m in body["messages"]]
        assert contents == [("Pergunta" if i == 0 else f"msg {i}") for i in range(5, 30)]
        assistant = next(m for m in body["messages"] if m["role"] == "assistant")
        user_msg = next(m for m in body["messages"] if m["role"] == "user")
        assert assistant["sources"] and assistant["metadata"]
        assert user_msg["sources"] == [] and user_msg["metadata"] == {}
        assert set(assistant) == {"id", "role", "content", "sources", "metadata", "created_at"}

    def test_no_more_when_under_the_limit(self, fetch, user):
        s = ChatSession.objects.create(user=user, title="t")
        add_messages(s, 3)
        body = fetch(s).json()
        assert (body["count"], body["total_count"], body["has_more"]) == (3, 3, False)

    def test_other_users_session_is_404(self, fetch):
        foreign = ChatSession.objects.create(user=User.objects.create_user("x"), title="t")
        assert fetch(foreign).status_code == 404


class TestDetailMisc:
    def test_delete_removes_session_and_messages(self, client, user):
        s = ChatSession.objects.create(user=user, title="t")
        add_messages(s, 2)
        r = client.delete(f"{SESSIONS}{s.id}/")
        assert r.status_code == 200 and r.json()["success"] is True
        assert not ChatSession.objects.filter(pk=s.pk).exists()
        assert not ChatMessage.objects.filter(session_id=s.id).exists()

    def test_unknown_slug_is_404(self, client):
        assert client.get(f"{SESSIONS}slug/nao-existe/").status_code == 404

    def test_unauthenticated_detail_is_401(self, user):
        s = ChatSession.objects.create(user=user, title="t")
        assert Client().get(f"{SESSIONS}{s.id}/").status_code == 401


# ------------------------------------------------- new behaviour (old code failed)
class TestFixedBehaviour:
    def _queries_for(self, client, user, n_sessions):
        ChatSession.objects.filter(user=user).delete()
        for i in range(n_sessions):
            add_messages(ChatSession.objects.create(user=user, title=f"s{i}"), 3)
        with CaptureQueriesContext(connection) as ctx:
            assert client.get(SESSIONS).status_code == 200
        return len(ctx)

    def test_list_query_count_does_not_grow_with_number_of_sessions(self, client, user):
        """Was 2 extra queries per session (preview + count)."""
        assert self._queries_for(client, user, 2) == self._queries_for(client, user, 12)

    def test_database_failure_is_a_500_not_an_empty_successful_list(self, client):
        with patch("src.apps.legislation.api_views.ChatSession.objects") as manager:
            manager.filter.side_effect = DatabaseError("db down")
            r = client.get(SESSIONS)
        assert r.status_code == 500
        assert r.json()["success"] is False

    @pytest.mark.parametrize("bad_title", [123, ["a"], {"a": 1}, True])
    def test_non_string_title_is_a_400_not_a_500(self, client, bad_title):
        import json
        r = client.post(SESSIONS, data=json.dumps({"title": bad_title}), content_type="application/json")
        assert r.status_code == 400

    def test_500_body_never_contains_a_traceback_or_exception_text(self, client):
        with patch("src.apps.legislation.api_views.ChatSession.objects") as manager:
            manager.filter.side_effect = DatabaseError("secret-internal-detail")
            body = client.get(SESSIONS).content.decode()
        assert "secret-internal-detail" not in body and "Traceback" not in body
