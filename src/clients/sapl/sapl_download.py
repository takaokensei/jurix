# ruff: noqa: F401,F403,E501,E701
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


class SaplDownloadMixin:
    def download_pdf(self, pdf_url: str, output_path: str) -> bool:
        """
        Baixa um arquivo PDF da URL fornecida.

        Args:
            pdf_url: URL do PDF
            output_path: Caminho local para salvar

        Returns:
            True se bem-sucedido, False caso contrário
        """
        logger.info(f"Baixando PDF: {pdf_url} -> {output_path}")

        max_bytes = int(getattr(settings, "SAPL_DOWNLOAD_MAX_BYTES", 80 * 1024 * 1024))
        timeout = int(getattr(settings, "SAPL_DOWNLOAD_TIMEOUT_SECONDS", self.timeout))
        target = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temporary = target + ".part"
        try:
            headers = self._get_headers()
            response = self.session.get(pdf_url, headers=headers, timeout=timeout, stream=True)
            response.raise_for_status()
            content_length = response.headers.get("Content-Length")
            if content_length and int(content_length) > max_bytes:
                logger.warning("PDF exceeds configured download limit: %s bytes", content_length)
                return False

            total = 0
            with open(temporary, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning("PDF exceeded configured download limit while streaming")
                        return False
                    f.write(chunk)

            os.replace(temporary, target)

            logger.info(f"PDF baixado com sucesso: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Falha ao baixar PDF {pdf_url}: {str(e)}")
            return False
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                logger.debug("Could not remove partial SAPL PDF", exc_info=True)
