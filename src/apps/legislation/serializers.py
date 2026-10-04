"""
Serializers for the legislation app.

Provides centralized and consistent serialization for:
- Dispositivo source citations in RAG
- ChatSession objects
- ChatMessage objects
"""

import logging
import re
from datetime import date
from typing import Any
from urllib.parse import urlparse, urlsplit, urlunsplit

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from src.apps.legislation.source_urls import (
    canonical_norma_url,
    canonical_sapl_url,
    public_source_url,
)
from src.processing.temporal_scope import temporal_state_from_dates

logger = logging.getLogger(__name__)

_ARCHIVE_NORMA_LABEL = re.compile(
    r"^(?P<type>Lei(?:\s+Complementar|\s+Ordinária|\s+Orgânica|\s+Promulgada)?|"
    r"Decreto(?:-Lei|\s+Legislativo|\s+Executivo)?|Resolução|Portaria)\s+"
    r"(?:n[º°o.]?\s*)?(?P<number>[\d.]+)/(?P<year>\d{4})$",
    re.IGNORECASE,
)


def _legacy_archive_document_id(source: dict[str, Any], norma_ref: str) -> str | None:
    """Recover the local PDF for old saved citations only when the source is unique."""
    if not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False):
        return None
    match = _ARCHIVE_NORMA_LABEL.fullmatch(str(norma_ref or "").strip())
    excerpt = re.sub(r"\s+", " ", str(source.get("full_text") or source.get("text") or "")).strip()
    if not match or len(excerpt) < 30:
        return None

    from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
    from src.processing.document_metadata import (
        TYPE_SERIES,
        build_normative_identity,
        normalize_document_number,
    )
    from src.processing.normative_reference import canonical_type

    type_key = canonical_type(match.group("type"))
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type=type_key,
        series=TYPE_SERIES.get(type_key),
        number=normalize_document_number(match.group("number")),
        year=match.group("year"),
    )
    if not identity.identity_key:
        return None
    candidates = list(
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            review_status__in=(
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            ),
            metadata_json__identity_key=identity.identity_key,
            conflicts_json=[],
        ).order_by("entry_index", "pk")[:3]
    )
    matches = []
    folded_excerpt = excerpt.casefold()
    for document in candidates:
        extraction = document.extracoes.order_by("-created_at", "-pk").first()
        if extraction is None or extraction.status not in {
            ExtracaoDocumento.Status.COMPLETE,
            ExtracaoDocumento.Status.PARTIAL,
        }:
            continue
        extracted = re.sub(r"\s+", " ", extraction.legal_text or "").casefold()
        if folded_excerpt in extracted:
            matches.append(str(document.public_id))
    return matches[0] if len(matches) == 1 else None


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
    typed_match = re.match(
        r"^(Lei(?:\s+Complementar)?|Decreto|Resolu[cç][aã]o|Portaria)\s+(?:n[º°o.]?\s*)?(\d[\d.]*)/(\d{4})$",
        text,
        re.IGNORECASE,
    )
    if typed_match:
        return f"{typed_match.group(1)} nº {_format_legal_number(typed_match.group(2))}/{typed_match.group(3)}"
    match = re.match(r"^(\d[\d.]*)/(\d{4})$", text)
    if match:
        return f"Lei nº {_format_legal_number(match.group(1))}/{match.group(2)}"
    return text


def _format_legal_number(value: object) -> str:
    number = str(value or "").strip()
    if "." in number or not number.isdigit() or len(number) <= 3:
        return number
    return f"{int(number):,}".replace(",", ".")


def _legal_citation_label(norma_ref: str, dispositivo_ref: object) -> str:
    """Render a stable, readable citation without exposing hierarchy separators."""
    path = [part.strip() for part in str(dispositivo_ref or "").split(">") if part.strip()]
    if not path:
        return norma_ref
    normalized = []
    for part in path:
        if re.match(r"^inciso\b", part, re.IGNORECASE):
            part = re.sub(r"^inciso\s*", "inciso ", part, flags=re.IGNORECASE)
            part = part[0].lower() + part[1:]
        normalized.append(part)
    return f"{norma_ref}, {', '.join(normalized)}"


def _citation_id(norma_id: object, device_id: object, fallback: object = None) -> str | None:
    if norma_id and device_id:
        return f"jurix:norma:{norma_id}:dispositivo:{device_id}"
    if fallback:
        return f"jurix:fonte:{fallback}"
    return None


def _safe_temporal_version(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    version_hash = str(value.get("version_hash") or "")
    input_hash = str(value.get("input_hash") or "")
    as_of = str(value.get("as_of") or "")[:10]
    try:
        date.fromisoformat(as_of)
    except ValueError:
        return None
    if not re.fullmatch(r"[a-fA-F0-9]{64}", version_hash):
        return None
    result = {
        "as_of": as_of,
        "legal_status": str(value.get("legal_status") or "unknown")[:24],
        "version_hash": version_hash.lower(),
        "policy": str(value.get("policy") or "")[:80],
    }
    if re.fullmatch(r"[a-fA-F0-9]{64}", input_hash):
        result["input_hash"] = input_hash.lower()
    provenance = value.get("provenance")
    if isinstance(provenance, dict):
        source_id = str(provenance.get("base_document_id") or "")
        if re.fullmatch(r"[0-9a-fA-F-]{36}", source_id):
            result["source_document_id"] = source_id.lower()
        effective_on = str(provenance.get("effective_on") or "")
        if re.fullmatch(r"\d{4}-\d{2}-\d{2}", effective_on):
            result["effective_on"] = effective_on
    return result


def _safe_graph_relation(value: object) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "").upper()
    if action not in {"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA", "REFERENCIA"}:
        return None
    result = {
        key: str(value[key])[:160]
        for key in (
            "event_id", "intent", "role", "label", "review_status",
            "effective_status", "effective_on", "publication_on", "resolution",
        )
        if value.get(key) is not None
    }
    result["action"] = action
    quote = str(value.get("quote") or "").strip()
    if quote:
        result["quote"] = quote[:1200]
    for key in ("source_norma_id", "target_norma_id"):
        try:
            result[key] = int(value[key]) if value.get(key) is not None else None
        except (TypeError, ValueError):
            result[key] = None
    for key in ("source_device_key", "target_device_key"):
        candidate = str(value.get(key) or "")
        if re.fullmatch(r"[a-fA-F0-9]{64}", candidate):
            result[key] = candidate.lower()
    official_url = str(value.get("official_url") or "")
    parsed = urlparse(official_url)
    if parsed.scheme in {"http", "https"} and parsed.netloc:
        result["official_url"] = official_url[:1000]
    return result


def _citation_identity(norma_id, disp_id, structural_key, temporal_version):
    if temporal_version and norma_id and structural_key:
        return (
            f"jurix:norma:{norma_id}:version:{temporal_version['version_hash']}"
            f":device:{structural_key}"
        )
    return _citation_id(norma_id, disp_id)


def _without_url_fragment(value: str | None) -> str | None:
    if not value:
        return value
    parts = urlsplit(value)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, parts.query, ""))


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
        synthetic_fixture = False
        try:
            norma = disp.norma
            tipo_getter = getattr(norma, "get_tipo_display_name", None)
            norma_tipo = tipo_getter() if callable(tipo_getter) else getattr(norma, "tipo", "Lei")
            if str(norma_tipo).isdigit():
                norma_tipo = "Lei"
            norma_numero = _format_legal_number(getattr(norma, "numero", ""))
            norma_ano = getattr(norma, "ano", "")
            norma_id = getattr(norma, "id", None)
            base_document = getattr(norma, "documento_base", None)
            base_metadata = getattr(base_document, "metadata_json", {})
            synthetic_fixture = (
                isinstance(base_metadata, dict) and base_metadata.get("synthetic") is True
            )
            pdf_url = getattr(norma, "pdf_url", None) or None
            sapl_url = canonical_norma_url(norma)
            publication_date = getattr(norma, "data_publicacao", None)
            effective_date = getattr(norma, "data_vigencia", None)
        except Exception as e:
            logger.warning(f"Error accessing norma attributes: {e}")
            norma_tipo, norma_numero, norma_ano = "Lei", "", ""
            norma_id, pdf_url, sapl_url = None, None, None
            publication_date, effective_date = None, None
            synthetic_fixture = False

        disp_id = getattr(disp, "id", None)
        structural_key = str(getattr(disp, "structural_key", "") or "")
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
        citation_label = _legal_citation_label(norma_ref_str, disp_identifier)
        temporal_version = _safe_temporal_version(source.get("temporal_version"))
        source_url = public_source_url(norma) if norma is not None else None
        if temporal_version:
            citation_label += f" (redação projetada pelo Jurix em {temporal_version['as_of']})"
            pdf_url = _without_url_fragment(pdf_url)
            sapl_url = _without_url_fragment(sapl_url)
            source_url = _without_url_fragment(source_url)
        graph_relation = _safe_graph_relation(source.get("graph_relation"))
        contribution = "Trecho de dispositivo"
        source_type = "Fonte normativa primária"
        if synthetic_fixture:
            source_type = "Fixture sintética de QA — não representa legislação real"
        if graph_relation:
            contribution = graph_relation.get("label") or "Contexto de relação normativa"
            if not synthetic_fixture:
                source_type = "Contexto de relação normativa"

        return {
            "id": disp_id,
            "text": disp_texto[:200] + ("..." if len(disp_texto) > 200 else ""),
            "full_text": disp_texto,
            "similarity_score": similarity,
            "relevance_band": _relevance_band(similarity),
            "contribution": graph_relation.get("label")
            if graph_relation
            else "Dispositivo incluído na visão da norma"
            if source.get("retrieval_strategy") == "whole_norma"
            else contribution,
            "source_type": source_type,
            "distance": distance,
            "match_kind": source.get("match_kind"),
            "norma_ref": norma_ref_str,
            "norma_id": norma_id,
            "dispositivo_ref": disp_identifier,
            "citation_id": _citation_identity(
                norma_id, disp_id, structural_key, temporal_version
            ),
            "citation_label": citation_label,
            "retrieval_strategy": source.get("retrieval_strategy"),
            "evidence_scope": source.get("evidence_scope"),
            "synthetic_fixture": synthetic_fixture,
            "coverage": source.get("coverage"),
            "hierarchy": hierarchy,
            "pdf_url": pdf_url,
            "sapl_url": sapl_url,
            "source_url": source_url,
            "data_publicacao": publication_date.isoformat() if publication_date else None,
            "data_vigencia": effective_date.isoformat() if effective_date else None,
            "temporal_status": temporal_state_from_dates(norma)
            if norma is not None
            else "data_indeterminada",
            "dispositivo_id": disp_id,
            "dispositivo_structural_key": structural_key or None,
            "temporal_version": temporal_version,
            "graph_relation": graph_relation,
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

    dispositivo_ref = source.get("dispositivo_ref", norma_ref)
    norma_id = source.get("norma_id")
    structural_key = str(source.get("dispositivo_structural_key") or source.get("structural_key") or "")
    temporal_version = _safe_temporal_version(source.get("temporal_version"))
    citation_label = source.get("citation_label") or _legal_citation_label(norma_ref, dispositivo_ref)
    is_local_archive = source.get("evidence_scope") == "isolated_qa_archive"
    source_id = source.get("source_id") if is_local_archive else None
    if is_local_archive and not source_id:
        source_id = _legacy_archive_document_id(source, norma_ref)
    source_type = source.get("source_type", "Fonte normativa primária")
    if is_local_archive:
        citation_label = re.sub(
            r"\s*\(PDF de teste\)\s*$", "", str(citation_label), flags=re.IGNORECASE
        )
        source_type = "Acervo histórico local — extração pendente de revisão"
        contribution = "Trecho da extração do PDF arquivado; transcrição pendente de revisão"
    if temporal_version and "redação projetada pelo Jurix" not in citation_label:
        citation_label += f" (redação projetada pelo Jurix em {temporal_version['as_of']})"
    graph_relation = _safe_graph_relation(source.get("graph_relation"))
    citation_id = source.get("citation_id") or _citation_id(
        norma_id, disp_id, source.get("source_id")
    )
    if temporal_version:
        citation_id = _citation_identity(norma_id, disp_id, structural_key, temporal_version)
    local_pdf_url = None
    if source_id:
        try:
            local_pdf_url = reverse(
                "legislation:document_pdf",
                kwargs={"document_id": source_id},
            )
        except (NoReverseMatch, TypeError, ValueError):
            local_pdf_url = None
    return {
        "id": disp_id,
        "text": disp_texto[:200] + ("..." if len(disp_texto) > 200 else ""),
        "full_text": disp_texto,
        "similarity_score": similarity,
        "relevance_band": _relevance_band(similarity),
        "contribution": contribution,
        "source_type": source_type,
        "distance": distance,
        "match_kind": source.get("match_kind"),
        "norma_ref": norma_ref,
        "norma_id": norma_id,
        "dispositivo_ref": dispositivo_ref,
        "citation_id": citation_id,
        "citation_label": citation_label,
        "source_id": str(source_id) if source_id else None,
        "retrieval_strategy": source.get("retrieval_strategy"),
        "evidence_scope": source.get("evidence_scope"),
        "synthetic_fixture": source.get("synthetic_fixture") is True,
        "coverage": source.get("coverage"),
        "hierarchy": source.get("hierarchy", ""),
        "pdf_url": source.get("pdf_url"),
        "local_pdf_url": local_pdf_url,
        "sapl_url": canonical_sapl_url(source.get("sapl_url"), source.get("sapl_id")),
        "data_publicacao": source.get("data_publicacao"),
        "data_vigencia": source.get("data_vigencia"),
        "temporal_status": source.get("temporal_status", "data_indeterminada"),
        "dispositivo_id": disp_id,
        "dispositivo_structural_key": structural_key or None,
        "temporal_version": temporal_version,
        "graph_relation": graph_relation,
    }


def serialize_citation_sources(sources: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Serialize evidence in its answer-context order; citation indexes are stable."""
    serialized = []
    for index, source in enumerate(sources or [], start=1):
        row = serialize_dispositivo_source(source)
        row["citation_index"] = index
        serialized.append(row)
    return serialized


def serialize_chat_session(session: Any) -> dict[str, Any]:
    """Serialize a ChatSession model instance (the single JSON shape used by every endpoint)."""
    return {
        "id": session.id,
        "title": session.title or "Conversa sem título",
        "slug": session.slug,
        "is_active": session.is_active,
        "is_pinned": bool(getattr(session, "is_pinned", False)),
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
        "sources": serialize_citation_sources(message.sources_json or []) if is_assistant else [],
        "metadata": message.metadata_json if is_assistant else {},
        "created_at": message.created_at.isoformat() if message.created_at else None,
    }
    if not is_assistant:
        result["turn_state"] = getattr(turn, "state", None)
        result["client_turn_id"] = str(turn.client_turn_id) if turn else None
    return result
