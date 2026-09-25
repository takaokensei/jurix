"""Prometheus metrics used by the Jurix runtime."""
from __future__ import annotations

from django.http import HttpResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "jurix_http_requests_total",
    "Total HTTP requests handled by Jurix.",
    ("method", "route", "status"),
)
HTTP_LATENCY = Histogram(
    "jurix_http_request_duration_seconds",
    "HTTP request latency in seconds.",
    ("method", "route"),
)

RAG_REQUESTS = Counter(
    "jurix_rag_requests_total",
    "RAG requests by terminal state.",
    ("status",),
)
RAG_RETRIEVAL_LATENCY = Histogram(
    "jurix_rag_retrieval_duration_seconds",
    "RAG retrieval latency in seconds.",
)
RAG_GENERATION_LATENCY = Histogram(
    "jurix_rag_generation_duration_seconds",
    "RAG generation latency in seconds.",
)
RAG_FIRST_TOKEN_LATENCY = Histogram(
    "jurix_rag_first_token_duration_seconds",
    "Latency from generation start to first streamed token.",
)
RAG_GROUNDING_FAILURES = Counter(
    "jurix_rag_grounding_failures_total",
    "RAG generations rejected by grounding validation.",
)
RAG_CACHE_HITS = Counter(
    "jurix_rag_cache_hits_total",
    "RAG answer cache hits.",
)
RAG_CACHE_MISSES = Counter(
    "jurix_rag_cache_misses_total",
    "RAG answer cache misses.",
)

SAPL_SYNC_RUNS = Counter(
    "jurix_sapl_sync_runs_total",
    "Incremental SAPL synchronization runs.",
    ("status",),
)
SAPL_SYNC_FAILURES = Counter(
    "jurix_sapl_sync_failures_total",
    "SAPL synchronization failures.",
)
SAPL_SYNC_RECORDS = Counter(
    "jurix_sapl_sync_records_total",
    "Records observed during SAPL synchronization.",
    ("state",),
)
CONSOLIDATION_TOTAL = Counter(
    "jurix_consolidation_total",
    "Consolidation runs.",
)
CONSOLIDATION_UNRESOLVED = Counter(
    "jurix_consolidation_unresolved_events_total",
    "Consolidation events that require review.",
)
ATTACHMENT_PROCESSING_FAILURES = Counter(
    "jurix_attachment_processing_failures_total",
    "Attachment processing failures.",
)


def metrics_response(request):
    """Expose the Prometheus text endpoint."""
    return HttpResponse(generate_latest(), content_type=CONTENT_TYPE_LATEST)
