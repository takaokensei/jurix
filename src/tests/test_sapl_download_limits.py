import hashlib
from pathlib import Path
from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from src.clients.sapl.sapl_client import SaplAPIClient


class SaplDownloadLimitTests(SimpleTestCase):
    def test_fingerprint_prefers_strong_etag_without_downloading_pdf(self):
        client = SaplAPIClient(base_url="https://sapl.test/api", timeout=1)
        head = Mock()
        head.status_code = 200
        head.headers = {"ETag": '"revision-1"'}
        client.session.head = Mock(return_value=head)
        client.session.get = Mock()
        try:
            assert client.fingerprint_pdf("https://sapl.test/media/law.pdf") == 'etag:"revision-1"'
            client.session.head.assert_called_once()
            client.session.get.assert_not_called()
            assert client.session.head.call_args.kwargs["allow_redirects"] is False
        finally:
            client.close()

    @override_settings(SAPL_SYNC_PDF_FINGERPRINT_MAX_BYTES=10)
    def test_fingerprint_hashes_bounded_response_when_validators_are_missing(self):
        client = SaplAPIClient(base_url="https://sapl.test/api", timeout=1)
        head = Mock()
        head.status_code = 200
        head.headers = {}
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "8"}
        response.iter_content.return_value = [b"%PDF", b"-1.7"]
        client.session.head = Mock(return_value=head)
        client.session.get = Mock(return_value=response)
        try:
            result = client.fingerprint_pdf("https://sapl.test/media/law.pdf")
            assert result == f"sha256:{hashlib.sha256(b'%PDF-1.7').hexdigest()}"
            client.session.get.assert_called_once()
            assert client.session.get.call_args.kwargs["allow_redirects"] is False
        finally:
            client.close()

    @override_settings(SAPL_SYNC_PDF_FINGERPRINT_MAX_BYTES=3)
    def test_fingerprint_rejects_oversized_pdf_without_claiming_identity(self):
        client = SaplAPIClient(base_url="https://sapl.test/api", timeout=1)
        head = Mock()
        head.status_code = 200
        head.headers = {}
        response = Mock()
        response.status_code = 200
        response.headers = {"Content-Length": "4"}
        client.session.head = Mock(return_value=head)
        client.session.get = Mock(return_value=response)
        try:
            try:
                client.fingerprint_pdf("https://sapl.test/media/law.pdf")
            except ValueError as exc:
                assert "byte limit" in str(exc)
            else:
                raise AssertionError("an oversized PDF must not receive a complete fingerprint")
        finally:
            client.close()

    def test_fingerprint_rejects_cross_origin_pdf_url_before_request(self):
        client = SaplAPIClient(base_url="https://sapl.test/api", timeout=1)
        client.session.head = Mock()
        try:
            try:
                client.fingerprint_pdf("https://other.test/law.pdf")
            except ValueError as exc:
                assert "origin" in str(exc)
            else:
                raise AssertionError("a cross-origin PDF URL must be rejected")
            client.session.head.assert_not_called()
        finally:
            client.close()

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
