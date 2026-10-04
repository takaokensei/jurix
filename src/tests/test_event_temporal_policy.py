from datetime import date
from types import SimpleNamespace

import pytest
from django.contrib.auth.models import Permission, User
from django.core.exceptions import ValidationError
from django.test import Client
from django.urls import reverse

from src.apps.legislation.event_review import (
    event_review_fingerprint,
    review_event,
    review_event_effective_date,
)
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.event_temporal_policy import event_temporal_decision
from src.processing.temporal_scope import (
    revoked_dispositivo_ids,
    revoked_norma_ids,
    temporal_status,
)


def _event(*, action="REVOGA", text="Art. 1º Fica revogado o dispositivo.", publication=None):
    source_norma = SimpleNamespace(data_publicacao=publication)
    source = SimpleNamespace(texto=text, norma=source_norma, revision_fingerprint="source-v1")
    return SimpleNamespace(
        pk=None,
        dispositivo_fonte_id=1,
        acao=action,
        target_text="Lei nº 100/2026",
        referencia_tipo="lei",
        referencia_numero="100/2026",
        revision_fingerprint="event-v1",
        target_reference_json={},
        evidence_json={},
        dispositivo_fonte=source,
        effective_on=None,
        effective_date_status="unknown",
        effective_date_basis={},
        is_active=True,
        validado=False,
    )


def test_publication_clause_creates_candidate_not_confirmed_effect():
    event = _event(
        text="Art. 8º Esta Lei entra em vigor na data de sua publicação.",
        publication=date(2026, 3, 1),
    )

    decision = event_temporal_decision(event)
    assert decision.effective_on == date(2026, 3, 1)
    assert decision.status == "candidate"
    assert decision.operative is False
    assert decision.basis["kind"] == "publication_clause"


def test_reference_action_uses_publication_only_for_availability():
    event = _event(action="REFERENCIA", publication=date(2026, 1, 1))
    decision = event_temporal_decision(event)
    assert decision.status == "not_applicable"
    assert decision.effective_on is None
    assert decision.publication_on == date(2026, 1, 1)
    assert decision.operative is False


def test_unknown_conditional_and_retroactive_effects_fail_closed():
    assert event_temporal_decision(_event()).status == "unknown"
    assert (
        event_temporal_decision(_event(text="A regra produz efeitos retroativos.")).status
        == "unsupported"
    )
    assert (
        event_temporal_decision(_event(text="Enquanto durar a emergência, fica revogada.")).status
        == "unsupported"
    )


@pytest.mark.django_db
def test_manually_confirmed_date_without_review_record_is_not_operative():
    quote = "Esta Lei entra em vigor em 1º de março de 2026."
    event = _event(text=quote, publication=date(2026, 1, 1))
    event.effective_on = date(2026, 3, 1)
    event.effective_date_status = "confirmed"
    event.effective_date_basis = {
        "evidence_quote": quote,
        "review_id": "not-a-review",
    }
    decision = event_temporal_decision(event)
    assert decision.status == "candidate"
    assert decision.operative is False


@pytest.mark.django_db
def test_effect_date_review_is_separate_from_relation_review_and_has_d_minus_d_plus():
    target = Norma.objects.create(
        tipo="Lei",
        numero="77",
        ano=2020,
        data_publicacao=date(2020, 1, 1),
        data_vigencia=date(2020, 1, 1),
    )
    source_norma = Norma.objects.create(
        tipo="Lei", numero="99", ano=2026, data_publicacao=date(2026, 1, 10)
    )
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="1º", texto="Texto alvo.", ordem=1
    )
    source_device = Dispositivo.objects.create(
        norma=source_norma,
        tipo="artigo",
        numero="8º",
        texto="Art. 8º Esta Lei entra em vigor em 1º de março de 2026.",
        ordem=8,
        revision_fingerprint="source-revision-1",
    )
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        norma_alvo=target,
        dispositivo_alvo=target_device,
        acao="REVOGA",
        target_text="Lei nº 77/2020, art. 1º",
        revision_fingerprint="event-revision-1",
        referencia_tipo="lei",
        referencia_numero="77/2020",
    )
    reviewer = User.objects.create_user(username="temporal-reviewer", is_staff=True)
    permission = Permission.objects.get(
        content_type__app_label="legislation", codename="change_eventoalteracao"
    )
    reviewer.user_permissions.add(permission)

    relation_review = review_event(
        event_id=event.pk,
        actor=reviewer,
        decision=RevisaoJuridica.Decision.APPROVE,
        reason="Confirmei o alvo e o dispositivo.",
        expected_fingerprint=event_review_fingerprint(event),
        target_norma_id=target.pk,
        target_dispositivo_id=target_device.pk,
    )
    event.refresh_from_db()
    assert event.review_revision_id == relation_review.pk
    assert event.effective_date_status == "unknown"
    assert revoked_dispositivo_ids([target.pk], date(2026, 2, 28)) == set()

    quote = "Art. 8º Esta Lei entra em vigor em 1º de março de 2026."
    client = Client(enforce_csrf_checks=True)
    client.force_login(reviewer)
    temporal_review_url = reverse(
        "admin:legislation_eventoalteracao_temporal_review", args=[event.pk]
    )
    page = client.get(temporal_review_url)
    assert page.status_code == 200
    assert quote.encode() in page.content
    payload = {
        "effective_on": "2026-03-01",
        "evidence_quote": quote,
        "reason": "A data expressa foi conferida no trecho literal.",
        "expected_fingerprint": event_review_fingerprint(event),
    }
    assert client.post(temporal_review_url, payload).status_code == 403
    payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    assert client.post(temporal_review_url, payload).status_code == 302
    event.refresh_from_db()
    decision = event_temporal_decision(event)
    assert decision.status == "confirmed" and decision.operative is True
    assert event.review_revision_id == relation_review.pk
    assert event.effective_date_status == "confirmed"
    assert revoked_dispositivo_ids([target.pk], date(2026, 2, 28)) == set()
    assert revoked_dispositivo_ids([target.pk], date(2026, 3, 1)) == {target_device.pk}
    assert revoked_dispositivo_ids([target.pk], date(2026, 3, 2)) == {target_device.pk}
    assert revoked_norma_ids([target.pk], date(2026, 3, 1)) == set()
    assert temporal_status(target, as_of=date(2026, 3, 1)) == "parcialmente_revogada"

    total_event = EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        norma_alvo=target,
        acao="REVOGA",
        target_text="Revoga integralmente a Lei nº 77/2020",
        revision_fingerprint="event-revision-total",
        referencia_tipo="lei",
        referencia_numero="77/2020",
    )
    review_event(
        event_id=total_event.pk,
        actor=reviewer,
        decision=RevisaoJuridica.Decision.APPROVE,
        reason="A relação de revogação total foi confirmada.",
        expected_fingerprint=event_review_fingerprint(total_event),
        target_norma_id=target.pk,
    )
    total_event.refresh_from_db()
    review_event_effective_date(
        event_id=total_event.pk,
        actor=reviewer,
        effective_on=date(2026, 3, 1),
        evidence_quote=quote,
        reason="A data de efeito foi confirmada separadamente.",
        expected_fingerprint=event_review_fingerprint(total_event),
    )
    assert revoked_norma_ids([target.pk], date(2026, 2, 28)) == set()
    assert revoked_norma_ids([target.pk], date(2026, 3, 1)) == {target.pk}
    assert temporal_status(target, as_of=date(2026, 3, 1)) == "revogada"


@pytest.mark.django_db
def test_effect_date_review_rejects_quote_not_in_source_and_retroactivity():
    target = Norma.objects.create(tipo="Lei", numero="78", ano=2020)
    source_norma = Norma.objects.create(
        tipo="Lei", numero="100", ano=2026, data_publicacao=date(2026, 3, 1)
    )
    source = Dispositivo.objects.create(
        norma=source_norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Art. 1º Produz efeitos nesta data.",
        revision_fingerprint="source-revision-1",
    )
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=source,
        norma_alvo=target,
        acao="ALTERA",
        target_text="Lei nº 78/2020",
        validado=True,
        revision_fingerprint="event-revision-1",
        referencia_tipo="lei",
        referencia_numero="78/2020",
    )
    reviewer = User.objects.create_user(username="temporal-reviewer-2", is_staff=True)
    reviewer.user_permissions.add(
        Permission.objects.get(
            content_type__app_label="legislation", codename="change_eventoalteracao"
        )
    )
    review_event(
        event_id=event.pk,
        actor=reviewer,
        decision=RevisaoJuridica.Decision.APPROVE,
        reason="Relação confirmada.",
        expected_fingerprint=event_review_fingerprint(event),
        target_norma_id=target.pk,
    )
    event.refresh_from_db()
    with pytest.raises(ValidationError, match="literal"):
        review_event_effective_date(
            event_id=event.pk,
            actor=reviewer,
            effective_on=date(2026, 3, 1),
            evidence_quote="Uma data que não existe no texto fonte.",
            reason="Tentativa com trecho ausente.",
            expected_fingerprint=event_review_fingerprint(event),
        )
    with pytest.raises(ValidationError, match="retroativos"):
        review_event_effective_date(
            event_id=event.pk,
            actor=reviewer,
            effective_on=date(2026, 2, 28),
            evidence_quote="Art. 1º Produz efeitos nesta data.",
            reason="Tentativa retroativa.",
            expected_fingerprint=event_review_fingerprint(event),
        )
