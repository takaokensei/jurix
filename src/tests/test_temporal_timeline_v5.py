from datetime import date
from types import SimpleNamespace

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
                select_related=lambda *a, **k: SimpleNamespace(order_by=lambda *x, **y: [])
            )
        ),
    )
    timeline = build_norma_timeline(norma, as_of=date(2024, 1, 1))
    assert [item["kind"] for item in timeline] == ["publication", "effective"]
