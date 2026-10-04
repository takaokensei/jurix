from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.core.management import call_command

from src.apps.ingestion.management.commands.seed_normative_qa import seed_fixture
from src.apps.legislation.document_models import NormativeSnapshot, SnapshotDispositivo
from src.apps.legislation.event_review import _decision_fingerprint, event_review_fingerprint
from src.apps.legislation.models import EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.event_temporal_policy import temporal_candidate_fingerprint
from src.processing.normative_projection import persist_projection, project_norma_as_of


@pytest.fixture
def temporal_fixture(tmp_path, monkeypatch):
    root = tmp_path / "qa"
    root.mkdir()
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    monkeypatch.setenv("JURIX_QA_ROOT", str(root))
    return seed_fixture(root / "fixture-map.json")["temporal_scenarios"]


@pytest.mark.django_db(transaction=True)
def test_projection_reconstructs_d_minus_one_and_effective_date(temporal_fixture):
    norma = Norma.objects.get(pk=temporal_fixture["norma_a"]["norma_id"])
    before = project_norma_as_of(norma, date(2021, 2, 28))
    on = project_norma_as_of(norma, date(2021, 3, 1))
    after = project_norma_as_of(norma.pk, date(2021, 3, 2))
    assert before.status == on.status == after.status == "complete"
    assert before.devices[0].text == "Art. 5º O prazo é de dez dias."
    assert on.devices[0].text == "O prazo é de vinte dias."
    assert after.content_sha256 == on.content_sha256
    assert before.content_sha256 != on.content_sha256
    assert on.coverage["applied_event_ids"] == [temporal_fixture["norma_b"]["event_id"]]
    assert before.devices[0].provenance["base_document_id"] == temporal_fixture["norma_a"]["document_id"]
    assert on.devices[0].provenance["event_id"] == temporal_fixture["norma_b"]["event_id"]


@pytest.mark.django_db(transaction=True)
def test_projection_is_deterministic_and_persist_is_append_only(temporal_fixture):
    norma_id = temporal_fixture["norma_a"]["norma_id"]
    projection = project_norma_as_of(norma_id, date(2021, 3, 1))
    repeated = project_norma_as_of(norma_id, date(2021, 3, 1))
    assert projection.input_sha256 == repeated.input_sha256
    assert projection.content_sha256 == repeated.content_sha256
    snapshot = persist_projection(projection)
    again = persist_projection(repeated)
    assert snapshot.pk == again.pk
    row = SnapshotDispositivo.objects.get(snapshot=snapshot)
    assert row.text == "O prazo é de vinte dias."
    assert row.provenance_json["event_id"] == temporal_fixture["norma_b"]["event_id"]
    with pytest.raises(Exception, match="imutáveis"):
        row.save()


@pytest.mark.django_db(transaction=True)
def test_unreviewed_event_marks_projection_partial_without_applying(temporal_fixture):
    norma = Norma.objects.get(pk=temporal_fixture["norma_a"]["norma_id"])
    source = EventoAlteracao.objects.get(pk=temporal_fixture["norma_b"]["event_id"])
    EventoAlteracao.objects.create(
        dispositivo_fonte=source.dispositivo_fonte,
        acao="REVOGA",
        target_text="Art. 5º da Lei 9001/2020",
        norma_alvo=norma,
        dispositivo_alvo=source.dispositivo_alvo,
        referencia_tipo="artigo",
        referencia_numero="5º",
        target_reference_json={"synthetic": True},
        revision_fingerprint="pending-synthetic-event",
    )
    result = project_norma_as_of(norma, date(2021, 3, 2))
    assert result.status == "partial"
    assert result.devices[0].text == "O prazo é de vinte dias."
    assert result.devices[0].legal_status == "in_force"
    assert len(result.coverage["pending_event_ids"]) == 1


@pytest.mark.django_db(transaction=True)
def test_current_text_without_reviewed_source_is_not_renamed_as_history(temporal_fixture):
    norma = Norma.objects.get(pk=temporal_fixture["norma_a"]["norma_id"])
    document = norma.documento_base
    document.review_status = "pending"
    document.save(update_fields=["review_status", "updated_at"])
    result = project_norma_as_of(norma, date(2020, 2, 1))
    assert result.status == "not_reconstructable"
    assert result.devices == ()
    assert result.coverage["reason"] == "base_document_not_reviewed_or_temporally_unknown"


@pytest.mark.django_db(transaction=True)
def test_future_base_document_does_not_leak_into_earlier_projection(temporal_fixture):
    norma = Norma.objects.get(pk=temporal_fixture["norma_b"]["norma_id"])
    result = project_norma_as_of(norma, date(2020, 12, 31))
    assert result.status == "not_reconstructable"
    assert result.coverage["reason"] == "base_document_not_yet_published"


@pytest.mark.django_db(transaction=True)
def test_snapshot_command_is_dry_run_by_default_and_apply_is_idempotent(temporal_fixture):
    norma_id = temporal_fixture["norma_a"]["norma_id"]
    before = NormativeSnapshot.objects.count()
    dry_output = StringIO()
    call_command(
        "build_normative_snapshots",
        as_of="2021-03-01",
        norma_id=[norma_id],
        stdout=dry_output,
    )
    assert '"dry_run": true' in dry_output.getvalue()
    assert NormativeSnapshot.objects.count() == before

    call_command("build_normative_snapshots", as_of="2021-03-01", norma_id=[norma_id], apply=True, stdout=StringIO())
    after_first = NormativeSnapshot.objects.count()
    call_command("build_normative_snapshots", as_of="2021-03-01", norma_id=[norma_id], apply=True, stdout=StringIO())
    assert NormativeSnapshot.objects.count() == after_first


@pytest.mark.django_db(transaction=True)
def test_same_date_conflicting_effects_remain_pending(temporal_fixture):
    original = EventoAlteracao.objects.get(pk=temporal_fixture["norma_b"]["event_id"])
    conflict = EventoAlteracao.objects.create(
        dispositivo_fonte=original.dispositivo_fonte,
        acao="REVOGA",
        target_text=original.target_text,
        norma_alvo=original.norma_alvo,
        dispositivo_alvo=original.dispositivo_alvo,
        referencia_tipo=original.referencia_tipo,
        referencia_numero=original.referencia_numero,
        target_reference_json={"synthetic": True, "conflicting_effect": True},
        evidence_json={"synthetic": True, "conflicting_effect": True},
        revision_fingerprint="synthetic-conflicting-effect",
    )
    relation_review = RevisaoJuridica.objects.create(
        evento=conflict,
        target_fingerprint=_decision_fingerprint(
            event_review_fingerprint(conflict),
            norma_id=original.norma_alvo_id,
            dispositivo_id=original.dispositivo_alvo_id,
        ),
        decision=RevisaoJuridica.Decision.APPROVE,
        reason="[QA SINTÉTICO] Evento conflitante para testar fail closed.",
        actor=original.review_revision.actor,
    )
    conflict.validado = True
    conflict.review_revision = relation_review
    conflict.effective_on = date(2021, 3, 1)
    conflict.effective_date_status = "confirmed"
    quote = original.effective_date_basis["evidence_quote"]
    date_review = RevisaoJuridica.objects.create(
        evento=conflict,
        target_fingerprint=temporal_candidate_fingerprint(conflict, date(2021, 3, 1), quote),
        decision=RevisaoJuridica.Decision.APPROVE,
        reason="[QA SINTÉTICO] Data de conflito artificial.",
        actor=original.review_revision.actor,
    )
    conflict.effective_date_basis = {
        "evidence_quote": quote,
        "effective_on": "2021-03-01",
        "review_id": str(date_review.public_id),
        "review_type": "effective_date",
    }
    conflict.save(
        update_fields=["validado", "review_revision", "effective_on", "effective_date_status", "effective_date_basis", "updated_at"]
    )

    result = project_norma_as_of(original.norma_alvo, date(2021, 3, 1))
    assert result.status == "partial"
    assert result.devices[0].text == "Art. 5º O prazo é de dez dias."
    assert set(result.coverage["pending_event_ids"]) == {original.pk, conflict.pk}
    assert result.coverage["applied_event_ids"] == []
