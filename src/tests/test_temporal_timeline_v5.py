from datetime import date
from types import SimpleNamespace

import pytest

from src.processing.temporal_scope import build_norma_timeline


def test_build_norma_timeline_accepts_as_of(monkeypatch):
    # The public contract is tested at the pure-function boundary; integration
    # tests in the temporal suite cover actual EventoAlteracao rows.
    norma = SimpleNamespace(
        data_publicacao=date(2020, 1, 1),
        data_vigencia=date(2020, 2, 1),
    )
    # With no event manager supplied, publication/effectivity still form a valid
    # historical timeline. The function must preserve both dates <= as_of.
    monkeypatch.setattr(
        "src.apps.legislation.models.EventoAlteracao.objects",
        SimpleNamespace(
            filter=lambda *args, **kwargs: SimpleNamespace(
                select_related=lambda *a, **k: SimpleNamespace(
                    distinct=lambda: SimpleNamespace(order_by=lambda *x, **y: [])
                )
            )
        ),
    )
    timeline = build_norma_timeline(norma, as_of=date(2024, 1, 1))
    assert [item["kind"] for item in timeline] == ["publication", "effective"]
    assert [item["date_display"] for item in timeline] == ["01/01/2020", "01/02/2020"]


@pytest.mark.django_db
def test_timeline_deduplicates_event_matching_norma_and_device_target():
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(tipo="Lei", numero="10", ano=2025, status="consolidated")
    source = Norma.objects.create(tipo="Lei", numero="11", ano=2026, status="consolidated")
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="1º", texto="Texto", ordem=0
    )
    source_device = Dispositivo.objects.create(
        norma=source, tipo="artigo", numero="1º", texto="Altera", ordem=0
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        norma_alvo=target,
        dispositivo_alvo=target_device,
        acao="alteracao",
        target_text="Art. 1º",
    )

    timeline = build_norma_timeline(target)
    assert [item["source_norma_id"] for item in timeline if item["kind"] == "event"] == [source.id]


@pytest.mark.django_db
@pytest.mark.parametrize("suffix", ["timeline", "conflicts"])
def test_temporal_api_returns_json_404_for_unknown_norma(client, suffix):
    response = client.get(f"/api/v1/normas/999999/{suffix}/")

    assert response.status_code == 404
    assert response.json() == {
        "success": False,
        "error": "Norma with ID 999999 not found",
    }


@pytest.mark.django_db
@pytest.mark.parametrize("suffix", ["timeline", "conflicts"])
def test_temporal_api_rejects_mutating_methods(client, suffix):
    response = client.post(f"/api/v1/normas/999999/{suffix}/", data={})

    assert response.status_code == 405
