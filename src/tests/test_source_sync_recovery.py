"""Recovery contracts for checkpointed source synchronization."""

from urllib.parse import parse_qs, urlparse

import pytest

from src.apps.ingestion import sapl_sync
from src.apps.legislation.models import Norma
from src.apps.operations.models import SaplSyncState

pytestmark = pytest.mark.django_db


def _payload(sapl_id: int) -> dict:
    return {
        "id": sapl_id,
        "tipo": {"descricao": "Lei"},
        "numero": str(sapl_id),
        "ano": 2026,
        "ementa": f"Norma de QA {sapl_id}",
        "texto_integral": "",
    }


class _RecoveringClient:
    def __init__(self):
        self.closed = False
        self.interrupted = False
        self.resume_urls: list[str] = []

    def fetch_normas_page(self, *, limit, offset, tipo=None, ano=None):
        assert (limit, offset, tipo, ano) == (1, 0, None, None)
        return {
            "count": 2,
            "next": "https://example.invalid/api/norma/normajuridica/?offset=1",
            "results": [_payload(1)],
        }

    def _make_request_url(self, url):
        self.resume_urls.append(url)
        if not self.interrupted:
            self.interrupted = True
            raise OSError("simulated source outage")
        offset = int(parse_qs(urlparse(url).query)["offset"][0])
        assert offset == 1
        return {
            "count": 2,
            "next": None,
            "results": [_payload(2)],
        }

    def validate_pagination_url(self, url):
        assert url.startswith("https://example.invalid/api/")
        return url

    def close(self):
        self.closed = True


def test_full_sync_resumes_after_outage_and_only_reconciles_after_complete_coverage(
    monkeypatch, settings
):
    first, second, absent = [
        Norma.objects.create(
            tipo="Lei",
            numero=str(sapl_id),
            ano=2026,
            ementa=f"Norma de QA {sapl_id}",
            sapl_id=sapl_id,
            sapl_metadata={
                "_jurix_source_hash": sapl_sync.payload_hash(_payload(sapl_id))
            },
        )
        for sapl_id in (1, 2, 99)
    ]
    client = _RecoveringClient()
    monkeypatch.setattr(sapl_sync, "SaplAPIClient", lambda: client)

    with pytest.raises(OSError, match="simulated source outage"):
        sapl_sync.run_full_sync(limit=1)

    scope = sapl_sync.hashlib.sha256(
        (sapl_sync._scope_fingerprint(None, None) + ":full").encode("utf-8")
    ).hexdigest()
    checkpoint = SaplSyncState.objects.get(source="sapl", filter_fingerprint=scope)
    assert checkpoint.last_cursor == 1
    assert checkpoint.last_cursor_url.endswith("offset=1")
    assert checkpoint.last_sync_count == 1
    assert checkpoint.full_sweep_token
    assert checkpoint.full_sweep_expected_count == 2
    assert checkpoint.last_success_at is None
    assert "simulated source outage" in checkpoint.last_error
    absent.refresh_from_db()
    assert absent.needs_review is False

    result = sapl_sync.run_full_sync(limit=1)

    assert result["success"] is True
    assert result["fetched"] == 2
    assert result["missing_marked_for_review"] == 1
    assert client.resume_urls == [
        "https://example.invalid/api/norma/normajuridica/?offset=1",
        "https://example.invalid/api/norma/normajuridica/?offset=1",
    ]
    assert client.closed is True
    checkpoint.refresh_from_db()
    assert checkpoint.last_success_at is not None
    assert checkpoint.last_cursor == 0
    assert checkpoint.last_cursor_url == ""
    assert checkpoint.full_sweep_token == ""
    assert checkpoint.last_error == ""
    absent.refresh_from_db()
    assert absent.needs_review is True
    first.refresh_from_db()
    second.refresh_from_db()
    assert first.needs_review is False
    assert second.needs_review is False
