"""Security and operational middleware used by the Django application."""

import json
import logging
import time
import uuid

from django.conf import settings

from src.observability.metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("jurix.request")


class RequestObservabilityMiddleware:
    """Attach a correlation ID and emit bounded HTTP metrics/logs."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
        request.jurix_request_id = request_id
        started = time.perf_counter()

        try:
            response = self.get_response(request)
        except Exception:
            resolver_match = getattr(request, "resolver_match", None)
            route = getattr(resolver_match, "route", None) or "unresolved"
            elapsed = time.perf_counter() - started
            HTTP_REQUESTS.labels(request.method, route, "500").inc()
            HTTP_LATENCY.labels(request.method, route).observe(elapsed)
            logger.exception(
                json.dumps(
                    {
                        "event": "http_request",
                        "request_id": request_id,
                        "method": request.method,
                        "route": route,
                        "status": 500,
                        "latency_ms": round(elapsed * 1000, 2),
                    },
                    ensure_ascii=False,
                )
            )
            raise

        resolver_match = getattr(request, "resolver_match", None)
        route = getattr(resolver_match, "route", None) or "unresolved"
        elapsed = time.perf_counter() - started
        status = str(getattr(response, "status_code", 500))
        HTTP_REQUESTS.labels(request.method, route, status).inc()
        HTTP_LATENCY.labels(request.method, route).observe(elapsed)
        response["X-Request-ID"] = request_id
        logger.info(
            json.dumps(
                {
                    "event": "http_request",
                    "request_id": request_id,
                    "method": request.method,
                    "route": route,
                    "status": response.status_code,
                    "latency_ms": round(elapsed * 1000, 2),
                },
                ensure_ascii=False,
            )
        )
        return response


def _build_content_security_policy() -> str:
    """Build a strict CSP in production without breaking local development."""
    style_sources = ["'self'"]
    font_sources = ["'self'"]
    if settings.CSP_ALLOW_INLINE_STYLES:
        style_sources.append("'unsafe-inline'")
    if settings.CSP_ALLOW_GOOGLE_FONTS:
        style_sources.append("https://fonts.googleapis.com")
        font_sources.append("https://fonts.gstatic.com")
    return (
        "default-src 'self'; "
        "script-src 'self'; "
        f"style-src {' '.join(style_sources)}; "
        f"font-src {' '.join(font_sources)}; "
        "img-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'self'; "
        "form-action 'self'; "
        "frame-ancestors 'none'; "
        "manifest-src 'self'; "
        "worker-src 'self' blob:; "
        "upgrade-insecure-requests"
    )


CONTENT_SECURITY_POLICY = _build_content_security_policy()


class ContentSecurityPolicyMiddleware:
    """Apply CSP and baseline browser security headers."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        content_type = response.headers.get("Content-Type", "")
        if content_type.lower().startswith("text/html") and not request.path.startswith("/admin/"):
            response["Content-Security-Policy"] = _build_content_security_policy()
        response["X-Content-Type-Options"] = "nosniff"
        response["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=(), usb=()"
        )
        response["Cross-Origin-Opener-Policy"] = "same-origin"
        return response
