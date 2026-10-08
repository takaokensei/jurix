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
        acao="REFERENCIA",
        target_text="Art. 1º",
    )

    timeline = build_norma_timeline(target)
    event_items = [item for item in timeline if item["kind"] == "event"]
    assert [item["source_norma_id"] for item in event_items] == [source.id]
    assert event_items[0]["target_label"] == "Art. 1º"
    assert event_items[0]["extraction_signal"] is None
    assert event_items[0]["pending"] is True
    assert "menciona" in event_items[0]["description"]
    assert "Art. 1º" in event_items[0]["description"]


@pytest.mark.django_db
def test_timeline_collapses_duplicate_rows_only_for_same_fingerprinted_relation(monkeypatch):
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(tipo="Lei", numero="30", ano=2025, status="consolidated")
    source = Norma.objects.create(tipo="Lei", numero="31", ano=2026, status="consolidated")
    source_device = Dispositivo.objects.create(
        norma=source, tipo="artigo", numero="1º", texto="Menciona dois dispositivos.", ordem=0
    )
    first_target = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="21", texto="Texto 21", ordem=0
    )
    second_target = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="44", texto="Texto 44", ordem=1
    )
    shared = {
        "dispositivo_fonte": source_device,
        "norma_alvo": target,
        "acao": "REFERENCIA",
        "revision_fingerprint": "a" * 64,
        "evidence_json": {"quote": "Menciona os Arts. 21 e 44."},
    }
    EventoAlteracao.objects.create(
        **shared,
        dispositivo_alvo=first_target,
        target_text="Art. 21 da Lei 30/2025",
    )
    EventoAlteracao.objects.create(
        **shared,
        dispositivo_alvo=first_target,
        target_text="[QA] Art. 21 da Lei 30/2025",
    )
    EventoAlteracao.objects.create(
        **shared,
        dispositivo_alvo=second_target,
        target_text="Art. 44 da Lei 30/2025",
    )
    monkeypatch.setattr(
        "src.apps.legislation.event_review.event_review_status",
        lambda event: "confirmed" if event.target_text.startswith("[QA]") else "pending",
    )

    events = [item for item in build_norma_timeline(target) if item["kind"] == "event"]

    assert len(events) == 2
    assert {item["target_dispositivo_id"] for item in events} == {
        first_target.pk,
        second_target.pk,
    }
    first = next(item for item in events if item["target_dispositivo_id"] == first_target.pk)
    second = next(item for item in events if item["target_dispositivo_id"] == second_target.pk)
    assert first["relation_status"] == "confirmed"
    assert second["relation_status"] == "pending"
    assert second["pending"] is True


@pytest.mark.django_db
def test_timeline_explains_distinct_actions_for_the_same_target_device():
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(tipo="Lei", numero="55", ano=2004, status="consolidated")
    source = Norma.objects.create(tipo="Lei Complementar", numero="198", ano=2021, status="consolidated")
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="21", texto="Texto-alvo", ordem=0
    )
    source_device = Dispositivo.objects.create(
        norma=source, tipo="artigo", numero="1º", texto="Referência ao Art. 21", ordem=0
    )
    for action, fingerprint in (("REFERENCIA", "a" * 64), ("REVOGA", "b" * 64)):
        EventoAlteracao.objects.create(
            dispositivo_fonte=source_device,
            norma_alvo=target,
            dispositivo_alvo=target_device,
            acao=action,
            target_text="Art. 21 da Lei Complementar nº 55/2004",
            revision_fingerprint=fingerprint,
        )

    events = [item for item in build_norma_timeline(target) if item["kind"] == "event"]

    assert len(events) == 2
    assert {item["action"] for item in events} == {"Referência", "Revogação"}
    assert {item["target_relation_count"] for item in events} == {2}
    assert {item["target_relation_ordinal"] for item in events} == {1, 2}


@pytest.mark.django_db
def test_norma_detail_explains_multiple_relation_records_for_one_device(client):
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(tipo="Lei", numero="55", ano=2004, status="consolidated")
    source = Norma.objects.create(tipo="Lei Complementar", numero="198", ano=2021, status="consolidated")
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="21", texto="Texto-alvo", ordem=0
    )
    source_device = Dispositivo.objects.create(
        norma=source, tipo="artigo", numero="1º", texto="Referência ao Art. 21", ordem=0
    )
    for action, fingerprint in (("REFERENCIA", "c" * 64), ("REVOGA", "d" * 64)):
        EventoAlteracao.objects.create(
            dispositivo_fonte=source_device,
            norma_alvo=target,
            dispositivo_alvo=target_device,
            acao=action,
            target_text="Art. 21 da Lei Complementar nº 55/2004",
            revision_fingerprint=fingerprint,
        )

    response = client.get(f"/normas/{target.pk}/")
    body = response.content.decode()

    assert response.status_code == 200
    assert "Há 2 registros distintos para este dispositivo." in body
    assert body.count("Há 2 registros distintos para este dispositivo.") == 1
    assert "Candidato extraído · não confirmado" in body


@pytest.mark.django_db
def test_norma_detail_does_not_present_extraction_signal_as_legal_confidence(client):
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(tipo="Lei", numero="12", ano=2025, status="consolidated")
    source = Norma.objects.create(tipo="Lei", numero="13", ano=2026, status="consolidated")
    source_device = Dispositivo.objects.create(
        norma=source, tipo="artigo", numero="1º", texto="Altera o art. 2º", ordem=0
    )
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="2º", texto="Texto original", ordem=0
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        norma_alvo=target,
        dispositivo_alvo=target_device,
        acao="ALTERA",
        target_text="Art. 2º",
        extraction_confidence=0,
    )

    response = client.get(f"/normas/{target.pk}/")

    assert response.status_code == 200
    assert "Registros de relações extraídos" in response.content.decode()
    assert "Extração pendente de revisão" in response.content.decode()
    assert "Não calibrado" in response.content.decode()
    assert "0.00" not in response.content.decode()


@pytest.mark.django_db
def test_timeline_labels_unreviewed_effective_date_as_candidate():
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(tipo="Lei", numero="20", ano=2024, status="consolidated")
    source = Norma.objects.create(
        tipo="Lei", numero="21", ano=2025, status="consolidated",
        data_publicacao=date(2025, 1, 1),
    )
    source_text = "O art. 2º da Lei 20/2024 passa a vigorar com nova redação."
    source_device = Dispositivo.objects.create(
        norma=source, tipo="artigo", numero="1º", texto=source_text, ordem=0
    )
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="2º", texto="Texto original", ordem=0
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        norma_alvo=target,
        dispositivo_alvo=target_device,
        acao="ALTERA",
        target_text="Art. 2º da Lei 20/2024",
        effective_on=date(2025, 2, 1),
        effective_date_status="candidate",
        effective_date_basis={"evidence_quote": source_text},
    )

    event = next(item for item in build_norma_timeline(target) if item["kind"] == "event")

    assert event["date"] is None
    assert event["candidate_effective_date"] == "2025-02-01"
    assert event["candidate_effective_date_display"] == "01/02/2025"
    assert event["validated"] is False


@pytest.mark.django_db
def test_amending_norma_timeline_distinguishes_publication_from_reviewed_effect(monkeypatch):
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
    from src.processing.event_temporal_policy import EventTemporalDecision

    target = Norma.objects.create(
        tipo="Lei", numero="9001", ano=2020, status="consolidated"
    )
    source = Norma.objects.create(
        tipo="Lei",
        numero="9002",
        ano=2021,
        status="consolidated",
        data_publicacao=date(2021, 1, 10),
        data_vigencia=date(2021, 1, 10),
    )
    source_device = Dispositivo.objects.create(
        norma=source,
        tipo="artigo",
        numero="1º",
        texto="Dê-se nova redação ao Art. 5º: ‘O prazo é de vinte dias.’",
        ordem=0,
    )
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="5º", texto="O prazo é de dez dias.", ordem=0
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        norma_alvo=target,
        dispositivo_alvo=target_device,
        acao="ALTERA",
        target_text="Art. 5º",
        validado=True,
    )
    monkeypatch.setattr(
        "src.processing.temporal_scope.event_temporal_decision",
        lambda event: EventTemporalDecision(
            effective_on=date(2021, 3, 1),
            status="confirmed",
            basis={"kind": "qa-reviewed"},
            reason="QA fixture",
            publication_on=date(2021, 1, 10),
            operative=True,
        ),
    )
    monkeypatch.setattr(
        "src.apps.legislation.event_review.event_review_status",
        lambda event: "confirmed",
    )

    timeline = build_norma_timeline(source)

    assert [(item["kind"], item["date"]) for item in timeline] == [
        ("publication", "2021-01-10"),
        ("effective", "2021-01-10"),
        ("event", "2021-03-01"),
    ]
    effect = timeline[-1]
    assert effect["timeline_role"] == "source"
    assert effect["title"] == "Efeito em outra norma — Alteração"
    assert "Art. 5º da Lei nº 9001/2020" in effect["description"]
    assert effect["validated"] is True


@pytest.mark.django_db
def test_historical_compare_renders_history_sync_and_date_defaults(client):
    from src.apps.legislation.models import Norma

    norma = Norma.objects.create(tipo="Lei", numero="71", ano=2021, status="pending")

    response = client.get(
        f"/normas/{norma.pk}/compare/?history=1&from_as_of=2021-02-28&to_as_of=2021-03-01"
    )

    assert response.status_code == 200
    html = response.content.decode()
    assert 'data-default-from="2021-02-28" data-default-to="2021-03-01"' in html
    assert "jurix-temporal-compare.js?v=20261004-history-sync1" in html


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
