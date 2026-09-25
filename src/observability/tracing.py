"""Small OpenTelemetry integration that remains a no-op unless enabled."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from django.conf import settings

try:
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor
except ImportError:  # pragma: no cover - dependency is present in production requirements
    trace = None

_INITIALIZED = False


def _ensure_provider() -> None:
    global _INITIALIZED
    if _INITIALIZED or trace is None or not getattr(settings, "OTEL_ENABLED", False):
        return
    provider = TracerProvider(
        resource=Resource.create({"service.name": getattr(settings, "OTEL_SERVICE_NAME", "jurix")})
    )
    endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "")
    if endpoint:
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint)))
    trace.set_tracer_provider(provider)
    _INITIALIZED = True


def get_tracer():
    _ensure_provider()
    if trace is None:
        return None
    return trace.get_tracer("jurix")


@contextmanager
def span(name: str, attributes: dict[str, Any] | None = None) -> Iterator[Any]:
    tracer = get_tracer()
    if tracer is None:
        yield None
        return
    with tracer.start_as_current_span(name) as current:
        for key, value in (attributes or {}).items():
            if value is not None:
                current.set_attribute(key, value)
        yield current


class TracingMiddleware:
    """Create one HTTP span and attach the Jurix correlation ID."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = getattr(request, "jurix_request_id", None) or request.headers.get(
            "X-Request-ID", ""
        )
        attrs = {
            "http.request.method": request.method,
            "url.path": request.path,
            "jurix.request_id": request_id,
        }
        with span("http.request", attrs) as current:
            response = self.get_response(request)
            if current is not None:
                current.set_attribute(
                    "http.response.status_code", int(getattr(response, "status_code", 500))
                )
            return response
