# ruff: noqa: F401,F403,E501,E701
"""Compatibility facade for the SAPL client, split into focused mixins."""

from __future__ import annotations

import logging
import os

import requests

from django.conf import settings

from .sapl_corpus import SaplCorpusMixin
from .sapl_download import SaplDownloadMixin
from .sapl_normas import SaplNormasMixin
from .sapl_transport import SaplTransportMixin

logger = logging.getLogger(__name__)


class SaplAPIClient(SaplTransportMixin, SaplNormasMixin, SaplCorpusMixin, SaplDownloadMixin):
    DEFAULT_BASE_URL = getattr(
        settings, "SAPL_BASE_URL", os.getenv("SAPL_BASE_URL", "https://sapl.natal.rn.leg.br/api")
    )
    BASE_URL = DEFAULT_BASE_URL
    NORMA_ENDPOINT = "/norma/normajuridica/"
    USER_AGENTS = [
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36",
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    ]

    def __init__(self, base_url: str | None = None, timeout: int = 30, max_retries: int = 3):
        resolved_url = base_url or getattr(settings, "SAPL_BASE_URL", self.BASE_URL)
        self.base_url = str(resolved_url).rstrip("/")
        self.timeout = timeout
        self.session = self._create_session(max_retries)
        self._request_count = 0
        logger.info(
            "SaplAPIClient inicializado: base_url=%s, timeout=%ss, max_retries=%s",
            self.base_url,
            timeout,
            max_retries,
        )
