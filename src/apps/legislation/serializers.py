"""
Serializers for the legislation app.

Provides centralized and consistent serialization for:
- Dispositivo source citations in RAG
- ChatSession objects
- ChatMessage objects
"""

import logging
import re
from typing import Any

from src.apps.legislation.source_urls import (
    canonical_norma_url,
    canonical_sapl_url,
    public_source_url,
)
from src.processing.temporal_scope import temporal_state_from_dates

logger = logging.getLogger(__name__)


def _relevance_band(score: float) -> str:
    if score >= 0.8:
        return "high"
    if score >= 0.6:
        return "medium"
    if score >= 0.4:
        return "partial"
    return "low"


def _normalize_norma_ref(value: object) -> str:
    """Keep cached sources readable even when legacy data omitted the type label."""
    text = str(value or "Fonte anexada").strip()
    if re.match(r"^\d+(?:[./-]\d+)?/\d{4}$", text):
        return f"Lei nº {text.replace('.', '')}"
    return text


def serialize_dispositivo_source(source: dict[str, Any]) -> dict[str, Any]:
    """
    Serialize a RAG source into a sanitized, frontend-ready dictionary.
    Handles both live Dispositivo model instances and cached dictionaries.

    Args:
        source: Dictionary containing 'dispositivo' (or 'dispositivo_id'),
                'similarity_score', 'distance', etc.

    Returns:
        Structured dictionary with clean source metadata
    """
    source = source if isinstance(source, dict) else {}
    disp = source.get("dispositivo")

    # Cosine distance and similarity bounded strictly to [0.0, 1.0]
    raw_distance = source.get("distance", 1.0)
    try:
        distance = float(raw_distance) if raw_distance is not None else 1.0
    except (ValueError, TypeError):
        distance = 1.0

    raw_similarity = source.get("similarity_score")
    if raw_similarity is not None:
        try:
            similarity = max(0.0, min(1.0, float(raw_similarity)))
        except (ValueError, TypeError):
            similarity = max(0.0, min(1.0, 1.0 - distance))
    else:
        similarity = max(0.0, min(1.0, 1.0 - distance))

    if disp:
        # Source from model instance
        norma = None
        try:
            norma = disp.norma
            tipo_getter = getattr(norma, "get_tipo_display_name", None)
            norma_tipo = tipo_getter() if callable(tipo_getter) else getattr(norma, "tipo", "Lei")
            if str(norma_tipo).isdigit():
                norma_tipo = "Lei"
            norma_numero = getattr(norma, "numero", "")
            norma_ano = getattr(norma, "ano", "")
            norma_id = getattr(norma, "id", None)
            pdf_url = getattr(norma, "pdf_url", None) or None
            sapl_url = canonical_norma_url(norma)
            publication_date = getattr(norma, "data_publicacao", None)
            effective_date = getattr(norma, "data_vigencia", None)
        except Exception as e:
            logger.warning(f"Error accessing norma attributes: {e}")
            norma_tipo, norma_numero, norma_ano = "Lei", "", ""
            norma_id, pdf_url, sapl_url = None, None, None
            publication_date, effective_date = None, None

        disp_id = getattr(disp, "id", None)
        disp_texto = str(getattr(disp, "texto", "") or "")
        disp_identifier = disp.get_full_identifier() if hasattr(disp, "get_full_identifier") else ""
        hierarchy = (
            source.get("context", {}).get("hierarchy", "")
            if isinstance(source.get("context"), dict)
            else ""
        )

        ident_prefix = (
            f"{norma_tipo} nº"
            if "nº" not in str(norma_tipo) and "n°" not in str(norma_tipo)
            else norma_tipo
        )
        norma_ref_str = (
            f"{ident_prefix} {norma_numero}/{norma_ano}".strip()
            if norma_numero and norma_ano
            else f"{norma_tipo} {norma_numero}/{norma_ano}".strip()
        )

        return {
            "id": disp_id,
            "text": disp_texto[:200] + ("..." if len(disp_texto) > 200 else ""),
            "full_text": disp_texto,
            "similarity_score": similarity,
            "relevance_band": _relevance_band(similarity),
            "contribution": "Trecho de dispositivo",
            "source_type": "Fonte normativa primária",
            "distance": distance,
            "norma_ref": norma_ref_str,
            "norma_id": norma_id,
            "dispositivo_ref": disp_identifier,
            "hierarchy": hierarchy,
            "pdf_url": pdf_url,
            "sapl_url": sapl_url,
            "source_url": public_source_url(norma) if norma is not None else None,
            "data_publicacao": publication_date.isoformat() if publication_date else None,
            "data_vigencia": effective_date.isoformat() if effective_date else None,
            "temporal_status": temporal_state_from_dates(norma)
            if norma is not None
            else "data_indeterminada",
            "dispositivo_id": disp_id,
        }

    # Fallback for cached or dict-only source
    disp_id = source.get("dispositivo_id") or source.get("id")
    disp_texto = str(source.get("texto") or source.get("text") or source.get("full_text", "") or "")
    norma_ref = _normalize_norma_ref(
        source.get("norma") or source.get("norma_ref", "Fonte anexada")
    )
    contribution = source.get("contribution") or source.get("evidence_role")
    if not contribution:
        contribution = "Trecho de dispositivo" if similarity >= 0.4 else "Contexto relacionado"

    return {
        "id": disp_id,
        "text": disp_texto[:200] + ("..." if len(disp_texto) > 200 else ""),
        "full_text": disp_texto,
        "similarity_score": similarity,
        "relevance_band": _relevance_band(similarity),
        "contribution": contribution,
        "source_type": source.get("source_type", "Fonte normativa primária"),
        "distance": distance,
        "norma_ref": norma_ref,
        "norma_id": source.get("norma_id"),
        "dispositivo_ref": source.get("dispositivo_ref", norma_ref),
        "hierarchy": source.get("hierarchy", ""),
        "pdf_url": source.get("pdf_url"),
        "sapl_url": canonical_sapl_url(source.get("sapl_url"), source.get("sapl_id")),
        "data_publicacao": source.get("data_publicacao"),
        "data_vigencia": source.get("data_vigencia"),
        "temporal_status": source.get("temporal_status", "data_indeterminada"),
        "dispositivo_id": disp_id,
    }


def serialize_chat_session(session: Any) -> dict[str, Any]:
    """Serialize a ChatSession model instance (the single JSON shape used by every endpoint)."""
    return {
        "id": session.id,
        "title": session.title or "Conversa sem título",
        "slug": session.slug,
        "is_active": session.is_active,
        "created_at": session.created_at.isoformat() if session.created_at else None,
        "updated_at": session.updated_at.isoformat() if session.updated_at else None,
    }


def serialize_chat_message(message: Any) -> dict[str, Any]:
    """
    Serialize a ChatMessage model instance.

    Sources and metadata only exist for assistant answers; user messages always
    report them empty.
    """
    is_assistant = message.role == "assistant"
    turn = None if is_assistant else getattr(message, "turn", None)
    result = {
        "id": message.id,
        "role": message.role,
        "content": message.content,
        "sources": message.sources_json if is_assistant else [],
        "metadata": message.metadata_json if is_assistant else {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
    if not is_assistant:
        result["turn_state"] = getattr(turn, "state", None)
        result["client_turn_id"] = str(turn.client_turn_id) if turn else None
    return result
