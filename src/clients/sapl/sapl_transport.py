from __future__ import annotations
import logging
import os
import time
from typing import Any
import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry
logger = logging.getLogger(__name__)

class SaplTransportMixin:
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
            return f"{base}/norma/{int(sapl_id)}/"

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
    
                return data
    
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
            headers = self._get_headers()
            try:
                response = self.session.get(
                    url,
                    headers=headers,
                    timeout=self.timeout,
                )
                response.raise_for_status()
                return response.json()
            except requests.exceptions.RequestException:
                logger.error("Erro ao seguir paginação SAPL: %s", url, exc_info=True)
                raise
            except ValueError:
                logger.error("Resposta JSON inválida ao seguir paginação SAPL: %s", url, exc_info=True)
                raise

        def close(self):
            """Fecha a sessão HTTP."""
            self.session.close()
            logger.info("Sessão HTTP fechada")
