from __future__ import annotations

from datetime import date
from io import StringIO

import pytest
from django.contrib.auth import get_user_model
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import Client, override_settings

from src.apps.ingestion.management.commands.seed_normative_qa import (
    _ensure_reviewed_document,
    seed_fixture,
)
from src.apps.legislation.document_models import NormativeSnapshot, SnapshotDispositivo
from src.apps.legislation.event_review import _decision_fingerprint, event_review_fingerprint
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.corpus_coverage import record_corpus_coverage_scope
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
def test_corpus_coverage_revision_changes_projection_fingerprint_and_snapshot(
    temporal_fixture, monkeypatch
):
    norma_id = temporal_fixture["norma_a"]["norma_id"]
    first_coverage = {
        "coverage_status": "unknown",
        "corpus_revision": {"revision": 1, "digest": "a" * 64},
        "checked_until": None,
        "sources_checked": [],
        "missing_intervals": None,
        "pending_review": None,
    }
    monkeypatch.setattr(
        "src.processing.normative_projection.current_corpus_coverage",
        lambda: first_coverage,
    )
    first = project_norma_as_of(norma_id, date(2021, 3, 1))
    first_snapshot = persist_projection(first)

    second_coverage = {
        **first_coverage,
        "coverage_status": "partial",
        "corpus_revision": {"revision": 2, "digest": "b" * 64},
        "sources_checked": [
            {
                "source": "official_registry",
                "series": "municipal_laws",
                "checked_until": "2021-03-01",
            }
        ],
    }
    monkeypatch.setattr(
        "src.processing.normative_projection.current_corpus_coverage",
        lambda: second_coverage,
    )
    second = project_norma_as_of(norma_id, date(2021, 3, 1))
    second_snapshot = persist_projection(second)

    assert first.input_sha256 != second.input_sha256
    assert first.content_sha256 == second.content_sha256
    assert first.coverage["corpus_coverage"] == first_coverage
    assert second.coverage["corpus_coverage"] == second_coverage
    assert first_snapshot.pk != second_snapshot.pk


@pytest.mark.django_db(transaction=True)
def test_persisted_coverage_scope_invalidates_projection_snapshot(temporal_fixture):
    norma_id = temporal_fixture["norma_a"]["norma_id"]
    as_of = date(2021, 3, 1)
    first = project_norma_as_of(norma_id, as_of)
    first_snapshot = persist_projection(first)

    record_corpus_coverage_scope(
        source="sapl",
        jurisdiction="BR-RN-NATAL",
        series="municipal_normas",
        coverage_status="partial",
        period_start=date(1980, 1, 1),
        checked_until=date(2021, 3, 1),
        source_checksum="c" * 64,
        missing_intervals=[{"start": "2001-01-01", "end": "2001-12-31"}],
        pending_review_count=2,
        last_success_at=None,
    )

    second = project_norma_as_of(norma_id, as_of)
    second_snapshot = persist_projection(second)

    assert first.input_sha256 != second.input_sha256
    assert first.content_sha256 == second.content_sha256
    assert first.coverage["corpus_coverage"]["coverage_status"] == "unknown"
    assert second.coverage["corpus_coverage"]["coverage_status"] == "partial"
    assert second.coverage["corpus_coverage"]["pending_review"] == 2
    assert first_snapshot.pk != second_snapshot.pk


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
    assert result.devices[0].legal_status == "unknown"
    assert result.devices[0].provenance["known_legal_status_before_pending_events"] == "in_force"
    assert result.devices[0].provenance["pending_event_ids"] == result.coverage["pending_event_ids"]
    assert len(result.coverage["pending_event_ids"]) == 1


@pytest.mark.django_db(transaction=True)
@override_settings(NORMATIVE_HISTORY_ENABLED=True)
def test_pending_event_with_exact_target_only_marks_that_device_unknown():
    reviewer = get_user_model().objects.create_user(
        username="scoped-pending-fixture-reviewer", is_active=True, is_staff=True
    )
    norma, _document, extraction, article_one = _ensure_reviewed_document(
        slug="scoped-pending",
        label="Lei",
        number="9902",
        year=2020,
        text="Art. 1º Regra do primeiro artigo.\nArt. 2º Regra independente do segundo artigo.",
        published=date(2020, 1, 1),
        reviewer=reviewer,
    )
    article_two_source = extraction.dispositivos_documentais.get(numero__startswith="2")
    article_two = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero=article_two_source.numero,
        texto=article_two_source.texto,
        texto_bruto=article_two_source.texto,
        ordem=2,
        structural_key=article_two_source.structural_key,
    )
    pending_event = EventoAlteracao.objects.create(
        dispositivo_fonte=article_two,
        acao="ALTERA",
        target_text="Art. 1º da Lei 9902/2020",
        norma_alvo=norma,
        dispositivo_alvo=article_one,
        referencia_tipo="artigo",
        referencia_numero="1º",
        target_reference_json={"synthetic": True, "exact_target": True},
        revision_fingerprint="synthetic-scoped-pending-event",
    )

    result = project_norma_as_of(norma, date(2020, 2, 1))

    by_number = {item.source.numero: item for item in result.devices}
    assert result.status == "partial"
    assert by_number["1º"].legal_status == "unknown"
    assert by_number["1º"].provenance["pending_event_ids"] == [pending_event.pk]
    assert by_number["2º"].legal_status == "in_force"
    assert "pending_event_ids" not in by_number["2º"].provenance
    assert result.coverage["pending_device_keys"] == [by_number["1º"].source.structural_key]

    response = Client().get(
        f"/api/v1/normas/{norma.pk}/version/?as_of=2020-02-01"
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["coverage"]["pending_device_keys"] == [
        by_number["1º"].source.structural_key
    ]
    api_devices = {item["numero"]: item for item in payload["devices"]}
    assert api_devices["1º"]["legal_status"] == "unknown"
    assert api_devices["2º"]["legal_status"] == "in_force"


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
def test_projection_fails_closed_when_document_segmentation_has_no_human_review():
    reviewer = get_user_model().objects.create_user(
        username="segmentation-fixture-reviewer", is_active=True, is_staff=True
    )
    norma, _document, _extraction, _device = _ensure_reviewed_document(
        slug="unreviewed-segmentation",
        label="Lei",
        number="9901",
        year=2020,
        text="Art. 1º O trecho sintético usado apenas para teste.\nArt. 2º Fim.",
        published=date(2020, 1, 1),
        reviewer=reviewer,
        review_segmentation=False,
    )

    result = project_norma_as_of(norma, date(2020, 2, 1))

    assert result.status == "not_reconstructable"
    assert result.devices == ()
    assert result.coverage["reason"] == "document_segmentation_not_human_reviewed"


@pytest.mark.django_db(transaction=True)
def test_future_base_document_does_not_leak_into_earlier_projection(temporal_fixture):
    norma = Norma.objects.get(pk=temporal_fixture["norma_b"]["norma_id"])
    result = project_norma_as_of(norma, date(2020, 12, 31))
    assert result.status == "not_reconstructable"
    assert result.coverage["reason"] == "base_document_not_yet_published"


@pytest.mark.django_db(transaction=True)
def test_snapshot_command_dry_run_is_read_only_and_apply_persists_in_qa_database(
    temporal_fixture, monkeypatch
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
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

    apply_output = StringIO()
    call_command(
        "build_normative_snapshots",
        as_of="2021-03-01",
        norma_id=[norma_id],
        apply=True,
        stdout=apply_output,
    )
    assert '"persisted": true' in apply_output.getvalue()
    assert NormativeSnapshot.objects.count() == before + 1


@pytest.mark.django_db(transaction=True)
def test_snapshot_command_dry_run_reports_missing_reviewed_source_without_persisting(
    monkeypatch,
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    norma = Norma.objects.create(
        tipo="Lei Complementar",
        numero="9998",
        ano=2026,
        ementa="Identidade de teste sem documento-base.",
        status=Norma.Status.PENDING,
    )
    before = NormativeSnapshot.objects.count()

    dry_output = StringIO()
    call_command(
        "build_normative_snapshots",
        as_of="2026-10-15",
        norma_id=[norma.pk],
        stdout=dry_output,
    )

    assert '"status": "not_reconstructable"' in dry_output.getvalue()
    assert '"persisted": false' in dry_output.getvalue()
    assert NormativeSnapshot.objects.count() == before

    # Applying in the dedicated QA test database is permitted, but this test
    # deliberately covers only the read-only preview of an unreviewed identity.


@pytest.mark.django_db(transaction=True)
def test_snapshot_command_rejects_apply_to_non_qa_database_even_with_qa_flag(
    temporal_fixture, monkeypatch
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    with override_settings(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": ":memory:",
            }
        }
    ):
        with pytest.raises(CommandError, match="Persistência de snapshots exige PostgreSQL QA"):
            call_command(
                "build_normative_snapshots",
                as_of="2021-03-01",
                norma_id=[temporal_fixture["norma_a"]["norma_id"]],
                apply=True,
                stdout=StringIO(),
            )


@pytest.mark.django_db(transaction=True)
def test_snapshot_command_dry_run_rejects_persistent_sqlite_even_with_qa_flag(
    temporal_fixture, monkeypatch
):
    monkeypatch.setenv("JURIX_QA_ONLY", "1")
    with override_settings(
        DATABASES={
            "default": {
                "ENGINE": "django.db.backends.sqlite3",
                "NAME": "jurix-persistent-local.sqlite3",
            }
        }
    ):
        with pytest.raises(
            CommandError,
            match="Prévia de snapshots exige PostgreSQL QA ou SQLite efêmero de teste",
        ):
            call_command(
                "build_normative_snapshots",
                as_of="2021-03-01",
                norma_id=[temporal_fixture["norma_a"]["norma_id"]],
                stdout=StringIO(),
            )


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
