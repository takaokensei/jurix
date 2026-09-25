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
    fake = FakeClient({
        0: {"count": 2, "next": "x", "results": [p]},
    })
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
    fake = FakeClient({
        0: {"count": 1, "next": None, "previous": None, "results": [present]},
    })
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: fake)
    monkeypatch.setattr(
        sapl_sync,
        "_process_payload",
        lambda value: (sapl_sync.payload_hash(value), int(value["id"])),
    )

    # Existing record is already considered current, so the test focuses on
    # the missing-record reconciliation path.
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
