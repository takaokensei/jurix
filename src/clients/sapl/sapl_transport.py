# ruff: noqa: F401,F403,E501,E701
from __future__ import annotations

import logging
import os
import time
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SaplTransportMixin:
    @staticmethod
    def _normalize_pagination_payload(data: dict[str, Any]) -> dict[str, Any]:
        """Normalize the nested paginator used by SAPL Natal to DRF-style keys.

        Natal currently returns an unrelated top-level ``count`` value and puts
        the real page contract under ``pagination``. Keeping the original object
        while adding one validated internal metadata block lets existing callers
        consume ``count``/``next`` without losing the source fields.
        """
        pagination = data.get("pagination")
        if not isinstance(pagination, dict):
            return data

        links = pagination.get("links")
        if not isinstance(links, dict):
            raise ValueError("SAPL pagination metadata has no links object")

        try:
            page = int(pagination["page"])
            total_pages = int(pagination["total_pages"])
            total_entries = int(pagination["total_entries"])
            start_index = int(pagination["start_index"])
            end_index = int(pagination["end_index"])
            next_page = (
                int(pagination["next_page"])
                if pagination.get("next_page") is not None
                else None
            )
            previous_page = (
                int(pagination["previous_page"])
                if pagination.get("previous_page") is not None
                else None
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("SAPL pagination metadata is incomplete or invalid") from exc

        results = data.get("results")
        if (
            not isinstance(results, list)
            or page < 1
            or total_pages < page
            or total_entries < 0
            or start_index < 1
            or end_index < start_index
            or end_index > total_entries
            or end_index - start_index + 1 != len(results)
        ):
            raise ValueError("SAPL pagination metadata conflicts with its result page")

        if next_page is not None and int(next_page) != page + 1:
            raise ValueError("SAPL next page does not follow the current page")
        if previous_page is not None and int(previous_page) != page - 1:
            raise ValueError("SAPL previous page does not precede the current page")
        if (next_page is not None) != bool(links.get("next")):
            raise ValueError("SAPL next page and next link disagree")
        if (previous_page is not None) != bool(links.get("previous")):
            raise ValueError("SAPL previous page and previous link disagree")
        if (page > 1) != (previous_page is not None):
            raise ValueError("SAPL previous page does not match the page index")
        if (page < total_pages) != (next_page is not None):
            raise ValueError("SAPL page count and next page disagree")

        normalized = dict(data)
        normalized["count"] = total_entries
        normalized["next"] = links.get("next")
        normalized["previous"] = links.get("previous")
        normalized["_jurix_pagination"] = {
            "page": page,
            "total_pages": total_pages,
            "total_entries": total_entries,
            "start_index": start_index,
            "end_index": end_index,
        }
        return normalized

    def _create_session(self, max_retries: int) -> requests.Session:
        """
        Cria uma sessão HTTP com retry automático.

        Args:
            max_retries: Número máximo de tentativas

        Returns:
            Sessão requests configurada
        """
        session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,  # 1s, 2s, 4s, 8s...
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _get_headers(self) -> dict[str, str]:
        """
        Gera headers HTTP com rotação de User-Agent.

        Returns:
            Dicionário de headers
        """
        user_agent = self.USER_AGENTS[self._request_count % len(self.USER_AGENTS)]
        self._request_count += 1

        return {
            "User-Agent": user_agent,
            "Accept": "application/json",
            "Accept-Language": "pt-BR,pt;q=0.9",
        }

    def get_public_norma_url(self, sapl_id: int | str) -> str:
        """Return the current public SAPL URL, never the API route."""
        base = self.base_url.rstrip("/")
        if base.endswith("/api"):
            base = base[:-4]
        return f"{base}/norma/{int(sapl_id)}"

    def _make_request(self, endpoint: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """
        Executa uma requisição GET na API SAPL.

        Args:
            endpoint: Endpoint relativo (ex: '/norma/normajuridica/')
            params: Query parameters opcionais

        Returns:
            Resposta JSON deserializada

        Raises:
            requests.RequestException: Em caso de falha na requisição
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        logger.debug(f"Requisitando: {url} com params={params}")

        try:
            response = self.session.get(url, headers=headers, params=params, timeout=self.timeout)
            response.raise_for_status()

            data = response.json()
            logger.info(f"Requisição bem-sucedida: {url} - Status {response.status_code}")

            return self._normalize_pagination_payload(data)

        except requests.exceptions.Timeout:
            logger.error(f"Timeout ao acessar {url}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"Erro HTTP {e.response.status_code}: {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de requisição: {url} - {str(e)}")
            raise
        except ValueError as e:
            logger.error(f"Erro ao parsear JSON: {url} - {str(e)}")
            raise

    def _make_request_url(self, url: str) -> dict[str, Any]:
        """Follow a pagination URL returned by SAPL without rebuilding its query."""
        url = self.validate_pagination_url(url)
        headers = self._get_headers()
        try:
            response = self.session.get(
                url,
                headers=headers,
                timeout=self.timeout,
            )
            response.raise_for_status()
            return self._normalize_pagination_payload(response.json())
        except requests.exceptions.RequestException:
            logger.error("Erro ao seguir paginação SAPL: %s", url, exc_info=True)
            raise
        except ValueError:
            logger.error("Resposta JSON inválida ao seguir paginação SAPL: %s", url, exc_info=True)
            raise

    def validate_pagination_url(self, url: str) -> str:
        """Validate same-origin API pagination and upgrade SAPL's HTTP links."""
        base = urlparse(self.base_url)
        candidate = urlparse(str(url or ""))
        base_path = base.path.rstrip("/")
        same_host = candidate.hostname and candidate.hostname.lower() == (base.hostname or "").lower()
        default_http_port = candidate.port in (None, 80)
        default_https_port = base.port in (None, 443)
        if (
            base.scheme == "https"
            and candidate.scheme == "http"
            and same_host
            and default_http_port
            and default_https_port
            and not candidate.username
            and not candidate.password
        ):
            candidate = candidate._replace(scheme="https", netloc=base.netloc)
        if (
            candidate.scheme != base.scheme
            or candidate.netloc.lower() != base.netloc.lower()
            or candidate.username
            or candidate.password
            or candidate.fragment
            or not (candidate.path == base_path or candidate.path.startswith(f"{base_path}/"))
        ):
            raise ValueError("SAPL pagination URL escaped the configured API origin/path")
        return candidate.geturl()

    def close(self):
        """Fecha a sessão HTTP."""
        self.session.close()
        logger.info("Sessão HTTP fechada")
