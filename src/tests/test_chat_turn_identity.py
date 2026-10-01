from uuid import UUID

import pytest
from django.contrib.auth.models import User

from src.apps.legislation.models import ChatMessage, ChatSession, ChatTurn
from src.apps.legislation.serializers import serialize_chat_message
from src.processing.chat_turns import (
    TurnPayloadConflict,
    normalize_turn_id,
    reserve_authenticated_turn,
    transition_turn,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def user():
    return User.objects.create_user("turn-owner", password="test-only")


def test_turn_reservation_is_idempotent_for_same_owner_and_payload(user):
    session = ChatSession.objects.create(user=user, title="Consulta")
    identity = "5b34fc9a-2f5b-4f65-aa6e-82659cf1d6e5"
    payload = {"question": "O que diz o art. 1?", "provider": "ollama"}

    first, created_first = reserve_authenticated_turn(
        user=user,
        client_session_id="client-session-a",
        client_turn_id=identity,
        payload=payload,
        session=session,
    )
    repeated, created_repeat = reserve_authenticated_turn(
        user=user,
        client_session_id="client-session-a",
        client_turn_id=identity,
        payload=payload,
        session=session,
    )

    assert created_first is True
    assert created_repeat is False
    assert repeated.pk == first.pk
    assert ChatTurn.objects.count() == 1


def test_reusing_turn_identity_with_changed_payload_returns_conflict(user):
    identity = "678c98cd-cb89-4f89-9d24-06b00226c07f"
    reserve_authenticated_turn(
        user=user,
        client_session_id="client-session-a",
        client_turn_id=identity,
        payload={"question": "pergunta original"},
    )

    with pytest.raises(TurnPayloadConflict):
        reserve_authenticated_turn(
            user=user,
            client_session_id="client-session-a",
            client_turn_id=identity,
            payload={"question": "pergunta alterada"},
        )
    assert ChatTurn.objects.count() == 1


def test_turn_identity_is_partitioned_by_authenticated_user(user):
    another_user = User.objects.create_user("other-turn-owner", password="test-only")
    identity = "81a3119b-0fb4-42f8-b1ef-d1890563cb35"
    args = {
        "client_session_id": "same-client-session",
        "client_turn_id": identity,
        "payload": {"question": "pergunta"},
    }
    first, created_first = reserve_authenticated_turn(user=user, **args)
    second, created_second = reserve_authenticated_turn(user=another_user, **args)
    assert created_first and created_second
    assert first.pk != second.pk


def test_turn_id_rejects_invalid_uuid_and_state_transitions_are_one_way(user):
    with pytest.raises(ValueError, match="Identificador de turno inválido"):
        normalize_turn_id("not-a-uuid")
    turn, _ = reserve_authenticated_turn(
        user=user,
        client_session_id="client-session-a",
        client_turn_id=UUID("81a3119b-0fb4-42f8-b1ef-d1890563cb36"),
        payload={"question": "pergunta"},
    )
    assert transition_turn(turn, "in_progress").state == "in_progress"
    assert transition_turn(turn, "completed").state == "completed"
    with pytest.raises(ValueError, match="Transição de turno inválida"):
        transition_turn(turn, "in_progress")


def test_turn_persists_only_hmac_digest_not_provider_secret(user):
    secret = "never-store-this-api-key"
    turn, _ = reserve_authenticated_turn(
        user=user,
        client_session_id="client-session-a",
        client_turn_id="81a3119b-0fb4-42f8-b1ef-d1890563cb37",
        payload={"question": "pergunta", "provider": {"api_key": secret}},
    )
    turn.refresh_from_db()
    assert secret not in turn.payload_digest
    assert len(turn.payload_digest) == 64


def test_interrupted_user_turn_is_serialized_for_retry_after_page_reload(user):
    session = ChatSession.objects.create(user=user, title="Consulta")
    turn, _ = reserve_authenticated_turn(
        user=user,
        client_session_id="client-session-a",
        client_turn_id="81a3119b-0fb4-42f8-b1ef-d1890563cb38",
        payload={"question": "Pergunta interrompida"},
        session=session,
    )
    turn = transition_turn(turn, "in_progress")
    turn = transition_turn(turn, "interrupted")
    message = ChatMessage.objects.create(
        session=session,
        role="user",
        content="Pergunta interrompida",
        turn=turn,
    )

    serialized = serialize_chat_message(message)
    assert serialized["turn_state"] == "interrupted"
    assert serialized["client_turn_id"] == str(turn.client_turn_id)
