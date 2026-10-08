import pytest
from django.contrib.auth.models import AnonymousUser, Permission, User
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import Client
from django.urls import reverse

from src.apps.legislation.event_review import (
    EventReviewForm,
    candidate_normas_for_review,
    event_review_fingerprint,
    event_review_status,
    review_event,
)
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.document_metadata import build_normative_identity


@pytest.fixture
def review_case(db):
    source_norma = Norma.objects.create(tipo="Lei", numero="900", ano=2026)
    source = Dispositivo.objects.create(
        norma=source_norma,
        tipo="artigo",
        numero="1º",
        ordem=1,
        texto="Altera a Lei nº 8.206/2020.",
        revision_fingerprint="source-rev-1",
    )
    target = Norma.objects.create(tipo="Lei", numero="8206", ano=2020)
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=source,
        acao="ALTERA",
        target_text="Lei nº 8.206/2020",
        referencia_tipo="lei",
        referencia_numero="8206",
        revision_fingerprint="event-rev-1",
        evidence_json={"status": "mapped", "quote": "Altera a Lei nº 8.206/2020."},
        target_reference_json={
            "type_candidate": "lei",
            "number_candidate": "8206",
            "year_candidate": 2020,
        },
    )
    return event, target


def _reviewer(*, grant_permission=True, username="reviewer-fixture"):
    user = User.objects.create_user(
        username=username,
        password="qa-only-password",
        is_staff=True,
    )
    if grant_permission:
        permission = Permission.objects.get(
            content_type__app_label="legislation",
            codename="change_eventoalteracao",
        )
        user.user_permissions.add(permission)
    return user


def _review(event, actor, target, **overrides):
    args = {
        "event_id": event.pk,
        "actor": actor,
        "decision": RevisaoJuridica.Decision.APPROVE,
        "reason": "Conferi a referência e o trecho literal da fonte.",
        "expected_fingerprint": event_review_fingerprint(event),
        "target_norma_id": target.pk,
    }
    args.update(overrides)
    return review_event(**args)


def test_anonymous_and_staff_without_model_permission_are_denied(review_case):
    event, target = review_case
    with pytest.raises(PermissionDenied):
        _review(event, AnonymousUser(), target)
    with pytest.raises(PermissionDenied):
        _review(event, _reviewer(grant_permission=False), target)


def test_empty_reason_stale_fingerprint_and_wrong_target_are_rejected(review_case):
    event, target = review_case
    actor = _reviewer()
    with pytest.raises(ValidationError, match="motivo"):
        _review(event, actor, target, reason=" ")
    with pytest.raises(ValidationError, match="mudou"):
        _review(event, actor, target, expected_fingerprint="0" * 64)
    wrong_target = Norma.objects.create(tipo="Lei Complementar", numero="8206", ano=2020)
    with pytest.raises(ValidationError, match="diverge"):
        _review(event, actor, wrong_target)
    assert not RevisaoJuridica.objects.filter(evento=event).exists()


@pytest.mark.django_db
def test_natal_canonical_identity_is_available_and_valid_for_human_review(review_case):
    event, _legacy_target = review_case
    event.target_text = "Lei nº 98206/2020"
    event.save(update_fields=["target_text", "updated_at"])
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei",
        series="municipal_lo",
        number="98206",
        year=2020,
    )
    target = Norma.objects.create(
        tipo="Lei", numero="98206", ano=2020,
        identity_key=identity.identity_key, identity_json=identity.identity_json,
    )

    assert candidate_normas_for_review(event) == [target]
    form = EventReviewForm(event=event)
    assert (str(target.pk), str(target)) in form.fields["target_norma_id"].choices
    actor = _reviewer()
    review = _review(event, actor, target)
    assert review.decision == RevisaoJuridica.Decision.APPROVE


@pytest.mark.django_db(transaction=True)
def test_duplicate_approval_is_idempotent_and_does_not_confirm_effect_date(review_case):
    event, target = review_case
    actor = _reviewer()
    first = _review(event, actor, target)
    event.refresh_from_db()
    second = _review(event, actor, target)

    assert first.pk == second.pk
    assert RevisaoJuridica.objects.filter(evento=event).count() == 1
    assert event.validado is True
    assert event_review_status(event) == "confirmed"
    assert event.effective_date_status == "unknown"
    assert event.effective_on is None


def test_rejection_is_append_only_and_withdraws_operational_approval(review_case):
    event, target = review_case
    actor = _reviewer()
    _review(event, actor, target)
    event.refresh_from_db()
    rejection = _review(
        event,
        actor,
        target,
        decision=RevisaoJuridica.Decision.REJECT,
        reason="A evidência não confirma a relação proposta.",
    )
    event.refresh_from_db()

    assert event.validado is False
    assert event.review_revision_id == rejection.pk
    assert event_review_status(event) == "rejected"
    assert RevisaoJuridica.objects.filter(evento=event).count() == 2
    assert event.norma_alvo_id == target.pk  # preserve the extracted candidate for audit


def test_changed_source_revision_makes_prior_decision_stale(review_case):
    event, target = review_case
    actor = _reviewer()
    _review(event, actor, target)
    event.refresh_from_db()
    event.dispositivo_fonte.revision_fingerprint = "source-rev-2"
    event.dispositivo_fonte.save(update_fields=["revision_fingerprint"])
    event.refresh_from_db()
    assert event_review_status(event) == "pending"


@pytest.mark.django_db(transaction=True)
def test_rejection_invalidates_corpus_once_without_deleting_event(review_case, mocker):
    event, _target = review_case
    actor = _reviewer()
    bump = mocker.patch("src.apps.legislation.signals._bump_after_commit")
    review_event(
        event_id=event.pk,
        actor=actor,
        decision=RevisaoJuridica.Decision.REJECT,
        reason="O texto citado não confirma o vínculo.",
        expected_fingerprint=event_review_fingerprint(event),
    )
    event.refresh_from_db()

    assert event.is_active is True
    assert event.validado is False
    assert RevisaoJuridica.objects.filter(evento=event).count() == 1
    assert bump.call_count == 1


@pytest.mark.django_db
def test_explicit_self_reference_can_only_be_reviewed_against_source_norma(review_case):
    event, target = review_case
    event.target_text = "Art. 2º desta Lei"
    event.target_reference_json = {"kind": "self_reference"}
    event.save(update_fields=["target_text", "target_reference_json", "updated_at"])
    event.refresh_from_db()
    actor = _reviewer()

    review = _review(event, actor, event.dispositivo_fonte.norma)
    assert review.decision == RevisaoJuridica.Decision.APPROVE
    with pytest.raises(ValidationError, match="própria norma"):
        _review(event, actor, target, reason="Tentativa de apontar para outro ato.")


def test_admin_review_requires_login_model_permission_and_csrf(review_case):
    event, target = review_case
    url = reverse("admin:legislation_eventoalteracao_review", args=[event.pk])
    guest = Client(enforce_csrf_checks=True)
    assert guest.get(url).status_code == 302

    reviewer = _reviewer(grant_permission=False)
    denied = Client(enforce_csrf_checks=True)
    denied.force_login(reviewer)
    assert denied.get(url).status_code == 403

    reviewer = _reviewer(username="reviewer-with-permission")
    client = Client(enforce_csrf_checks=True)
    client.force_login(reviewer)
    response = client.get(url)
    assert response.status_code == 200
    assert b"Texto literal da fonte" in response.content
    assert b"jurix-admin-review.css" in response.content
    assert b'class="jurix-pre-wrap"' in response.content
    assert b"n\303\243o confirma a data de efeito" in response.content.lower()
    event.refresh_from_db()
    assert event.validado is False
    assert not RevisaoJuridica.objects.filter(evento=event).exists()
    change_url = reverse("admin:legislation_eventoalteracao_change", args=[event.pk])
    change_page = client.get(change_url)
    assert change_page.status_code == 200
    assert b'name="validado"' not in change_page.content
    assert b'name="provenance_json"' not in change_page.content
    payload = {
        "decision": RevisaoJuridica.Decision.APPROVE,
        "reason": "Trecho e identidade conferidos pelo revisor.",
        "expected_fingerprint": event_review_fingerprint(event),
        "target_norma_id": str(target.pk),
        "target_dispositivo_id": "",
    }
    assert client.post(url, payload).status_code == 403
    payload["csrfmiddlewaretoken"] = client.cookies["csrftoken"].value
    response = client.post(url, payload)
    assert response.status_code == 302
    event.refresh_from_db()
    assert event.validado is True
    assert RevisaoJuridica.objects.filter(evento=event).count() == 1
