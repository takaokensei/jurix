from pathlib import Path
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from src.clients.sapl.sapl_client import SaplAPIClient


class SaplDownloadLimitTests(SimpleTestCase):
    @override_settings(SAPL_DOWNLOAD_MAX_BYTES=10)
    @patch("src.clients.sapl.sapl_client.requests.Session.get")
    def test_download_rejects_oversized_content_length(self, mocked_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.headers = {"Content-Length": "11"}
        mocked_get.return_value = response
        client = SaplAPIClient(timeout=1)
        target = Path("/tmp/jurix-test-limit.pdf")
        target.unlink(missing_ok=True)
        try:
            assert client.download_pdf("https://example.test/a.pdf", str(target)) is False
            assert not target.exists()
        finally:
            target.unlink(missing_ok=True)
            client.close()

    @override_settings(SAPL_DOWNLOAD_MAX_BYTES=10)
    @patch("src.clients.sapl.sapl_client.requests.Session.get")
    def test_download_rejects_stream_that_exceeds_limit(self, mocked_get):
        response = Mock()
        response.raise_for_status.return_value = None
        response.headers = {}
        response.iter_content.return_value = [b"123456", b"78901"]
        mocked_get.return_value = response
        client = SaplAPIClient(timeout=1)
        target = Path("/tmp/jurix-test-stream-limit.pdf")
        target.unlink(missing_ok=True)
        try:
            assert client.download_pdf("https://example.test/a.pdf", str(target)) is False
            assert not target.exists()
        finally:
            target.unlink(missing_ok=True)
            client.close()
