"""Versioned, credential-free provenance DTO shared by HTTP, SSE and chat history."""

from __future__ import annotations

from uuid import uuid4

SCHEMA_VERSION = 1
PROMPT_POLICY_VERSION = "jurix-legal-grounding-v2"
GROUNDING_POLICY_VERSION = "strict-grounding-v1"


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
