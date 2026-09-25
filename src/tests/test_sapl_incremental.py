from unittest.mock import patch

from src.apps.ingestion.tasks import _sapl_payload_hash
from src.apps.legislation.models import Norma


def test_sapl_payload_hash_is_deterministic():
    payload = {"id": 10, "ano": 2026, "numero": "123", "nested": {"b": 2, "a": 1}}
    assert _sapl_payload_hash(payload) == _sapl_payload_hash(
        {"nested": {"a": 1, "b": 2}, "numero": "123", "id": 10, "ano": 2026}
    )


def test_incremental_sync_skips_unchanged_payload(db):
    payload = {
        "id": 42,
        "tipo": {"descricao": "Lei"},
        "numero": "123",
        "ano": 2026,
        "ementa": "Ementa",
        "data": "2026-01-01",
        "data_vigencia": "2026-01-02",
        "texto_integral": "",
    }
    digest = _sapl_payload_hash(payload)
    Norma.objects.create(
        sapl_id=42,
        tipo="Lei",
        numero="123",
        ano=2026,
        sapl_metadata={**payload, "_jurix_source_hash": digest},
    )

    from src.apps.ingestion.tasks import incremental_sync_sapl_task

    with patch("src.apps.ingestion.sapl_sync.SaplAPIClient") as client_cls:
        client_cls.return_value.fetch_normas_page.return_value = {
            "count": 1,
            "next": None,
            "results": [payload],
        }
        stats = incremental_sync_sapl_task.run(limit=10)

    assert stats["unchanged"] == 1
    assert stats["changed"] == 0
    client_cls.return_value.close.assert_called_once()
