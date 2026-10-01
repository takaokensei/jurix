"""Authenticated chat-turn identity and safe idempotency primitives."""

from __future__ import annotations

import json
from uuid import UUID

from django.conf import settings
from django.core.signing import salted_hmac
from django.db import transaction

from src.apps.legislation.models import ChatTurn


class TurnPayloadConflict(ValueError):
    """A client reused a turn identity for different request content."""


def normalize_turn_id(value: str | UUID | None) -> UUID:
    if isinstance(value, UUID):
        return value
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Identificador de turno inválido.") from None


def payload_digest(payload: dict) -> str:
    """Hash the request canonically; credentials are HMACed and never stored raw."""
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return salted_hmac(
        "jurix.chat_turn.payload.v1",
        canonical,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()


@transaction.atomic
def reserve_authenticated_turn(
    *,
    user,
    client_session_id: str,
    client_turn_id: str | UUID,
    payload: dict,
    session=None,
    retry_of: ChatTurn | None = None,
) -> tuple[ChatTurn, bool]:
    if not getattr(user, "is_authenticated", False):
        raise ValueError("Somente uma sessão autenticada pode reservar um turno durável.")
    if (
        not isinstance(client_session_id, str)
        or not client_session_id
        or len(client_session_id) > 80
    ):
        raise ValueError("Identificador de sessão do cliente inválido.")

    turn_id = normalize_turn_id(client_turn_id)
    if retry_of is not None:
        if retry_of.session_id is None:
            raise TurnPayloadConflict("A conversa da tentativa anterior não está disponível.")
        if retry_of.user_id != user.pk or retry_of.client_session_id != client_session_id:
            raise TurnPayloadConflict("A tentativa anterior não pertence a esta sessão.")
        if retry_of.state not in {"failed", "cancelled", "interrupted"}:
            raise TurnPayloadConflict(
                "Somente um turno interrompido ou com falha pode ser repetido."
            )
        if session and retry_of.session_id not in (None, session.pk):
            raise TurnPayloadConflict("A tentativa anterior pertence a outra conversa.")
    digest = payload_digest(payload)
    turn, created = ChatTurn.objects.get_or_create(
        user=user,
        client_session_id=client_session_id,
        client_turn_id=turn_id,
        defaults={
            "payload_digest": digest,
            "session": session,
            "retry_of": retry_of,
            "state": "reserved",
        },
    )
    if not created:
        if turn.payload_digest != digest:
            raise TurnPayloadConflict("O identificador do turno já foi usado com outro conteúdo.")
        if session and turn.session_id not in (None, session.pk):
            raise TurnPayloadConflict("O identificador do turno pertence a outra conversa.")
        if session and turn.session_id is None:
            turn.session = session
            turn.save(update_fields=["session", "updated_at"])
    return turn, created


_ALLOWED_TRANSITIONS = {
    "reserved": {"in_progress", "failed", "cancelled"},
    "in_progress": {"completed", "failed", "cancelled", "interrupted"},
    "interrupted": {"failed"},
    "completed": set(),
    "failed": set(),
    "cancelled": set(),
}


@transaction.atomic
def transition_turn(turn: ChatTurn, state: str) -> ChatTurn:
    locked = ChatTurn.objects.select_for_update().get(pk=turn.pk)
    if state == locked.state:
        return locked
    if state not in _ALLOWED_TRANSITIONS.get(locked.state, set()):
        raise ValueError(f"Transição de turno inválida: {locked.state} → {state}.")
    locked.state = state
    locked.save(update_fields=["state", "updated_at"])
    return locked
