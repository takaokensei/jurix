import hashlib
import os
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import fitz
import pytest
import requests
from django.conf import settings
from django.test import SimpleTestCase, TransactionTestCase, override_settings

from src.apps.ingestion import sapl_sync
from src.apps.ingestion.sapl_document_sync import (
    SaplDocumentCandidateError,
    _storage_root,
    stage_sapl_pdf_candidate,
)
from src.apps.ingestion.tasks import _process_norma_data
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.operations.models import SaplSyncState
from src.clients.sapl.sapl_client import SaplAPIClient


def _pdf_bytes(text="candidate"):
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), text)
        return document.tobytes()


def _response(*, status=200, body=None, headers=None):
    if body is None:
        body = _pdf_bytes("qa")
    response = Mock()
    response.status_code = status
    response.headers = headers or {"Content-Length": str(len(body)), "ETag": '"v2"'}
    response.iter_content.return_value = [body]
    response.raise_for_status.return_value = None
    return response


class SaplPdfCandidateDownloadTests(SimpleTestCase):
    def setUp(self):
        self.client = SaplAPIClient(base_url="https://sapl.test/api", timeout=1)
        self.addCleanup(self.client.close)
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)

    def test_upgrades_same_origin_http_pdf_url_before_fingerprinting(self):
        response = _response(headers={"Content-Length": "123", "ETag": '"stable"'})
        self.client.session.head = Mock(return_value=response)
        self.client.session.get = Mock()

        fingerprint = self.client.fingerprint_pdf("http://sapl.test/media/law.pdf")

        assert fingerprint == 'etag:"stable"'
        self.client.session.head.assert_called_once()
        assert self.client.session.head.call_args.args[0] == "https://sapl.test/media/law.pdf"
        assert self.client.session.head.call_args.kwargs["allow_redirects"] is False
        self.client.session.get.assert_not_called()
        response.close.assert_called_once()

    def test_rejects_http_upgrade_from_nondefault_port(self):
        self.client.session.get = Mock()

        with pytest.raises(ValueError, match="origin"):
            self.client.download_pdf_version(
                "http://sapl.test:8080/media/law.pdf", self.tmp_path / "candidate.pdf"
            )

        self.client.session.get.assert_not_called()

    @pytest.mark.skipif(
        os.environ.get("JURIX_RUN_LIVE_SAPL_READONLY") != "1",
        reason="requires explicit opt-in for a public SAPL metadata/PDF HEAD check",
    )
    def test_live_sapl_http_media_url_has_a_fingerprint_without_redirect(self):
        client = SaplAPIClient(timeout=15, max_retries=0)
        try:
            payload = client.fetch_norma_by_id(4040)
            assert str(payload.get("numero")) == "7795"
            assert int(payload.get("ano")) == 2024
            pdf_url = str(payload.get("texto_integral") or "")
            assert pdf_url.startswith("http://sapl.natal.rn.leg.br/media/")

            fingerprint = client.fingerprint_pdf(pdf_url)

            assert fingerprint.startswith(("etag:", "last-modified:", "sha256:"))
            assert len(fingerprint) > len("etag:")
        finally:
            client.close()


    def test_downloads_bounded_pdf_atomically_and_returns_content_identity(self):
        body = _pdf_bytes("qa candidate")
        response = _response(body=body)
        self.client.session.get = Mock(return_value=response)
        target = self.tmp_path / "candidate.part.pdf"

        result = self.client.download_pdf_version(
            "https://sapl.test/media/law.pdf", target
        )

        assert target.read_bytes() == body
        assert result["content_sha256"] == hashlib.sha256(body).hexdigest()
        assert result["size_bytes"] == len(body)
        assert result["etag"] == '"v2"'
        self.client.session.get.assert_called_once()
        assert self.client.session.get.call_args.kwargs["allow_redirects"] is False
        assert list(self.tmp_path.iterdir()) == [target]
        response.close.assert_called_once()

    def test_rejects_cross_origin_url_without_network_request(self):
        self.client.session.get = Mock()

        with pytest.raises(ValueError, match="origin"):
            self.client.download_pdf_version(
                "https://foreign.test/media/law.pdf", self.tmp_path / "candidate.pdf"
            )

        self.client.session.get.assert_not_called()
        assert list(self.tmp_path.iterdir()) == []

    def test_refuses_redirect_response_without_following_it(self):
        response = _response(status=302, body=b"", headers={"Location": "https://foreign.test/file"})
        self.client.session.get = Mock(return_value=response)

        with pytest.raises(requests.RequestException, match="status: 302"):
            self.client.download_pdf_version(
                "https://sapl.test/media/law.pdf", self.tmp_path / "candidate.pdf"
            )

        assert self.client.session.get.call_args.kwargs["allow_redirects"] is False
        assert list(self.tmp_path.iterdir()) == []
        response.close.assert_called_once()

    @override_settings(SAPL_DOWNLOAD_MAX_BYTES=8)
    def test_rejects_oversized_content_length_and_cleans_staging_file(self):
        response = _response(body=b"", headers={"Content-Length": "9"})
        self.client.session.get = Mock(return_value=response)

        with pytest.raises(ValueError, match="byte limit"):
            self.client.download_pdf_version(
                "https://sapl.test/media/law.pdf", self.tmp_path / "candidate.pdf"
            )

        assert list(self.tmp_path.iterdir()) == []
        response.close.assert_called_once()

    @override_settings(SAPL_DOWNLOAD_MAX_BYTES=8)
    def test_rejects_stream_that_exceeds_limit_and_cleans_staging_file(self):
        response = _response(body=b"", headers={})
        response.iter_content.return_value = [b"%PDF-1.7", b"oversized"]
        self.client.session.get = Mock(return_value=response)

        with pytest.raises(ValueError, match="byte limit"):
            self.client.download_pdf_version(
                "https://sapl.test/media/law.pdf", self.tmp_path / "candidate.pdf"
            )

        assert list(self.tmp_path.iterdir()) == []
        response.close.assert_called_once()

    def test_rejects_non_pdf_payload_and_preserves_existing_target(self):
        response = _response(body=b"not a pdf")
        self.client.session.get = Mock(return_value=response)
        target = self.tmp_path / "candidate.pdf"
        target.write_bytes(b"existing version")

        with pytest.raises(ValueError, match="does not contain a PDF"):
            self.client.download_pdf_version(
                "https://sapl.test/media/law.pdf", self.tmp_path / "candidate.new.pdf"
            )

        with pytest.raises(FileExistsError, match="already exists"):
            self.client.download_pdf_version("https://sapl.test/media/law.pdf", target)

        self.client.session.get.assert_called_once()
        assert target.read_bytes() == b"existing version"
        assert sorted(path.name for path in self.tmp_path.iterdir()) == [
            "candidate.pdf",
        ]

    def test_rejects_signature_only_payload_and_cleans_staging_file(self):
        response = _response(body=b"%PDF-1.7\nnot a structurally valid PDF")
        self.client.session.get = Mock(return_value=response)
        target = self.tmp_path / "candidate.pdf"

        with pytest.raises(ValueError, match="structurally invalid"):
            self.client.download_pdf_version("https://sapl.test/media/law.pdf", target)

        assert not target.exists()
        assert list(self.tmp_path.iterdir()) == []
        response.close.assert_called_once()

    def test_rejects_password_protected_pdf(self):
        with fitz.open() as document:
            page = document.new_page()
            page.insert_text((72, 72), "restricted source")
            body = document.tobytes(
                encryption=fitz.PDF_ENCRYPT_AES_256,
                user_pw="qa-only",
                owner_pw="qa-owner-only",
            )
        response = _response(body=body)
        self.client.session.get = Mock(return_value=response)
        target = self.tmp_path / "encrypted.pdf"

        with pytest.raises(ValueError, match="password-protected"):
            self.client.download_pdf_version("https://sapl.test/media/law.pdf", target)

        assert not target.exists()
        response.close.assert_called_once()


class SaplPdfCandidateStagingTests(SimpleTestCase):
    def setUp(self):
        self._temporary_directory = tempfile.TemporaryDirectory()
        self.addCleanup(self._temporary_directory.cleanup)
        self.tmp_path = Path(self._temporary_directory.name)
        (self.tmp_path / "media").mkdir()
        previous_qa_only = os.environ.get("JURIX_QA_ONLY")
        os.environ["JURIX_QA_ONLY"] = "1"
        if previous_qa_only is None:
            self.addCleanup(os.environ.pop, "JURIX_QA_ONLY", None)
        else:
            self.addCleanup(os.environ.__setitem__, "JURIX_QA_ONLY", previous_qa_only)
        self.settings_override = override_settings(
            QA_ROOT=self.tmp_path,
            MEDIA_ROOT=self.tmp_path / "media",
            NORMATIVE_ARCHIVE_ROOT=self.tmp_path / "media" / "normative-archive",
            NORMATIVE_ARCHIVE_ENABLED=True,
        )
        self.settings_override.enable()
        self.addCleanup(self.settings_override.disable)

    def test_candidate_is_staged_by_hash_and_never_promoted(self):
        from unittest.mock import patch

        body = _pdf_bytes("immutable revision")
        digest = hashlib.sha256(body).hexdigest()
        norma = Norma(
            tipo="Lei",
            numero="55",
            ano=2026,
            sapl_id=55,
            identity_key="municipal:lei:55:2026",
            identity_json={"scope": "municipal"},
            pdf_path="accepted/current.pdf",
            texto_consolidado="Texto atualmente aceito",
        )
        client = Mock()

        def download(_url, destination):
            Path(destination).write_bytes(body)
            return {
                "content_sha256": digest,
                "size_bytes": len(body),
                "etag": '"revision-2"',
                "last_modified": "",
            }

        client.download_pdf_version.side_effect = download
        client._validated_sapl_pdf_url.return_value = "https://sapl.test/media/law.pdf"
        candidate = SimpleNamespace(
            content_sha256=digest,
            storage_key=(Path("sha256") / digest[:2] / digest[2:4] / f"{digest}.pdf").as_posix(),
        )
        with patch.object(
            DocumentoNormativo.objects,
            "filter",
            return_value=Mock(order_by=Mock(return_value=Mock(first=Mock(return_value=None)))),
        ), patch.object(
            DocumentoNormativo.objects,
            "get_or_create",
            return_value=(candidate, True),
        ) as get_or_create:
            result, created = stage_sapl_pdf_candidate(
                client=client,
                norma=norma,
                pdf_url="https://sapl.test/media/law.pdf",
                remote_fingerprint='etag:"revision-2"',
            )

        assert result is candidate
        assert created is True
        defaults = get_or_create.call_args.kwargs["defaults"]
        assert defaults["norma"] is norma
        assert defaults["role"] == DocumentoNormativo.Role.UNDETERMINED
        assert defaults["condition_of_use"] == DocumentoNormativo.ConditionOfUse.UNKNOWN
        assert defaults["review_status"] == DocumentoNormativo.ReviewStatus.PENDING
        assert defaults["extraction_status"] == DocumentoNormativo.ExtractionStatus.PENDING
        assert defaults["content_sha256"] == digest
        assert defaults["metadata_json"]["remote_fingerprint"] == 'etag:"revision-2"'
        assert norma.pdf_path == "accepted/current.pdf"
        assert norma.texto_consolidado == "Texto atualmente aceito"
        blob = self.tmp_path / "media" / "normative-archive" / defaults["storage_key"]
        assert blob.read_bytes() == body

    def test_candidate_rejects_download_that_does_not_match_observed_fingerprint(self):
        from unittest.mock import patch

        body = b"%PDF-1.7\nother revision"
        norma = Norma(tipo="Lei", numero="56", ano=2026, sapl_id=56)
        client = Mock()

        def download(_url, destination):
            Path(destination).write_bytes(body)
            return {
                "content_sha256": hashlib.sha256(body).hexdigest(),
                "size_bytes": len(body),
                "etag": '"other"',
                "last_modified": "",
            }

        client.download_pdf_version.side_effect = download
        with patch.object(
            DocumentoNormativo.objects,
            "filter",
            return_value=Mock(order_by=Mock(return_value=Mock(first=Mock(return_value=None)))),
        ), pytest.raises(SaplDocumentCandidateError, match="does not match"):
            stage_sapl_pdf_candidate(
                client=client,
                norma=norma,
                pdf_url="https://sapl.test/media/law.pdf",
                remote_fingerprint='etag:"observed"',
            )

        assert list((self.tmp_path / "media" / "normative-archive" / ".staging").iterdir()) == []

    def test_existing_fingerprint_candidate_is_reused_without_download(self):
        from unittest.mock import patch

        norma = Norma(tipo="Lei", numero="59", ano=2026, sapl_id=59)
        existing = SimpleNamespace(content_sha256="a" * 64, storage_key="sha256/existing.pdf")
        query = Mock()
        query.order_by.return_value.first.return_value = existing
        client = Mock()
        with patch.object(DocumentoNormativo.objects, "filter", return_value=query):
            candidate, created = stage_sapl_pdf_candidate(
                client=client,
                norma=norma,
                pdf_url="https://sapl.test/media/law.pdf",
                remote_fingerprint='etag:"already-staged"',
            )

        assert candidate is existing
        assert created is False
        client.download_pdf_version.assert_not_called()

    def test_qa_staging_refuses_a_storage_root_outside_the_qa_directory(self):
        outside = self.tmp_path.parent / f"{self.tmp_path.name}-outside"
        with override_settings(NORMATIVE_ARCHIVE_ROOT=outside), pytest.raises(
            SaplDocumentCandidateError, match="escaped the QA root"
        ):
            _storage_root()

    def test_disabled_archive_feature_refuses_before_download(self):
        norma = Norma(tipo="Lei", numero="60", ano=2026, sapl_id=60)
        client = Mock()
        with override_settings(NORMATIVE_ARCHIVE_ENABLED=False), pytest.raises(
            SaplDocumentCandidateError, match="disabled"
        ):
            stage_sapl_pdf_candidate(
                client=client,
                norma=norma,
                pdf_url="https://sapl.test/media/law.pdf",
                remote_fingerprint='etag:"disabled"',
            )

        client.download_pdf_version.assert_not_called()

    @override_settings(NORMATIVE_ARCHIVE_ENABLED=True)
    def test_pending_change_stages_and_attaches_candidate(self):
        from unittest.mock import patch

        fingerprint = 'etag:"revision-3"'
        norma = SimpleNamespace(
            sapl_id=57,
            sapl_metadata={"_jurix_pending_pdf_change": {"fingerprint": fingerprint}},
        )
        candidate = SimpleNamespace(public_id="candidate-uuid", document_key="candidate-key")
        client = Mock()
        with patch.object(
            Norma.objects,
            "filter",
            return_value=Mock(first=Mock(return_value=norma)),
        ), patch(
            "src.apps.ingestion.sapl_document_sync.stage_sapl_pdf_candidate",
            return_value=(candidate, True),
        ) as stage, patch.object(
            sapl_sync, "_attach_pdf_candidate", return_value=True
        ) as attach:
            staged = sapl_sync._stage_pending_pdf_candidate(
                client,
                {"id": 57, "texto_integral": "https://sapl.test/media/law.pdf"},
                fingerprint,
            )

        assert staged is True
        stage.assert_called_once_with(
            client=client,
            norma=norma,
            pdf_url="https://sapl.test/media/law.pdf",
            remote_fingerprint=fingerprint,
        )
        attach.assert_called_once_with(57, fingerprint, candidate)

    @override_settings(NORMATIVE_ARCHIVE_ENABLED=True)
    def test_attached_candidate_is_not_downloaded_again(self):
        from unittest.mock import patch

        fingerprint = 'etag:"revision-4"'
        norma = SimpleNamespace(
            sapl_id=58,
            sapl_metadata={
                "_jurix_pending_pdf_change": {
                    "fingerprint": fingerprint,
                    "document_public_id": "existing-candidate",
                }
            },
        )
        client = Mock()
        with patch.object(
            Norma.objects,
            "filter",
            return_value=Mock(first=Mock(return_value=norma)),
        ), patch.object(
            DocumentoNormativo.objects,
            "filter",
            return_value=Mock(exists=Mock(return_value=True)),
        ), patch(
            "src.apps.ingestion.sapl_document_sync.stage_sapl_pdf_candidate"
        ) as stage:
            staged = sapl_sync._stage_pending_pdf_candidate(
                client,
                {"id": 58, "texto_integral": "https://sapl.test/media/law.pdf"},
                fingerprint,
            )

        assert staged is False
        stage.assert_not_called()


class SaplLiveCandidateStagingTests(TransactionTestCase):
    """Opt-in public SAPL integration; all writes stay in QA test DB/temp storage."""

    @pytest.mark.skipif(
        os.environ.get("JURIX_RUN_LIVE_SAPL_READONLY") != "1",
        reason="requires explicit opt-in for one public SAPL PDF staging check",
    )
    def test_stages_one_real_sapl_pdf_as_unreviewed_and_is_idempotent(self):
        client = SaplAPIClient(timeout=20, max_retries=0)
        qa_root = Path(settings.QA_ROOT).resolve()
        temp_storage = tempfile.TemporaryDirectory(prefix="live-sapl-candidate-", dir=qa_root)
        self.addCleanup(temp_storage.cleanup)
        storage_root = Path(temp_storage.name).resolve()
        assert storage_root.is_relative_to(qa_root)

        try:
            payload = client.fetch_norma_by_id(4040)
            assert str(payload.get("numero")) == "7795"
            assert int(payload.get("ano")) == 2024
            pdf_url = str(payload.get("texto_integral") or "")
            assert pdf_url.startswith("http://sapl.natal.rn.leg.br/media/")

            fingerprint = client.fingerprint_pdf(pdf_url)
            with override_settings(NORMATIVE_ARCHIVE_ROOT=storage_root):
                result = _process_norma_data(payload, auto_download=False)
                norma = Norma.objects.get(pk=result["norma_id"])
                document, created = stage_sapl_pdf_candidate(
                    client=client,
                    norma=norma,
                    pdf_url=pdf_url,
                    remote_fingerprint=fingerprint,
                )
                repeated, repeated_created = stage_sapl_pdf_candidate(
                    client=client,
                    norma=norma,
                    pdf_url=pdf_url,
                    remote_fingerprint=fingerprint,
                )

            staged_path = storage_root / document.storage_key
            assert created is True
            assert repeated_created is False
            assert repeated.pk == document.pk
            assert document.source_kind == DocumentoNormativo.SourceKind.SAPL
            assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
            assert document.condition_of_use == DocumentoNormativo.ConditionOfUse.UNKNOWN
            assert document.official_url.startswith("https://sapl.natal.rn.leg.br/media/")
            assert document.content_sha256 == hashlib.sha256(staged_path.read_bytes()).hexdigest()
            assert staged_path.read_bytes().startswith(b"%PDF-")
            assert norma.pdf_path == ""
            assert norma.texto_consolidado == ""
        finally:
            client.close()

    @override_settings(SAPL_INCREMENTAL_MAX_PAGES=1)
    @pytest.mark.skipif(
        os.environ.get("JURIX_RUN_LIVE_SAPL_READONLY") != "1",
        reason="requires explicit opt-in for one bounded public SAPL sync page",
    )
    def test_live_incremental_sync_checkpoints_one_page_as_partial(self):
        from src.apps.ingestion.sapl_sync import _scope_fingerprint, run_incremental_sync

        result = run_incremental_sync(limit=50)

        assert result["pages"] == 1
        assert 0 < result["fetched"] <= 50
        assert result["partial"] is True
        assert result["safe_stop"] is False
        state = SaplSyncState.objects.get(
            source="sapl",
            filter_fingerprint=_scope_fingerprint(None, None),
        )
        assert state.last_cursor == result["cursor_end"] > 0
        assert state.last_cursor_url.startswith("https://sapl.natal.rn.leg.br/api/")
        assert state.last_success_at is None
        assert state.last_full_sync_at is None
