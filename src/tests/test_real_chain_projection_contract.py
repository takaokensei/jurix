"""Cross-layer temporal safety contracts; fixture data is synthetic QA only."""

from datetime import date

import pytest
from django.test import Client, override_settings

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.document_models import NormativeSnapshot
from src.apps.legislation.models import EventoAlteracao, Norma
from src.processing.normative_projection import project_norma_as_of
from src.processing.temporal_retrieval import retrieve_historical_norma
from src.processing.temporal_scope import TemporalScope


@pytest.fixture
def temporal_case(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    return seed_fixture(root / "fixture-map.json")["temporal_scenarios"]


@pytest.mark.django_db(transaction=True)
def test_pending_temporal_effect_is_not_exposed_as_in_force_evidence(temporal_case):
    norma = Norma.objects.get(pk=temporal_case["norma_a"]["norma_id"])
    source = EventoAlteracao.objects.get(pk=temporal_case["norma_b"]["event_id"])
    EventoAlteracao.objects.create(
        dispositivo_fonte=source.dispositivo_fonte,
        acao="REVOGA",
        target_text="Art. 5º da Lei 9001/2020",
        norma_alvo=norma,
        dispositivo_alvo=source.dispositivo_alvo,
        referencia_tipo="artigo",
        referencia_numero="5º",
        target_reference_json={"synthetic": True},
        revision_fingerprint="pending-synthetic-revocation",
    )

    rows = retrieve_historical_norma(
        norma,
        "O que prevê o art. 5º da Lei nº 9001/2020?",
        date(2021, 3, 2),
        max_sources=12,
        scope=TemporalScope(as_of=date(2021, 3, 2)),
    )

    assert rows
    assert rows.coverage["status"] == NormativeSnapshot.Status.PARTIAL
    assert rows.coverage["complete"] is False
    assert all(row["temporal_version"]["legal_status"] == "unknown" for row in rows)
    assert all(row["evidence_scope"] == "partial" for row in rows)
    assert all(
        "conflitos" in row["temporal_version"]["status_note"].lower()
        or "indeterminada" in row["temporal_version"]["status_note"].lower()
        for row in rows
    )


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_version_api_does_not_advertise_snapshot_with_mismatched_content_or_status(
    temporal_case,
):
    norma = Norma.objects.get(pk=temporal_case["norma_a"]["norma_id"])
    as_of = date(2021, 2, 27)
    projection = project_norma_as_of(norma, as_of)
    snapshot = NormativeSnapshot.objects.create(
        norma=norma,
        as_of=as_of,
        status=NormativeSnapshot.Status.PARTIAL,
        input_sha256=projection.input_sha256,
        content_sha256="b" * 64,
        coverage_json={"complete": False},
    )

    response = Client().get(f"/api/v1/normas/{norma.pk}/version/?as_of=2021-02-27")

    assert response.status_code == 200
    assert response.json()["snapshot_id"] is None
    assert response.json()["snapshot_id"] != snapshot.pk
