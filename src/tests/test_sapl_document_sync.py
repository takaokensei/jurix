import hashlib
from pathlib import Path

import pytest

from src.apps.ingestion import sapl_sync
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.operations.models import SaplSyncState

pytestmark = pytest.mark.django_db


class Pages:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def fetch_normas_page(self, *, limit, offset, tipo=None, ano=None):
        return self.pages.get(offset, {"results": []})

    def validate_pagination_url(self, url):
        if not str(url).startswith("https://sapl.test/api/"):
            raise ValueError("foreign pagination host")
        return url

    def fingerprint_pdf(self, _url):
        return "etag:stable-test-pdf"

    def close(self):
        self.closed = True


def _payload(sapl_id):
    return {
        "id": sapl_id,
        "tipo": {"descricao": "Lei"},
        "numero": str(sapl_id),
        "ano": 2026,
        "ementa": "Ato de teste",
    }


class CandidatePages(Pages):
    def __init__(self, pages, *, body, fingerprint):
        super().__init__(pages)
        self.body = body
        self.remote_fingerprint = fingerprint
        self.downloads = 0

    def fingerprint_pdf(self, _url):
        return self.remote_fingerprint

    def download_pdf_version(self, _url, destination):
        self.downloads += 1
        Path(destination).write_bytes(self.body)
        return {
            "content_sha256": hashlib.sha256(self.body).hexdigest(),
            "size_bytes": len(self.body),
            "etag": self.remote_fingerprint.removeprefix("etag:"),
            "last_modified": "",
        }

    def _validated_sapl_pdf_url(self, url):
        return url


def test_incomplete_declared_count_aborts_before_marking_local_normas_missing(monkeypatch):
    missing = Norma.objects.create(tipo="Lei", numero="999", ano=2025, sapl_id=999)
    present = _payload(10)
    Norma.objects.create(
        tipo="Lei", numero="10", ano=2026, sapl_id=10,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(present)},
    )
    client = Pages({0: {"count": 2, "next": None, "results": [present]}})
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)
    monkeypatch.setattr(sapl_sync, "_process_payload", lambda payload, **_kwargs: (sapl_sync.payload_hash(payload), payload["id"]))

    with pytest.raises(RuntimeError, match="contagem declarada|recebido"):
        sapl_sync.run_full_sync(limit=10)

    missing.refresh_from_db()
    assert missing.needs_review is False
    assert client.closed is True
    assert SaplSyncState.objects.filter(source="sapl").exists()


def test_repeated_overlapping_pages_abort_full_scan(monkeypatch):
    missing = Norma.objects.create(tipo="Lei", numero="998", ano=2025, sapl_id=998)
    item = _payload(10)
    Norma.objects.create(
        tipo="Lei", numero="10", ano=2026, sapl_id=10,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(item)},
    )
    client = Pages({
        0: {"count": 3, "results": [item]},
        1: {"count": 3, "results": [item]},
    })
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)
    monkeypatch.setattr(sapl_sync, "_process_payload", lambda payload, **_kwargs: (sapl_sync.payload_hash(payload), payload["id"]))

    with pytest.raises(RuntimeError, match="sobrepostas|repetiu uma página"):
        sapl_sync.run_full_sync(limit=1)

    missing.refresh_from_db()
    assert missing.needs_review is False
    assert client.closed is True


def test_full_sync_timeout_does_not_mark_remote_missing(monkeypatch):
    import requests

    missing = Norma.objects.create(tipo="Lei", numero="997", ano=2025, sapl_id=997)
    item = _payload(11)
    item["texto_integral"] = "https://sapl.test/media/test.pdf"
    client = Pages({0: {"count": 1, "next": None, "results": [item]}})

    def timeout(_url):
        raise requests.Timeout("controlled QA timeout")

    client.fingerprint_pdf = timeout
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)

    with pytest.raises(requests.Timeout):
        sapl_sync.run_full_sync(limit=10)

    missing.refresh_from_db()
    state = SaplSyncState.objects.get(source="sapl")
    assert missing.needs_review is False
    assert state.last_success_at is None
    assert "timeout" in state.last_error.lower()
    assert client.closed is True


def test_full_sync_resumes_from_checkpoint_before_marking_missing(monkeypatch, settings):
    settings.SAPL_FULL_SYNC_MAX_PAGES = 1
    missing = Norma.objects.create(tipo="Lei", numero="999", ano=2025, sapl_id=999)
    first = _payload(20)
    second = _payload(21)
    Norma.objects.create(
        tipo="Lei", numero="20", ano=2026, sapl_id=20,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(first)},
    )
    Norma.objects.create(
        tipo="Lei", numero="21", ano=2026, sapl_id=21,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(second)},
    )
    first_client = Pages({
        0: {
            "count": 2,
            "next": "https://sapl.test/api/norma/normajuridica/?offset=1",
            "results": [first],
        }
    })
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: first_client)

    with pytest.raises(RuntimeError, match="excedeu SAPL_FULL_SYNC_MAX_PAGES"):
        sapl_sync.run_full_sync(limit=1)

    scope = sapl_sync._scope_fingerprint(None, None) + ":full"
    scope_hash = sapl_sync.hashlib.sha256(scope.encode("utf-8")).hexdigest()
    state = SaplSyncState.objects.get(source="sapl", filter_fingerprint=scope_hash)
    assert state.last_cursor == 1
    assert state.last_sync_count == 1
    assert state.full_sweep_token
    missing.refresh_from_db()
    assert missing.needs_review is False

    settings.SAPL_FULL_SYNC_MAX_PAGES = 10
    second_client = Pages({
        1: {"count": 2, "next": None, "results": [second]},
    })
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: second_client)
    result = sapl_sync.run_full_sync(limit=1)

    assert result["success"] is True
    assert result["fetched"] == 2
    assert result["missing_marked_for_review"] >= 1
    missing.refresh_from_db()
    assert missing.needs_review is True
    state.refresh_from_db()
    assert state.last_cursor == 0
    assert state.full_sweep_token == ""
    assert state.last_full_sync_at is not None


def test_pdf_only_change_stages_one_pending_candidate_and_preserves_accepted_source(
    monkeypatch, settings, tmp_path
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    settings.QA_ROOT = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.NORMATIVE_ARCHIVE_ROOT = tmp_path / "media" / "normative-archive"
    settings.NORMATIVE_ARCHIVE_ENABLED = True
    payload = _payload(60)
    payload["texto_integral"] = "https://sapl.test/media/lei-60.pdf"
    norma = Norma.objects.create(
        tipo="Lei",
        numero="60",
        ano=2026,
        sapl_id=60,
        status="consolidated",
        pdf_path="accepted/lei-60.pdf",
        texto_consolidado="Texto atualmente aceito",
        sapl_metadata={
            "_jurix_source_hash": sapl_sync.payload_hash(payload),
            "_jurix_pdf_fingerprint": 'etag:"v1"',
        },
    )
    body = b"%PDF-1.7\nnew pending SAPL revision"
    digest = hashlib.sha256(body).hexdigest()

    first_client = CandidatePages(
        {0: {"count": 1, "next": None, "results": [payload]}},
        body=body,
        fingerprint='etag:"v2"',
    )
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: first_client)
    first = sapl_sync.run_incremental_sync(limit=10)

    norma.refresh_from_db()
    pending = norma.sapl_metadata["_jurix_pending_pdf_change"]
    candidate = DocumentoNormativo.objects.get(public_id=pending["document_public_id"])
    assert first["changed"] == 1
    assert candidate.norma_id == norma.pk
    assert candidate.content_sha256 == digest
    assert candidate.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert candidate.condition_of_use == DocumentoNormativo.ConditionOfUse.UNKNOWN
    assert candidate.extraction_status == DocumentoNormativo.ExtractionStatus.PENDING
    assert pending["document_key"] == candidate.document_key
    assert candidate.storage_key == (
        Path("sha256") / digest[:2] / digest[2:4] / f"{digest}.pdf"
    ).as_posix()
    assert (settings.NORMATIVE_ARCHIVE_ROOT / candidate.storage_key).read_bytes() == body
    assert norma.pdf_path == "accepted/lei-60.pdf"
    assert norma.texto_consolidado == "Texto atualmente aceito"
    assert norma.status == "consolidated"
    assert first_client.downloads == 1

    second_client = CandidatePages(
        {0: {"count": 1, "next": None, "results": [payload]}},
        body=body,
        fingerprint='etag:"v2"',
    )
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: second_client)
    second = sapl_sync.run_incremental_sync(limit=10)

    norma.refresh_from_db()
    assert second["changed"] == 0
    assert second["unchanged"] == 1
    assert DocumentoNormativo.objects.filter(norma=norma).count() == 1
    assert norma.sapl_metadata["_jurix_pending_pdf_change"]["document_public_id"] == str(
        candidate.public_id
    )
    assert second_client.downloads == 0


def test_full_sweep_stages_changed_pdf_as_pending_candidate(monkeypatch, settings, tmp_path):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    settings.QA_ROOT = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.NORMATIVE_ARCHIVE_ROOT = tmp_path / "media" / "normative-archive"
    settings.NORMATIVE_ARCHIVE_ENABLED = True
    payload = _payload(61)
    payload["texto_integral"] = "https://sapl.test/media/lei-61.pdf"
    norma = Norma.objects.create(
        tipo="Lei",
        numero="61",
        ano=2026,
        sapl_id=61,
        status="consolidated",
        pdf_path="accepted/lei-61.pdf",
        texto_consolidado="Texto atualmente aceito",
        sapl_metadata={
            "_jurix_source_hash": sapl_sync.payload_hash(payload),
            "_jurix_pdf_fingerprint": 'etag:"v1"',
        },
    )
    body = b"%PDF-1.7\nfull sweep pending revision"
    digest = hashlib.sha256(body).hexdigest()
    client = CandidatePages(
        {0: {"count": 1, "next": None, "results": [payload]}},
        body=body,
        fingerprint='etag:"v2"',
    )
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)

    result = sapl_sync.run_full_sync(limit=10)

    norma.refresh_from_db()
    pending = norma.sapl_metadata["_jurix_pending_pdf_change"]
    candidate = DocumentoNormativo.objects.get(public_id=pending["document_public_id"])
    assert result["success"] is True
    assert result["changed"] == 1
    assert candidate.norma_id == norma.pk
    assert candidate.content_sha256 == digest
    assert candidate.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert pending["document_key"] == candidate.document_key
    assert (settings.NORMATIVE_ARCHIVE_ROOT / candidate.storage_key).read_bytes() == body
    assert norma.pdf_path == "accepted/lei-61.pdf"
    assert norma.texto_consolidado == "Texto atualmente aceito"
    assert norma.status == "consolidated"
    assert client.downloads == 1
