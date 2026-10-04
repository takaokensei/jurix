# ruff: noqa: F401,F403,E501,E701
from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SaplDownloadMixin:
    def _validated_sapl_pdf_url(self, pdf_url: str) -> str:
        base = urlparse(self.base_url)
        candidate = urlparse(str(pdf_url or ""))
        if (
            candidate.scheme not in {"http", "https"}
            or candidate.scheme != base.scheme
            or candidate.netloc.lower() != base.netloc.lower()
            or candidate.username
            or candidate.password
            or candidate.fragment
        ):
            raise ValueError("SAPL PDF URL escaped the configured origin")
        return candidate.geturl()

    def fingerprint_pdf(self, pdf_url: str) -> str:
        """Return a bounded, same-origin identity for one SAPL PDF.

        Prefer a strong ETag, then Last-Modified + Content-Length. If the
        origin does not expose a usable validator, stream and hash the bytes
        under an explicit size cap. Redirects are never followed.
        """
        safe_url = self._validated_sapl_pdf_url(pdf_url)

        timeout = int(getattr(settings, "SAPL_DOWNLOAD_TIMEOUT_SECONDS", self.timeout))
        max_bytes = min(
            max(1, int(getattr(settings, "SAPL_SYNC_PDF_FINGERPRINT_MAX_BYTES", 10 * 1024 * 1024))),
            max(1, int(getattr(settings, "SAPL_DOWNLOAD_MAX_BYTES", 80 * 1024 * 1024))),
        )
        headers = self._get_headers()
        response = self.session.head(
            safe_url, headers=headers, timeout=timeout, allow_redirects=False
        )
        try:
            if response.status_code not in {405, 501}:
                if response.status_code != 200:
                    response.raise_for_status()
                    raise requests.RequestException(
                        f"Unexpected SAPL PDF HEAD status: {response.status_code}"
                    )
                etag = str(response.headers.get("ETag", "")).strip()
                if etag and not etag.lower().startswith("w/"):
                    return f"etag:{etag}"
                last_modified = str(response.headers.get("Last-Modified", "")).strip()
                content_length = str(response.headers.get("Content-Length", "")).strip()
                if last_modified and content_length.isdigit():
                    return f"last-modified:{last_modified}:bytes:{content_length}"
        finally:
            response.close()

        response = self.session.get(
            safe_url,
            headers=headers,
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        try:
            response.raise_for_status()
            if response.status_code != 200:
                raise requests.RequestException(
                    f"Unexpected SAPL PDF GET status: {response.status_code}"
                )
            content_length = str(response.headers.get("Content-Length", "")).strip()
            if content_length.isdigit() and int(content_length) > max_bytes:
                raise ValueError("SAPL PDF exceeds the fingerprint byte limit")
            digest = hashlib.sha256()
            total = 0
            prefix = b""
            for chunk in response.iter_content(chunk_size=64 * 1024):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise ValueError("SAPL PDF exceeded the fingerprint byte limit")
                if len(prefix) < 5:
                    prefix += chunk[: 5 - len(prefix)]
                digest.update(chunk)
            if total == 0:
                raise ValueError("SAPL PDF response was empty; fingerprint is incomplete")
            if not prefix.startswith(b"%PDF-"):
                raise ValueError("SAPL PDF response has no PDF signature")
            return f"sha256:{digest.hexdigest()}"
        finally:
            response.close()

    def download_pdf_version(self, pdf_url: str, output_path: str | Path) -> dict[str, Any]:
        """Download one immutable candidate without following redirects or overwriting.

        The caller is responsible for placing ``output_path`` inside its isolated
        staging/storage root. The target must not already exist; this method writes
        to a unique sibling temp file and publishes it with a no-overwrite hard link.
        """
        safe_url = self._validated_sapl_pdf_url(pdf_url)
        target = Path(output_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            raise FileExistsError("SAPL PDF candidate target already exists")

        max_bytes = max(1, int(getattr(settings, "SAPL_DOWNLOAD_MAX_BYTES", 80 * 1024 * 1024)))
        timeout = int(getattr(settings, "SAPL_DOWNLOAD_TIMEOUT_SECONDS", self.timeout))
        response = self.session.get(
            safe_url,
            headers=self._get_headers(),
            timeout=timeout,
            stream=True,
            allow_redirects=False,
        )
        temporary_path = None
        try:
            if response.status_code != 200:
                response.raise_for_status()
                raise requests.RequestException(
                    f"Unexpected SAPL PDF download status: {response.status_code}"
                )
            content_length = str(response.headers.get("Content-Length", "")).strip()
            if content_length and not content_length.isdigit():
                raise ValueError("SAPL PDF Content-Length is invalid")
            if content_length and int(content_length) > max_bytes:
                raise ValueError("SAPL PDF exceeds the configured download byte limit")

            fd, temporary_path = tempfile.mkstemp(
                prefix=f".{target.name}.", suffix=".part", dir=str(target.parent)
            )
            digest = hashlib.sha256()
            total = 0
            prefix = b""
            with os.fdopen(fd, "wb") as destination:
                for chunk in response.iter_content(chunk_size=64 * 1024):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("SAPL PDF exceeded the configured download byte limit")
                    if len(prefix) < 5:
                        prefix += chunk[: 5 - len(prefix)]
                    digest.update(chunk)
                    destination.write(chunk)
                destination.flush()
                os.fsync(destination.fileno())

            if total == 0 or not prefix.startswith(b"%PDF-"):
                raise ValueError("SAPL response is empty or does not contain a PDF")
            os.link(temporary_path, target)
            return {
                "path": str(target),
                "content_sha256": digest.hexdigest(),
                "size_bytes": total,
                "etag": str(response.headers.get("ETag", "")).strip(),
                "last_modified": str(response.headers.get("Last-Modified", "")).strip(),
            }
        finally:
            response.close()
            if temporary_path:
                try:
                    os.unlink(temporary_path)
                except FileNotFoundError:
                    pass

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
