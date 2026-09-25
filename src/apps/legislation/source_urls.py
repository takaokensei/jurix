"""Canonical public URLs for legislation sources.

SAPL exposes an API endpoint under ``/api/norma/normajuridica/...`` and a
public web route under ``/norma/<id>/``. Older Jurix records were persisted
with the former application's legacy UI route (``/norma/normajuridica``),
which now returns HTTP 404. Keeping URL normalization here prevents that
legacy value from leaking into the API, templates and cached responses.
"""

from __future__ import annotations

import re
from urllib.parse import urlparse

from django.conf import settings

_LEGACY_PATTERN = re.compile(r"/norma/normajuridica/(\d+)/?$")
_CURRENT_PATTERN = re.compile(r"/norma/(\d+)/?$")


def sapl_public_base_url() -> str:
    """Return the SAPL public host, stripping the API suffix if present."""
    configured = getattr(settings, "SAPL_PUBLIC_BASE_URL", "") or ""
    if not configured:
        configured = getattr(settings, "SAPL_BASE_URL", "") or ""
    configured = configured.strip().rstrip("/")
    if configured.lower().endswith("/api"):
        configured = configured[:-4]
    return configured.rstrip("/")


def canonical_sapl_url(url: str | None = None, sapl_id: int | str | None = None) -> str | None:
    """Return the current public SAPL URL for a norma.

    Existing non-SAPL URLs are preserved intentionally: they may represent a
    future external source and changing them without explicit knowledge would
    be destructive. SAPL's old ``/norma/normajuridica/<id>/`` route is always
    rewritten to ``/norma/<id>/``.
    """
    raw = (url or "").strip()
    parsed = urlparse(raw) if raw else None

    candidate_id: str | None = None
    if parsed and parsed.scheme in {"http", "https"}:
        match = _LEGACY_PATTERN.search(parsed.path.rstrip("/"))
        if match:
            candidate_id = match.group(1)
        else:
            match = _CURRENT_PATTERN.search(parsed.path.rstrip("/"))
            if match:
                candidate_id = match.group(1)

        configured_host = urlparse(sapl_public_base_url()).netloc.lower()
        host_is_sapl = not configured_host or parsed.netloc.lower() == configured_host
        if not host_is_sapl:
            return raw

    if candidate_id is None and sapl_id is not None:
        try:
            candidate_id = str(int(sapl_id))
        except (TypeError, ValueError):
            candidate_id = None

    if candidate_id is not None:
        base = sapl_public_base_url()
        if base:
            return f"{base}/norma/{candidate_id}/"

    if raw and parsed and parsed.scheme in {"http", "https"}:
        return raw
    return None


def canonical_norma_url(norma) -> str | None:
    """Resolve the public source URL from a ``Norma``-like object."""
    return canonical_sapl_url(
        getattr(norma, "sapl_url", None),
        getattr(norma, "sapl_id", None),
    )


def public_source_url(norma) -> str | None:
    """Prefer a valid PDF, otherwise return the canonical SAPL page."""
    pdf_url = (getattr(norma, "pdf_url", "") or "").strip()
    if pdf_url.startswith(("https://", "http://")):
        return pdf_url
    return canonical_norma_url(norma)
