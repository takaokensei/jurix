"""Versioned, credential-free provenance DTO shared by HTTP, SSE and chat history."""

from __future__ import annotations

import re
from datetime import date
from uuid import uuid4

SCHEMA_VERSION = 1
PROMPT_POLICY_VERSION = "jurix-legal-grounding-v2"
GROUNDING_POLICY_VERSION = "strict-grounding-v1"


def _safe_temporal_version(value):
    if not isinstance(value, dict):
        return None
    version_hash = str(value.get("version_hash") or "")
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
    for key in ("input_hash",):
        candidate = str(value.get(key) or "")
        if re.fullmatch(r"[a-fA-F0-9]{64}", candidate):
            result[key] = candidate.lower()
    for key in ("source_document_id", "effective_on"):
        candidate = value.get(key)
        if isinstance(candidate, str) and re.fullmatch(r"[0-9a-fA-F-]{36}" if key == "source_document_id" else r"\d{4}-\d{2}-\d{2}", candidate):
            result[key] = candidate.lower() if key == "source_document_id" else candidate
    return result


def _safe_graph_relation(value):
    if not isinstance(value, dict):
        return None
    action = str(value.get("action") or "").upper()
    if action not in {"ALTERA", "SUBSTITUI", "ADICIONA", "REVOGA", "REFERENCIA"}:
        return None
    allowed = (
        "event_id", "intent", "role", "label", "review_status", "effective_status",
        "effective_on", "publication_on", "resolution",
    )
    result = {key: str(value[key])[:160] for key in allowed if value.get(key) is not None}
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
    return result


def _date_value(value):
    return value.isoformat() if hasattr(value, "isoformat") else value


def build_answer_contract(
    *,
    question: str,
    retrieval_query: str,
    filters: dict,
    provider: str,
    model: str,
    sources: list[dict] | None = None,
    discarded_sources: list[dict] | None = None,
    grounding: dict | None = None,
    grounded: bool = False,
    corpus_revision: dict | None = None,
    request_id: str | None = None,
    cached: bool = False,
    timings_ms: dict | None = None,
    generation_attempts: list[dict] | None = None,
    reason_code: str | None = None,
) -> dict:
    """Build safe traceability metadata; never accept endpoint/auth config here."""
    if corpus_revision is None:
        try:
            from src.processing.corpus_identity import get_corpus_revision

            corpus_revision = get_corpus_revision()
        except Exception:
            corpus_revision = None
    safe_filters = {
        key: _date_value(value)
        for key, value in filters.items()
        if key
        in {
            "mode",
            "norma_status",
            "source_scope",
            "norma_type",
            "year",
            "max_sources",
            "min_similarity",
            "as_of",
            "published_from",
            "published_to",
        }
        and value is not None
    }
    source_rows = sources or []
    evidence_sources = []
    for source in source_rows:
        structural_key = str(source.get("dispositivo_structural_key") or "")
        evidence_sources.append(
            {
                "source_id": source.get("id") or source.get("source_id"),
                "device_id": source.get("dispositivo_id") or source.get("id"),
                "norma_id": source.get("norma_id") or (source.get("norma") or {}).get("id"),
                "citation_id": source.get("citation_id"),
                "citation_index": source.get("citation_index"),
                "citation_label": source.get("citation_label"),
                "article": source.get("dispositivo_ref") or source.get("numero"),
                "official_url": source.get("source_url")
                or source.get("pdf_url")
                or source.get("sapl_url"),
                "evidence_text": str(
                    source.get("evidence_text")
                    or source.get("snippet")
                    or source.get("full_text")
                    or source.get("texto")
                    or ""
                )[:1600],
                "evidence_text_present": bool(
                    source.get("evidence_text") or source.get("snippet") or source.get("texto")
                ),
                "dispositivo_structural_key": structural_key.lower()
                if re.fullmatch(r"[a-fA-F0-9]{64}", structural_key)
                else None,
                "retrieval_strategy": source.get("retrieval_strategy"),
                "evidence_scope": source.get("evidence_scope"),
                "temporal_version": _safe_temporal_version(source.get("temporal_version")),
                "graph_relation": _safe_graph_relation(source.get("graph_relation")),
            }
        )
    revision = corpus_revision or {}
    grounding_report = grounding or {}
    result = {
        "schema_version": SCHEMA_VERSION,
        "request_id": request_id or str(uuid4()),
        "corpus_revision": {
            "revision": revision.get("revision"),
            "digest": revision.get("digest"),
            "completeness": revision.get("completeness", "unknown"),
        },
        "question": question,
        "retrieval_query": retrieval_query,
        "filters": safe_filters,
        "provider": provider,
        "model": model,
        "prompt_policy_version": PROMPT_POLICY_VERSION,
        "grounding_policy_version": GROUNDING_POLICY_VERSION,
        "cached": bool(cached),
        "grounded": bool(grounded),
        "source_count": len(source_rows),
        "sources_count": len(source_rows),
        "sources": evidence_sources,
        "discarded_sources": discarded_sources or [],
        "grounding": grounding_report,
        "claim_report": grounding_report.get("claims", []),
        "timings_ms": timings_ms or {},
        "generation_attempts": generation_attempts or [],
    }
    if reason_code:
        result["reason_code"] = reason_code
    return result
