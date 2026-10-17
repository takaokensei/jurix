"""Session-history helpers extracted from the legislation API view module."""

from __future__ import annotations

import re
from typing import Any
from uuid import UUID

from django.core import signing
from django.db.models import OuterRef, Q, Subquery
from django.http import JsonResponse

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import ChatMessage, ChatSession
from src.apps.legislation.serializers import serialize_chat_message, serialize_chat_session

CHAT_SESSIONS_DEFAULT_LIMIT = 20
CHAT_SESSIONS_MAX_LIMIT = 100
CHAT_MESSAGES_PAGE_SIZE = 25
SESSION_PREVIEW_LENGTH = 50


def _normalized_archive_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _archive_source_page(source: dict[str, Any], extraction: dict[str, Any]) -> int | None:
    """Resolve a saved archive citation only against its exact extracted span."""
    span = source.get("span")
    if not isinstance(span, dict):
        return None
    start, end = span.get("start"), span.get("end")
    legal_text = extraction.get("legal_text") or ""
    if not isinstance(start, int) or not isinstance(end, int) or not 0 <= start < end <= len(legal_text):
        return None
    cited_text = _normalized_archive_text(
        source.get("full_text") or source.get("evidence_text") or source.get("text")
    )
    if not cited_text or cited_text != _normalized_archive_text(legal_text[start:end]):
        return None

    overlaps: dict[int, int] = {}
    for item in extraction.get("page_map_json") or []:
        if not isinstance(item, dict):
            continue
        page, page_start, page_end = item.get("page"), item.get("start"), item.get("end")
        if (
            not isinstance(page, int)
            or page < 1
            or not isinstance(page_start, int)
            or not isinstance(page_end, int)
            or page_start >= page_end
        ):
            continue
        overlap = max(0, min(end, page_end) - max(start, page_start))
        if overlap:
            overlaps[page] = overlaps.get(page, 0) + overlap
    if not overlaps:
        return None
    best_overlap = max(overlaps.values())
    best_pages = [page for page, overlap in overlaps.items() if overlap == best_overlap]
    return best_pages[0] if len(best_pages) == 1 else None


def resolve_archive_source_pages(sources: list[dict[str, Any]]) -> dict[int, int]:
    """Resolve verified page numbers for source dictionaries, without DB writes."""
    refs: set[tuple[UUID, str]] = set()
    for source in sources:
        if not isinstance(source, dict) or source.get("evidence_scope") != "isolated_qa_archive":
            continue
        if isinstance(source.get("page"), int) and source["page"] > 0:
            continue
        document_id = source.get("document_id") or source.get("source_id")
        digest = source.get("document_sha256")
        if not isinstance(digest, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", digest):
            continue
        try:
            refs.add((UUID(str(document_id)), digest.lower()))
        except (TypeError, ValueError, AttributeError):
            continue
    if not refs:
        return {}

    matching_documents = Q()
    for document_id, digest in refs:
        matching_documents |= Q(public_id=document_id, content_sha256=digest)
    latest_extraction = ExtracaoDocumento.objects.filter(documento_id=OuterRef("pk")).order_by(
        "-created_at", "-pk"
    )
    documents = DocumentoNormativo.objects.filter(
        matching_documents, source_kind=DocumentoNormativo.SourceKind.ARCHIVE
    ).annotate(
        _legal_text=Subquery(latest_extraction.values("legal_text")[:1]),
        _page_map=Subquery(latest_extraction.values("page_map_json")[:1]),
    ).values("public_id", "content_sha256", "_legal_text", "_page_map")
    extractions = {
        (row["public_id"], row["content_sha256"]): {
            "legal_text": row["_legal_text"],
            "page_map_json": row["_page_map"],
        }
        for row in documents
    }

    resolved = {}
    for index, source in enumerate(sources):
        if not isinstance(source, dict) or (
            isinstance(source.get("page"), int) and source["page"] > 0
        ):
            continue
        document_id = source.get("document_id") or source.get("source_id")
        digest = source.get("document_sha256")
        try:
            key = (UUID(str(document_id)), str(digest).lower())
        except (TypeError, ValueError, AttributeError):
            continue
        extraction = extractions.get(key)
        if extraction:
            page = _archive_source_page(source, extraction)
            if page:
                resolved[index] = page
    return resolved


def _hydrate_archive_source_pages(messages: list[ChatMessage]) -> dict[int, list[dict[str, Any]]]:
    """Return per-message source copies with verified PDF pages, without DB writes."""
    indexed_sources = []
    locations = []
    messages_by_id = {message.pk: message for message in messages}
    for message in messages:
        if message.role != "assistant":
            continue
        for source_index, source in enumerate(message.sources_json or []):
            indexed_sources.append(source)
            locations.append((message.pk, source_index))
    resolved = resolve_archive_source_pages(indexed_sources)

    hydrated: dict[int, list[dict[str, Any]]] = {}
    for flattened_index, page in resolved.items():
        message_id, source_index = locations[flattened_index]
        if message_id not in hydrated:
            message = messages_by_id[message_id]
            hydrated[message_id] = [
                dict(source) if isinstance(source, dict) else source
                for source in message.sources_json or []
            ]
        hydrated[message_id][source_index]["page"] = page
        hydrated[message_id][source_index]["page_index"] = page - 1
    return hydrated


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
    queryset = ChatMessage.objects.filter(session=session).select_related("turn")
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
    ordered_messages = list(reversed(latest))
    source_overrides = _hydrate_archive_source_pages(ordered_messages)
    messages = [
        serialize_chat_message(message, sources=source_overrides.get(message.pk))
        for message in ordered_messages
    ]
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
