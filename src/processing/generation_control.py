"""Short-lived, owner-bound cancellation controls for streamed generations."""

from __future__ import annotations

import hmac
from uuid import UUID, uuid4

from django.conf import settings
from django.core import signing
from django.core.cache import cache
from django.utils.crypto import get_random_string, salted_hmac

CANCEL_TOKEN_TTL_SECONDS = 600
_SIGNING_SALT = "jurix.generation-cancel.v1"
_OWNER_SALT = "jurix.generation-cancel.owner.v1"
_CACHE_PREFIX = "jurix:generation-control:v1:"


class InvalidCancelToken(ValueError):
    """The supplied token is malformed, expired, forged, or owned by another caller."""


class ExpiredCancelToken(InvalidCancelToken):
    """The signed cancellation token exceeded its short lifetime."""


def _owner_identity(request) -> str:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return f"user:{user.pk}"

    session = getattr(request, "session", None)
    if session is None:
        raise InvalidCancelToken("A Django session is required.")
    cookie_session_key = getattr(request, "COOKIES", {}).get(settings.SESSION_COOKIE_NAME)
    session_key = cookie_session_key or session.session_key
    if not session_key:
        # An anonymous stream must not require a session-table write merely to
        # obtain an owner identifier. The random key is issued as the standard
        # Django session cookie, but no session data is persisted for it.
        session_key = get_random_string(32)
        session._session_key = session_key
        request._jurix_ephemeral_cancel_session_key = session_key
    session_digest = salted_hmac(
        _OWNER_SALT,
        session_key,
        secret=settings.SECRET_KEY,
        algorithm="sha256",
    ).hexdigest()
    return f"session:{session_digest}"


def attach_ephemeral_session_cookie(request, response) -> None:
    """Issue the ephemeral anonymous session identifier when this stream created it."""
    session_key = getattr(request, "_jurix_ephemeral_cancel_session_key", None)
    if not session_key:
        return
    response.set_cookie(
        settings.SESSION_COOKIE_NAME,
        session_key,
        max_age=CANCEL_TOKEN_TTL_SECONDS,
        path=settings.SESSION_COOKIE_PATH,
        domain=settings.SESSION_COOKIE_DOMAIN,
        secure=settings.SESSION_COOKIE_SECURE,
        httponly=settings.SESSION_COOKIE_HTTPONLY,
        samesite=settings.SESSION_COOKIE_SAMESITE,
    )


def _normalize_generation_id(generation_id: str | UUID) -> str:
    try:
        return str(generation_id if isinstance(generation_id, UUID) else UUID(str(generation_id)))
    except (TypeError, ValueError, AttributeError):
        raise ValueError("Invalid generation identifier.") from None


def _active_key(generation_id: str) -> str:
    return f"{_CACHE_PREFIX}{generation_id}:active"


def _terminal_key(generation_id: str) -> str:
    return f"{_CACHE_PREFIX}{generation_id}:terminal"


def register_generation(request) -> tuple[str, str]:
    """Register a stream and return its server UUID and owner-bound signed token."""
    generation_id = str(uuid4())
    owner = _owner_identity(request)
    cache.delete(_terminal_key(generation_id))
    cache.set(_active_key(generation_id), True, timeout=CANCEL_TOKEN_TTL_SECONDS)
    token = signing.dumps(
        {"generation_id": generation_id, "owner": owner},
        salt=_SIGNING_SALT,
        compress=False,
    )
    return generation_id, token


def _load_generation_id(request, token: str) -> str:
    if not isinstance(token, str) or not token or len(token) > 2048:
        raise InvalidCancelToken("Invalid cancellation token.")
    try:
        payload = signing.loads(
            token,
            salt=_SIGNING_SALT,
            max_age=CANCEL_TOKEN_TTL_SECONDS,
        )
    except signing.SignatureExpired as exc:
        raise ExpiredCancelToken("Cancellation token expired.") from exc
    except signing.BadSignature as exc:
        raise InvalidCancelToken("Invalid cancellation token.") from exc

    if not isinstance(payload, dict) or set(payload) != {"generation_id", "owner"}:
        raise InvalidCancelToken("Invalid cancellation token.")
    try:
        generation_id = _normalize_generation_id(payload["generation_id"])
    except ValueError as exc:
        raise InvalidCancelToken("Invalid cancellation token.") from exc
    owner = _owner_identity(request)
    if not isinstance(payload["owner"], str) or not hmac.compare_digest(payload["owner"], owner):
        raise InvalidCancelToken("Cancellation token owner mismatch.")
    return generation_id


def request_generation_cancel(request, token: str) -> str:
    """Mark one active generation cancelled; return its current lifecycle state."""
    generation_id = _load_generation_id(request, token)
    terminal_key = _terminal_key(generation_id)
    terminal_state = cache.get(terminal_key)
    if terminal_state:
        return terminal_state
    if not cache.get(_active_key(generation_id)):
        return "finished"

    # `add` arbitrates completion vs cancellation atomically on supported shared caches.
    if cache.add(terminal_key, "cancelled", timeout=CANCEL_TOKEN_TTL_SECONDS):
        return "cancelled"
    return cache.get(terminal_key) or "finished"


def is_generation_cancelled(generation_id: str | UUID) -> bool:
    normalized_id = _normalize_generation_id(generation_id)
    return cache.get(_terminal_key(normalized_id)) == "cancelled"


def finish_generation(generation_id: str | UUID, state: str) -> str:
    """Set the first terminal state only, preserving a concurrent cancel decision."""
    if state not in {"completed", "failed", "interrupted", "cancelled"}:
        raise ValueError("Invalid terminal generation state.")
    normalized_id = _normalize_generation_id(generation_id)
    terminal_key = _terminal_key(normalized_id)
    if not cache.add(terminal_key, state, timeout=CANCEL_TOKEN_TTL_SECONDS):
        if cache.get(terminal_key) == "finalizing":
            cache.set(terminal_key, state, timeout=CANCEL_TOKEN_TTL_SECONDS)
    cache.delete(_active_key(normalized_id))
    return cache.get(_terminal_key(normalized_id)) or state


def claim_generation_finalization(generation_id: str | UUID) -> str:
    """Atomically stop accepting cancellation once validated generation is complete."""
    normalized_id = _normalize_generation_id(generation_id)
    terminal_key = _terminal_key(normalized_id)
    cache.add(terminal_key, "finalizing", timeout=CANCEL_TOKEN_TTL_SECONDS)
    state = cache.get(terminal_key) or "finished"
    if state == "finalizing":
        cache.delete(_active_key(normalized_id))
    return state
