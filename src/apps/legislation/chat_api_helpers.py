"""Session-history helpers extracted from the legislation API view module."""

from __future__ import annotations

from typing import Any

from django.core import signing
from django.db.models import Q
from django.http import JsonResponse

from src.apps.legislation.models import ChatMessage, ChatSession
from src.apps.legislation.serializers import serialize_chat_message, serialize_chat_session

CHAT_SESSIONS_DEFAULT_LIMIT = 20
CHAT_SESSIONS_MAX_LIMIT = 100
CHAT_MESSAGES_PAGE_SIZE = 25
SESSION_PREVIEW_LENGTH = 50


def _parse_limit(raw: Any) -> int:
    try:
        return max(1, min(int(raw), CHAT_SESSIONS_MAX_LIMIT))
    except (TypeError, ValueError):
        return CHAT_SESSIONS_DEFAULT_LIMIT


def _preview(content: str | None) -> str:
    content = content or ""
    suffix = "..." if len(content) > SESSION_PREVIEW_LENGTH else ""
    return content[:SESSION_PREVIEW_LENGTH] + suffix


def _chat_session_response(session: ChatSession, before: str | None = None) -> JsonResponse:
    queryset = ChatMessage.objects.filter(session=session)
    total = queryset.count()
    if before:
        try:
            cursor = signing.loads(before, salt="chat-history")
            if cursor["session"] != session.pk:
                raise ValueError("Wrong session")
            queryset = queryset.filter(
                Q(created_at__lt=cursor["date"]) | Q(created_at=cursor["date"], id__lt=cursor["id"])
            )
        except (signing.BadSignature, ValueError, KeyError, TypeError):
            return JsonResponse({"success": False, "error": "Invalid cursor"}, status=400)
    latest = list(queryset.order_by("-created_at", "-id")[: CHAT_MESSAGES_PAGE_SIZE + 1])
    has_more = len(latest) > CHAT_MESSAGES_PAGE_SIZE
    latest = latest[:CHAT_MESSAGES_PAGE_SIZE]
    next_cursor = None
    if has_more:
        last = latest[-1]
        next_cursor = signing.dumps(
            {"session": session.pk, "date": last.created_at.isoformat(), "id": last.pk},
            salt="chat-history",
        )
    messages = [serialize_chat_message(message) for message in reversed(latest)]
    return JsonResponse(
        {
            "success": True,
            "session": serialize_chat_session(session),
            "messages": messages,
            "count": len(messages),
            "total_count": total,
            "has_more": has_more,
            "next_cursor": next_cursor,
        }
    )
