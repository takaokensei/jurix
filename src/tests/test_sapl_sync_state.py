import pytest

from src.apps.ingestion import sapl_sync
from src.apps.legislation.models import Norma
from src.apps.operations.models import SaplSyncState

pytestmark = pytest.mark.django_db


class FakeClient:
    def __init__(self, pages):
        self.pages = pages
        self.closed = False

    def fetch_normas_page(self, *, limit, offset, tipo=None, ano=None):
        return self.pages.get(offset, {"count": 0, "next": None, "previous": None, "results": []})

    def fingerprint_pdf(self, _url):
        return "etag:stable-test-pdf"

    def validate_pagination_url(self, url):
        if not str(url).startswith("https://example.invalid/api/"):
            raise ValueError("foreign pagination host")
        return url

    def close(self):
        self.closed = True


def payload(sapl_id, *, title="Lei", updated_at=None):
    data = {
        "id": sapl_id,
        "tipo": {"descricao": "Lei"},
        "numero": str(sapl_id),
        "ano": 2026,
        "ementa": title,
        "texto_integral": f"https://example.invalid/{sapl_id}.pdf",
    }
    if updated_at:
        data["updated_at"] = updated_at
    return data


def test_scope_fingerprint_is_stable():
    assert sapl_sync._scope_fingerprint(None, None) == sapl_sync._scope_fingerprint(None, None)
    assert sapl_sync._scope_fingerprint("Lei", 2026) != sapl_sync._scope_fingerprint("Lei", 2025)


def test_payload_hash_changes_when_source_changes():
    a = payload(10, title="A")
    b = payload(10, title="B")
    assert sapl_sync.payload_hash(a) != sapl_sync.payload_hash(b)


def test_incremental_sync_stops_on_unchanged_page(monkeypatch, settings):
    settings.SAPL_INCREMENTAL_MAX_PAGES = 5
    p = payload(10, title="A")
    digest = sapl_sync.payload_hash(p)
    Norma.objects.create(
        tipo="Lei",
        numero="10",
        ano=2026,
        ementa="A",
        sapl_id=10,
        sapl_metadata={"_jurix_source_hash": digest},
    )
    fake = FakeClient(
        {
            0: {
                "count": 2,
                "next": "https://example.invalid/api/norma/normajuridica/?offset=1",
                "results": [p],
            },
        }
    )
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)

    result = sapl_sync.run_incremental_sync(limit=10)

    assert result["success"] is True
    assert result["safe_stop"] is True
    assert result["unchanged"] == 1
    assert result["pages"] == 1
    state = SaplSyncState.objects.get(source="sapl")
    assert state.last_cursor == 0
    assert state.last_success_at is not None
    assert fake.closed is True


def test_pdf_only_change_creates_review_candidate_without_replacing_local_source(monkeypatch):
    p = payload(55, title="Original")
    norma = Norma.objects.create(
        tipo="Lei",
        numero="55",
        ano=2026,
        ementa="Original",
        sapl_id=55,
        status="consolidated",
        pdf_path="qa/current-55.pdf",
        texto_consolidado="Texto atualmente aceito",
        sapl_metadata={
            "_jurix_source_hash": sapl_sync.payload_hash(p),
            "_jurix_pdf_fingerprint": "etag:old-version",
        },
    )
    fake = FakeClient({0: {"count": 1, "next": None, "results": [p]}})
    fake.fingerprint_pdf = lambda _url: "etag:new-version"
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)
    staging_calls = []
    monkeypatch.setattr(
        sapl_sync,
        "_stage_pending_pdf_candidate",
        lambda _client, _payload, fingerprint: staging_calls.append(fingerprint) or False,
    )

    first = sapl_sync.run_incremental_sync(limit=10)
    norma.refresh_from_db()

    assert first["changed"] == 1
    assert norma.needs_review is True
    assert norma.status == "consolidated"
    assert norma.pdf_path == "qa/current-55.pdf"
    assert norma.texto_consolidado == "Texto atualmente aceito"
    assert norma.sapl_metadata["_jurix_pending_pdf_change"]["fingerprint"] == "etag:new-version"
    assert staging_calls == ["etag:new-version"]

    fake = FakeClient({0: {"count": 1, "next": None, "results": [p]}})
    fake.fingerprint_pdf = lambda _url: "etag:new-version"
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)
    repeated = sapl_sync.run_incremental_sync(limit=10)
    assert repeated["changed"] == 0
    assert repeated["unchanged"] == 1
    # The fake staging service leaves the pending item unattached, so a later
    # sync retries candidate creation rather than marking it complete.
    assert staging_calls == ["etag:new-version", "etag:new-version"]


def test_metadata_update_still_processes_record_and_passes_pdf_fingerprint(monkeypatch):
    old = payload(56, title="Ementa anterior")
    updated = payload(56, title="Ementa atualizada")
    Norma.objects.create(
        tipo="Lei",
        numero="56",
        ano=2026,
        ementa="Ementa anterior",
        sapl_id=56,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(old)},
    )
    fake = FakeClient({0: {"count": 1, "next": None, "results": [updated]}})
    calls = []
    fake.fingerprint_pdf = lambda _url: "etag:pdf-56"
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)
    monkeypatch.setattr(
        sapl_sync,
        "_process_payload",
        lambda value, **kwargs: calls.append((value, kwargs)) or (sapl_sync.payload_hash(value), value["id"]),
    )

    result = sapl_sync.run_incremental_sync(limit=10)

    assert result["changed"] == 1
    assert len(calls) == 1
    assert calls[0][0]["ementa"] == "Ementa atualizada"
    assert calls[0][1]["pdf_fingerprint"] == "etag:pdf-56"


def test_pdf_fingerprint_timeout_preserves_incremental_cursor(monkeypatch):
    import requests

    scope = sapl_sync._scope_fingerprint(None, None)
    SaplSyncState.objects.create(source="sapl", filter_fingerprint=scope, last_cursor=17)
    p = payload(57)
    fake = FakeClient({17: {"count": 1, "next": None, "results": [p]}})

    def timeout(_url):
        raise requests.Timeout("controlled QA timeout")

    fake.fingerprint_pdf = timeout
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)

    with pytest.raises(requests.Timeout):
        sapl_sync.run_incremental_sync(limit=10)

    state = SaplSyncState.objects.get(source="sapl", filter_fingerprint=scope)
    assert state.last_cursor == 17
    assert state.last_success_at is None
    assert "timeout" in state.last_error.lower()
    assert fake.closed is True


def test_full_sync_marks_missing_normas(monkeypatch):
    Norma.objects.create(
        tipo="Lei",
        numero="999",
        ano=2025,
        ementa="local only",
        sapl_id=999,
        sapl_metadata={},
    )
    present = payload(10)
    fake = FakeClient(
        {
            0: {"count": 1, "next": None, "previous": None, "results": [present]},
        }
    )
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)
    monkeypatch.setattr(
        sapl_sync,
        "_process_payload",
        lambda value, **_kwargs: (sapl_sync.payload_hash(value), int(value["id"])),
    )

    # Existing record is already considered current, so the test focuses on
    # the missing-record reconciliation path.
    Norma.objects.create(
        tipo="Lei",
        numero="10",
        ano=2026,
        sapl_id=10,
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(present)},
    )
    Norma.objects.filter(sapl_id=10).update(
        sapl_metadata={"_jurix_source_hash": sapl_sync.payload_hash(present)}
    )

    result = sapl_sync.run_full_sync(limit=10)

    assert result["success"] is True
    assert result["missing_marked_for_review"] >= 1
    missing = Norma.objects.get(sapl_id=999)
    assert missing.needs_review is True
    assert "não localizada no SAPL" in missing.processing_error
    assert fake.closed is True


def test_sync_state_has_independent_filter_scopes():
    SaplSyncState.objects.create(
        source="sapl",
        filter_fingerprint="a" * 64,
    )
    SaplSyncState.objects.create(
        source="sapl",
        filter_fingerprint="b" * 64,
    )
    assert SaplSyncState.objects.filter(source="sapl").count() == 2
