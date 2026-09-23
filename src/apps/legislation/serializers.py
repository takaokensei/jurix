"""
Serializers for the legislation app.

Provides centralized and consistent serialization for:
- Dispositivo source citations in RAG
- ChatSession objects
- ChatMessage objects
"""
import logging
from typing import Any

from src.apps.legislation.source_urls import canonical_norma_url, public_source_url

logger = logging.getLogger(__name__)


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
    disp = source.get('dispositivo')

    # Cosine distance and similarity bounded strictly to [0.0, 1.0]
    raw_distance = source.get('distance', 1.0)
    try:
        distance = float(raw_distance) if raw_distance is not None else 1.0
    except (ValueError, TypeError):
        distance = 1.0

    raw_similarity = source.get('similarity_score')
    if raw_similarity is not None:
        try:
            similarity = max(0.0, min(1.0, float(raw_similarity)))
        except (ValueError, TypeError):
            similarity = max(0.0, min(1.0, 1.0 - distance))
    else:
        similarity = max(0.0, min(1.0, 1.0 - distance))

    if disp:
        # Source from model instance
        try:
            norma = disp.norma
            norma_tipo = getattr(norma, 'tipo', 'Norma')
            norma_numero = getattr(norma, 'numero', '')
            norma_ano = getattr(norma, 'ano', '')
            norma_id = getattr(norma, 'id', None)
            pdf_url = getattr(norma, 'pdf_url', None) or None
            sapl_url = canonical_norma_url(norma)
        except Exception as e:
            logger.warning(f"Error accessing norma attributes: {e}")
            norma_tipo, norma_numero, norma_ano = 'Norma', '', ''
            norma_id, pdf_url, sapl_url = None, None, None

        disp_id = getattr(disp, 'id', None)
        disp_texto = getattr(disp, 'texto', '') or ''
        disp_identifier = disp.get_full_identifier() if hasattr(disp, 'get_full_identifier') else ''
        hierarchy = source.get('context', {}).get('hierarchy', '') if isinstance(source.get('context'), dict) else ''

        return {
            'id': disp_id,
            'text': disp_texto[:200] + ('...' if len(disp_texto) > 200 else ''),
            'full_text': disp_texto,
            'similarity_score': similarity,
            'distance': distance,
            'norma_ref': f"{norma_tipo} {norma_numero}/{norma_ano}".strip(),
            'norma_id': norma_id,
            'dispositivo_ref': disp_identifier,
            'hierarchy': hierarchy,
            'pdf_url': pdf_url,
            'sapl_url': sapl_url,
            'source_url': public_source_url(norma),
            'dispositivo_id': disp_id
        }

    # Fallback for cached or dict-only source
    disp_id = source.get('dispositivo_id') or source.get('id')
    disp_texto = source.get('texto') or source.get('text') or source.get('full_text', '')
    norma_ref = source.get('norma') or source.get('norma_ref', '')

    return {
        'id': disp_id,
        'text': disp_texto[:200] + ('...' if len(disp_texto) > 200 else ''),
        'full_text': disp_texto,
        'similarity_score': similarity,
        'distance': distance,
        'norma_ref': norma_ref,
        'norma_id': source.get('norma_id'),
        'dispositivo_ref': source.get('dispositivo_ref', norma_ref),
        'hierarchy': source.get('hierarchy', ''),
        'pdf_url': source.get('pdf_url'),
        'sapl_url': source.get('sapl_url'),
        'dispositivo_id': disp_id
    }


def serialize_chat_session(session: Any) -> dict[str, Any]:
    """Serialize a ChatSession model instance (the single JSON shape used by every endpoint)."""
    return {
        'id': session.id,
        'title': session.title or 'Conversa sem título',
        'slug': session.slug,
        'is_active': session.is_active,
        'created_at': session.created_at.isoformat() if session.created_at else None,
        'updated_at': session.updated_at.isoformat() if session.updated_at else None,
    }


def serialize_chat_message(message: Any) -> dict[str, Any]:
    """
    Serialize a ChatMessage model instance.

    Sources and metadata only exist for assistant answers; user messages always
    report them empty.
    """
    is_assistant = message.role == 'assistant'
    return {
        'id': message.id,
        'role': message.role,
        'content': message.content,
        'sources': message.sources_json if is_assistant else [],
        'metadata': message.metadata_json if is_assistant else {},
        'created_at': message.created_at.isoformat() if message.created_at else None,
    }
