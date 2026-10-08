import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import fitz
import pytest

from src.apps.ingestion import sapl_sync
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.operations.models import SaplSyncState
from src.clients.sapl.sapl_client import SaplAPIClient

pytestmark = pytest.mark.django_db


class Pages:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def fetch_normas_page(self, *, limit, offset, tipo=None, ano=None):
        return self.pages.get(offset, {"results": []})

    def _make_request_url(self, url):
        query = parse_qs(urlparse(url).query)
        offset = int(query.get("offset", [0])[0])
        return self.pages.get(offset, {"results": []})

    def build_normas_page_url(self, page, *, tipo=None, ano=None):
        params = {"page": page}
        if tipo:
            params["tipo"] = tipo
        if ano:
            params["ano"] = ano
        from urllib.parse import urlencode

        return f"https://sapl.test/api/norma/normajuridica/?{urlencode(params)}"

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


def _pdf_bytes(text):
    with fitz.open() as document:
        page = document.new_page()
        page.insert_text((72, 72), text)
        return document.tobytes()


def _nested_page(page, start, results, *, total=3, next_page=None, total_pages=None):
    return {
        "results": results,
        "_jurix_pagination": {
            "page": page,
            "total_pages": total_pages or (total + 1) // 2,
            "total_entries": total,
            "start_index": start,
            "end_index": start + len(results) - 1,
        },
        "count": total,
        "next": (
            f"https://sapl.test/api/norma/normajuridica/?page={next_page}"
            if next_page
            else None
        ),
    }


def test_incremental_resume_page_url_preserves_filters():
    client = Pages({})
    page = _nested_page(4, 31, [_payload(31)])

    url = sapl_sync._page_start_url(
        client, page, tipo="Lei Complementar", ano=2026
    )

    assert parse_qs(urlparse(url).query) == {
        "page": ["4"],
        "tipo": ["Lei Complementar"],
        "ano": ["2026"],
    }


def test_nested_sapl_pagination_resumes_from_the_validated_next_url(monkeypatch, settings):
    settings.SAPL_FULL_SYNC_MAX_PAGES = 1
    missing = Norma.objects.create(tipo="Lei", numero="999", ano=2025, sapl_id=999)
    records = [_payload(31), _payload(32), _payload(33)]
    for record in records:
        Norma.objects.create(
            tipo="Lei",
            numero=str(record["id"]),
            ano=2026,
            sapl_id=record["id"],
            sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(record)},
        )
    next_url = "https://sapl.test/api/norma/normajuridica/?page=2"
    first_page = _nested_page(1, 1, records[:2], next_page=2)
    first_client = Pages({0: first_page})

    class PageResumeClient(Pages):
        def __init__(self, pages_by_number):
            super().__init__({})
            self.pages_by_number = pages_by_number
            self.requested_urls = []

        def _make_request_url(self, url):
            self.requested_urls.append(url)
            page_number = int(parse_qs(urlparse(url).query)["page"][0])
            return self.pages_by_number[page_number]

    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: first_client)
    with pytest.raises(RuntimeError, match="excedeu SAPL_FULL_SYNC_MAX_PAGES"):
        sapl_sync.run_full_sync(limit=50)

    scope = sapl_sync._scope_fingerprint(None, None) + ":full"
    scope_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    state = SaplSyncState.objects.get(source="sapl", filter_fingerprint=scope_hash)
    assert state.last_cursor == 2
    assert state.last_cursor_url == next_url
    missing.refresh_from_db()
    assert missing.needs_review is False

    second_client = PageResumeClient(
        {2: _nested_page(2, 3, records[2:], total=3)}
    )
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: second_client)
    result = sapl_sync.run_full_sync(limit=50)

    assert second_client.requested_urls == [next_url]
    assert result["success"] is True
    assert result["fetched"] == 3
    assert result["missing_marked_for_review"] >= 1
    state.refresh_from_db()
    assert state.last_cursor == 0
    assert state.last_cursor_url == ""


def test_nested_sapl_page_retry_skips_only_committed_prefix(monkeypatch, settings):
    records = [_payload(41), _payload(42)]
    records[1]["texto_integral"] = "https://sapl.test/media/qa.pdf"
    for record in records:
        Norma.objects.create(
            tipo="Lei",
            numero=str(record["id"]),
            ano=2026,
            sapl_id=record["id"],
            sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(record)},
        )
    page = _nested_page(1, 1, records, total=2)
    page["_jurix_pagination"]["total_pages"] = 1
    client = Pages({0: page})
    calls = 0

    def fail_once(_url):
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("controlled QA page interruption")
        return "etag:stable-test-pdf"

    page["results"] = records
    client.fingerprint_pdf = fail_once
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)

    with pytest.raises(RuntimeError, match="controlled QA page interruption"):
        sapl_sync.run_full_sync(limit=50)

    scope = sapl_sync._scope_fingerprint(None, None) + ":full"
    scope_hash = hashlib.sha256(scope.encode("utf-8")).hexdigest()
    state = SaplSyncState.objects.get(source="sapl", filter_fingerprint=scope_hash)
    assert state.last_cursor == 1
    assert state.last_cursor_url.endswith("?page=1")

    client.fingerprint_pdf = lambda _url: "etag:stable-test-pdf"
    client.pages[0] = page
    result = sapl_sync.run_full_sync(limit=50)
    assert result["success"] is True
    assert result["fetched"] == 2


def test_incremental_sync_follows_nested_next_until_first_unchanged_page(monkeypatch):
    changed_payload = _payload(51)
    unchanged_payload = _payload(52)
    Norma.objects.create(
        tipo="Lei",
        numero="51",
        ano=2026,
        sapl_id=51,
        sapl_metadata={"_jurix_source_hash": "older-hash"},
    )
    Norma.objects.create(
        tipo="Lei",
        numero="52",
        ano=2026,
        sapl_id=52,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(unchanged_payload)},
    )
    next_url = "https://sapl.test/api/norma/normajuridica/?page=2"
    page1 = _nested_page(
        1, 1, [changed_payload], total=2, total_pages=2, next_page=2
    )
    page2 = _nested_page(2, 2, [unchanged_payload], total=2, total_pages=2)

    class IncrementalPages(Pages):
        def __init__(self):
            super().__init__({0: page1})
            self.requested_urls = []

        def _make_request_url(self, url):
            self.requested_urls.append(url)
            assert url == next_url
            return page2

    client = IncrementalPages()
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)
    monkeypatch.setattr(
        sapl_sync,
        "_process_payload",
        lambda payload, **_kwargs: (sapl_sync.payload_hash(payload), payload["id"]),
    )

    result = sapl_sync.run_incremental_sync(limit=50)

    assert result["success"] is True
    assert result["pages"] == 2
    assert result["fetched"] == 2
    assert result["changed"] == 1
    assert result["unchanged"] == 1
    assert client.requested_urls == [next_url]


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
    body = _pdf_bytes("new pending SAPL revision")
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
    body = _pdf_bytes("full sweep pending revision")
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


def test_metadata_and_pdf_change_preserves_accepted_source_and_stages_candidate(
    monkeypatch, settings, tmp_path
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    settings.QA_ROOT = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.NORMATIVE_ARCHIVE_ROOT = tmp_path / "media" / "normative-archive"
    settings.NORMATIVE_ARCHIVE_ENABLED = True
    original = _payload(62)
    original["texto_integral"] = "https://sapl.test/media/lei-62-original.pdf"
    norma = Norma.objects.create(
        tipo="Lei",
        numero="62",
        ano=2026,
        sapl_id=62,
        status="consolidated",
        pdf_url=original["texto_integral"],
        pdf_path="accepted/lei-62.pdf",
        texto_consolidado="Texto oficialmente aceito",
        sapl_metadata={
            "_jurix_source_hash": sapl_sync.payload_hash(original),
            "_jurix_pdf_fingerprint": 'etag:"v1"',
        },
    )
    updated = {**original, "ementa": "Ementa corrigida no catálogo"}
    updated["texto_integral"] = "https://sapl.test/media/lei-62-republicada.pdf"
    body = _pdf_bytes("new PDF stays pending review")
    client = CandidatePages(
        {0: {"count": 1, "next": None, "results": [updated]}},
        body=body,
        fingerprint='etag:"v2"',
    )
    fingerprint_calls = []
    original_fingerprint = client.fingerprint_pdf
    client.fingerprint_pdf = lambda url: fingerprint_calls.append(url) or original_fingerprint(url)
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)

    from src.apps.ingestion import core_tasks

    def unexpected_download(*_args, **_kwargs):
        raise AssertionError("catalogue sync must not enqueue an automatic PDF download")

    monkeypatch.setattr(core_tasks.download_pdf_task, "delay", unexpected_download)

    result = sapl_sync.run_incremental_sync(limit=10)

    norma.refresh_from_db()
    metadata = norma.sapl_metadata
    assert fingerprint_calls == [updated["texto_integral"]], fingerprint_calls
    assert norma.needs_review is True
    assert "_jurix_pending_pdf_change" in metadata
    pending = metadata["_jurix_pending_pdf_change"]
    candidate = DocumentoNormativo.objects.get(public_id=pending["document_public_id"])
    assert result["changed"] == 1
    assert norma.ementa == "Ementa corrigida no catálogo"
    assert metadata["texto_integral"] == updated["texto_integral"]
    assert metadata["_jurix_source_hash"] == sapl_sync.payload_hash(updated)
    assert metadata["_jurix_pdf_fingerprint"] == 'etag:"v1"'
    assert pending["fingerprint"] == 'etag:"v2"'
    assert candidate.official_url == updated["texto_integral"]
    assert candidate.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert norma.pdf_url == original["texto_integral"]
    assert norma.pdf_path == "accepted/lei-62.pdf"
    assert norma.texto_consolidado == "Texto oficialmente aceito"
    assert norma.status == "consolidated"
    assert norma.needs_review is True
    assert client.downloads == 1


def test_incremental_sync_stages_valid_pdf_through_real_client_and_loopback_http(
    monkeypatch, settings, tmp_path
):
    """Exercise pagination, PDF fingerprint/download, DB state and storage together."""
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    settings.QA_ROOT = tmp_path
    settings.MEDIA_ROOT = tmp_path / "media"
    settings.NORMATIVE_ARCHIVE_ROOT = tmp_path / "media" / "normative-archive"
    settings.NORMATIVE_ARCHIVE_ENABLED = True
    (settings.NORMATIVE_ARCHIVE_ROOT).mkdir(parents=True)

    body = _pdf_bytes("R23 local transport integration")
    requests_seen = []
    payload_holder = {}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_args):
            return

        def _send(self, status, content_type, content, *, etag=None):
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(content)))
            if etag:
                self.send_header("ETag", etag)
            self.end_headers()
            if self.command != "HEAD":
                self.wfile.write(content)

        def do_GET(self):
            requests_seen.append((self.command, self.path))
            if self.path.startswith("/api/norma/normajuridica/"):
                offset = int(parse_qs(urlparse(self.path).query).get("offset", ["0"])[0])
                records = [payload_holder["payload"]] if offset == 0 else []
                response = json.dumps(
                    {"count": 1, "next": None, "results": records}
                ).encode()
                self._send(200, "application/json", response)
            elif self.path == "/media/lei-77.pdf":
                self._send(200, "application/pdf", body, etag='"v2"')
            else:
                self._send(404, "text/plain", b"not found")

        def do_HEAD(self):
            requests_seen.append((self.command, self.path))
            if self.path == "/media/lei-77.pdf":
                self._send(200, "application/pdf", body, etag='"v2"')
            else:
                self._send(404, "text/plain", b"")

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    pdf_url = f"{base_url}/media/lei-77.pdf"
    payload = _payload(77)
    payload["texto_integral"] = pdf_url
    payload_holder["payload"] = payload
    norma = Norma.objects.create(
        tipo="Lei",
        numero="77",
        ano=2026,
        sapl_id=77,
        status="consolidated",
        pdf_url="https://sapl.test/media/lei-77-original.pdf",
        pdf_path="accepted/lei-77.pdf",
        texto_consolidado="Texto aceito antes da atualização remota",
        sapl_metadata={
            "_jurix_source_hash": sapl_sync.payload_hash(payload),
            "_jurix_pdf_fingerprint": 'etag:"v1"',
        },
    )
    monkeypatch.setattr(
        sapl_sync,
        "SaplAPIClient",
        lambda: SaplAPIClient(
            base_url=f"{base_url}/api", timeout=2, max_retries=0
        ),
    )

    try:
        result = sapl_sync.run_incremental_sync(limit=1)

        norma.refresh_from_db()
        pending = norma.sapl_metadata["_jurix_pending_pdf_change"]
        candidate = DocumentoNormativo.objects.get(public_id=pending["document_public_id"])
        stored_pdf = settings.NORMATIVE_ARCHIVE_ROOT / candidate.storage_key
        assert result["success"] is True
        assert result["changed"] == 1
        assert candidate.review_status == DocumentoNormativo.ReviewStatus.PENDING
        assert candidate.condition_of_use == DocumentoNormativo.ConditionOfUse.UNKNOWN
        assert candidate.content_sha256 == hashlib.sha256(body).hexdigest()
        assert stored_pdf.read_bytes() == body
        assert candidate.official_url == pdf_url
        assert pending["document_key"] == candidate.document_key
        assert norma.pdf_url == "https://sapl.test/media/lei-77-original.pdf"
        assert norma.pdf_path == "accepted/lei-77.pdf"
        assert norma.texto_consolidado == "Texto aceito antes da atualização remota"
        assert norma.needs_review is True
        assert ("HEAD", "/media/lei-77.pdf") in requests_seen
        assert ("GET", "/media/lei-77.pdf") in requests_seen
        assert any(
            method == "GET" and path.startswith("/api/norma/normajuridica/")
            for method, path in requests_seen
        )
    finally:
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)
