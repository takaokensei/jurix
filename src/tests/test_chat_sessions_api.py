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

from src.apps.legislation.models import ChatMessage, ChatSession, ChatTurn

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
            session=session,
            role=role,
            content=first_user_text if i == 0 else f"msg {i}",
            sources_json=[{"n": i}] if role == "assistant" else [],
            metadata_json={"m": i} if role == "assistant" else {},
        )
        ChatMessage.objects.filter(pk=m.pk).update(created_at=base + timedelta(seconds=i))
        out.append(m)
    return out


SESSION_KEYS = {"id", "title", "slug", "is_active", "is_pinned", "created_at", "updated_at"}


# ------------------------------------------------------------- contract: list
class TestListContract:
    def test_guest_list_exposes_no_database_sessions(self):
        response = Client().get(SESSIONS)
        assert response.status_code == 200
        assert response.json()["sessions"] == []

    def test_shape_order_preview_and_count(self, client, user):
        old = ChatSession.objects.create(user=user, title="Antiga")
        new = ChatSession.objects.create(user=user, title="Nova")
        ChatSession.objects.filter(pk=old.pk).update(updated_at=timezone.now() - timedelta(days=2))
        add_messages(new, 3, first_user_text="x" * 60)
        ChatSession.objects.create(user=User.objects.create_user("outra"), title="De outra pessoa")

        body = client.get(SESSIONS).json()

        assert body["success"] is True and body["count"] == 2
        assert [s["title"] for s in body["sessions"]] == ["Nova", "Antiga"]  # -updated_at
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

    def test_pinned_sessions_sort_before_recent_unpinned_sessions(self, client, user):
        recent = ChatSession.objects.create(user=user, title="Recente")
        ChatSession.objects.create(user=user, title="Fixada", is_pinned=True)
        ChatSession.objects.filter(pk=recent.pk).update(updated_at=timezone.now() + timedelta(days=1))
        assert [item["title"] for item in client.get(SESSIONS).json()["sessions"]] == [
            "Fixada",
            "Recente",
        ]


# ------------------------------------------------------------ contract: create
class TestCreateContract:
    def test_creates_active_session_and_deactivates_previous(self, client, user):
        prev = ChatSession.objects.create(user=user, title="prev", is_active=True)
        r = client.post(
            SESSIONS, data='{"title": "Minha conversa"}', content_type="application/json"
        )
        assert r.status_code == 201
        s = r.json()["session"]
        assert {"id", "title", "is_active", "created_at"} <= set(s)
        assert s["title"] == "Minha conversa" and s["is_active"] is True
        prev.refresh_from_db()
        assert prev.is_active is False

    def test_default_title_and_truncation(self, client):
        assert (
            client.post(SESSIONS, data="{}", content_type="application/json").json()["session"][
                "title"
            ]
            == "Nova Conversa"
        )
        long = client.post(
            SESSIONS, data='{"title": "%s"}' % ("y" * 500), content_type="application/json"
        )
        assert len(long.json()["session"]["title"]) == 200

    def test_invalid_json_is_400(self, client):
        assert (
            client.post(SESSIONS, data="{oops", content_type="application/json").status_code == 400
        )


# ------------------------------------------------- contract: detail & by slug
@pytest.fixture(params=["detail", "slug"])
def fetch(request, client):
    def _fetch(session, **kw):
        url = (
            f"{SESSIONS}{session.id}/"
            if request.param == "detail"
            else f"{SESSIONS}slug/{session.slug}/"
        )
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
    def test_patch_renames_and_pins_owned_session(self, client, user):
        session = ChatSession.objects.create(user=user, title="Consulta")
        response = client.patch(
            f"{SESSIONS}{session.id}/",
            data='{"title":"Lei do Município","is_pinned":true}',
            content_type="application/json",
        )
        assert response.status_code == 200
        assert response.json()["session"]["title"] == "Lei do Município"
        assert response.json()["session"]["is_pinned"] is True

    def test_patch_rejects_invalid_fields_and_foreign_sessions(self, client, user):
        session = ChatSession.objects.create(user=user, title="Consulta")
        invalid = client.patch(
            f"{SESSIONS}{session.id}/",
            data='{"is_pinned":"yes"}',
            content_type="application/json",
        )
        assert invalid.status_code == 400
        assert client.patch(
            f"{SESSIONS}{session.id}/",
            data='{"user_id":999}',
            content_type="application/json",
        ).status_code == 400
        foreign = ChatSession.objects.create(user=User.objects.create_user("outra"), title="Privada")
        assert client.patch(
            f"{SESSIONS}{foreign.id}/",
            data='{"is_pinned":true}',
            content_type="application/json",
        ).status_code == 404

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

        r = client.post(
            SESSIONS, data=json.dumps({"title": bad_title}), content_type="application/json"
        )
        assert r.status_code == 400

    def test_500_body_never_contains_a_traceback_or_exception_text(self, client):
        with patch("src.apps.legislation.api_views.ChatSession.objects") as manager:
            manager.filter.side_effect = DatabaseError("secret-internal-detail")
            body = client.get(SESSIONS).content.decode()
        assert "secret-internal-detail" not in body and "Traceback" not in body


@pytest.mark.parametrize("grounded", [False, True])
def test_stream_contract_persists_sources_only_for_grounded_answers(client, user, grounded):
    import json

    session = ChatSession.objects.create(user=user, title="Consulta")
    ChatMessage.objects.create(session=session, role="user", content="Pergunta anterior")
    source = {"norma_ref": "Lei 10/2025", "text": "Art. 1º", "dispositivo_id": 7}
    events = iter(
        [
            {"event": "sources", "sources": [source]},
            {"event": "chunk", "chunk": "Resposta [[1]]"},
            {
                "event": "done",
                "answer": "Resposta [[1]]",
                "grounded": grounded,
                "timings_ms": {"retrieval": 7, "generation": 30},
                "generation_attempts": [{"attempt": 1, "duration_ms": 30}],
            },
        ]
    )

    with (
        patch("src.apps.legislation.api_views.RAGService") as rag,
        patch("src.apps.legislation.api_views.rate_limit_response", return_value=None),
    ):
        rag.return_value.stream_answer_question.return_value = events
        response = client.post(
            "/api/v1/search/answer/stream/",
            data=json.dumps({"question": "Nova pergunta", "session_id": session.id}),
            content_type="application/json",
        )
        payloads = [
            json.loads(line[6:])
            for line in b"".join(response.streaming_content).decode().splitlines()
            if line.startswith("data: ")
        ]

    done = next(payload for payload in payloads if payload["type"] == "done")
    saved = ChatMessage.objects.get(session=session, role="assistant")
    assert response.status_code == 200
    assert done["grounded"] is grounded
    assert done["contract"]["schema_version"] == 1
    assert done["contract"] == saved.metadata_json
    assert bool(saved.sources_json) is grounded
    assert saved.metadata_json["grounded"] is grounded
    assert saved.metadata_json["sources_count"] == (1 if grounded else 0)
    assert done["contract"]["timings_ms"] == {"retrieval": 7, "generation": 30}
    assert done["contract"]["generation_attempts"] == [{"attempt": 1, "duration_ms": 30}]


def test_stream_turn_retry_replays_completed_answer_without_generating_again(client, user):
    import json

    session = ChatSession.objects.create(user=user, title="Consulta")
    ChatMessage.objects.create(session=session, role="user", content="Pergunta anterior")
    turn_id = "b84f621d-333d-4da1-85ed-01ebc7e7226b"
    payload = {
        "question": "Pergunta com retry idempotente",
        "session_id": session.id,
        "client_session_id": "client-session-idempotent",
        "client_turn_id": turn_id,
    }
    generated_events = iter(
        [
            {"event": "sources", "sources": [{"norma_ref": "Lei 1/2026", "text": "Art. 1º"}]},
            {"event": "chunk", "chunk": "Resposta persistida"},
            {
                "event": "done",
                "answer": "Resposta persistida",
                "grounded": True,
                "grounding": {"grounded": True},
            },
        ]
    )
    with (
        patch("src.apps.legislation.api_views.RAGService") as rag,
        patch("src.apps.legislation.api_views.rate_limit_response", return_value=None),
    ):
        rag.return_value.stream_answer_question.return_value = generated_events
        first = client.post(
            "/api/v1/search/answer/stream/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        first_events = [
            json.loads(line[6:])
            for line in b"".join(first.streaming_content).decode().splitlines()
            if line.startswith("data: ")
        ]
        retry = client.post(
            "/api/v1/search/answer/stream/",
            data=json.dumps(payload),
            content_type="application/json",
        )
        retry_events = [
            json.loads(line[6:])
            for line in b"".join(retry.streaming_content).decode().splitlines()
            if line.startswith("data: ")
        ]
        changed_payload = {**payload, "question": "Conteúdo diferente"}
        conflict = client.post(
            "/api/v1/search/answer/stream/",
            data=json.dumps(changed_payload),
            content_type="application/json",
        )

    assert first.status_code == retry.status_code == 200
    assert (
        next(item for item in first_events if item["type"] == "done")["answer"]
        == "Resposta persistida"
    )
    replayed = next(item for item in retry_events if item["type"] == "done")
    assert replayed["answer"] == "Resposta persistida"
    assert replayed["contract"]["grounded"] is True
    rag.return_value.stream_answer_question.assert_called_once()
    assert conflict.status_code == 409
    assert ChatTurn.objects.filter(user=user).count() == 1
    assert (
        ChatMessage.objects.filter(
            session=session, role="user", content=payload["question"]
        ).count()
        == 1
    )


def test_stream_retry_links_failed_turn_without_duplicate_user_message(client, user):
    import json

    session = ChatSession.objects.create(user=user, title="Consulta")
    ChatMessage.objects.create(session=session, role="user", content="Pergunta anterior")
    original_turn_id = "440836cc-4fa4-4a7e-ab2c-50d0324131a7"
    next_turn_id = "59eab147-3662-492b-9b3b-50b8d640ab2a"
    base_payload = {
        "question": "Pergunta que precisa de retry",
        "session_id": session.id,
        "client_session_id": "client-session-retry",
    }

    def interrupted_events():
        yield {"event": "status", "status": "retrieving"}
        raise RuntimeError("synthetic interruption")

    def parse_events(response):
        return [
            json.loads(line[6:])
            for line in b"".join(response.streaming_content).decode().splitlines()
            if line.startswith("data: ")
        ]

    with (
        patch("src.apps.legislation.api_views.RAGService") as rag,
        patch("src.apps.legislation.api_views.rate_limit_response", return_value=None),
    ):
        rag.return_value.stream_answer_question.return_value = interrupted_events()
        first = client.post(
            "/api/v1/search/answer/stream/",
            data=json.dumps({**base_payload, "client_turn_id": original_turn_id}),
            content_type="application/json",
        )
        first_events = parse_events(first)
        original_turn = ChatTurn.objects.get(client_turn_id=original_turn_id)
        assert original_turn.state == "failed"

        rag.return_value.stream_answer_question.return_value = iter(
            [
                {"event": "sources", "sources": []},
                {"event": "chunk", "chunk": "Resposta após retry"},
                {"event": "done", "answer": "Resposta após retry", "grounded": False},
            ]
        )
        retry = client.post(
            "/api/v1/search/answer/stream/",
            data=json.dumps(
                {
                    **base_payload,
                    "client_turn_id": next_turn_id,
                    "retry_of_client_turn_id": original_turn_id,
                }
            ),
            content_type="application/json",
        )
        retry_events = parse_events(retry)

    retry_turn = ChatTurn.objects.get(client_turn_id=next_turn_id)
    assert first.status_code == retry.status_code == 200
    assert any(item.get("type") == "error" for item in first_events)
    assert retry_turn.retry_of_id == original_turn.pk
    assert retry_turn.state == "completed"
    assert (
        ChatMessage.objects.filter(
            session=session, role="user", content=base_payload["question"]
        ).count()
        == 1
    )
    assert (
        next(item for item in retry_events if item["type"] == "done")["answer"]
        == "Resposta após retry"
    )


@pytest.mark.parametrize("grounded", [False, True])
def test_regeneration_exposes_and_persists_sources_only_when_grounded(client, user, grounded):
    session = ChatSession.objects.create(user=user, title="Consulta")
    ChatMessage.objects.create(session=session, role="user", content="Pergunta")
    ChatMessage.objects.create(
        session=session, role="assistant", content="Resposta antiga", sources_json=[{"old": True}]
    )
    source = {"norma_ref": "Lei 10/2025", "text": "Art. 1º", "dispositivo_id": 7}
    generated = {
        "answer": "Resposta regenerada",
        "sources": [source],
        "grounded": grounded,
        "confidence": 0.95,
        "model": "llama3",
        "context_length": 100,
    }

    with (
        patch("src.apps.legislation.api_views.RAGService") as rag,
        patch("src.apps.legislation.api_views.rate_limit_response", return_value=None),
    ):
        rag.return_value.answer_question.return_value = generated
        response = client.post(
            f"{SESSIONS}{session.id}/regenerate/", data="{}", content_type="application/json"
        )

    body = response.json()
    saved = ChatMessage.objects.get(session=session, role="assistant")
    assert response.status_code == 200
    assert body["grounded"] is grounded
    assert bool(body["sources"]) is grounded
    assert bool(saved.sources_json) is grounded
    assert saved.metadata_json["grounded"] is grounded
