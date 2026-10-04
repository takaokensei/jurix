"""Authenticated, append-only human review for normative relation events."""

from __future__ import annotations

import hashlib
import json
from datetime import date

from django import forms
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.corpus_write_boundary import corpus_write_boundary
from src.processing.document_metadata import normalize_document_number
from src.processing.normative_reference import canonical_type
from src.processing.target_reconciliation import parse_target_reference


def candidate_normas_for_review(event: EventoAlteracao) -> list[Norma]:
    """Return exact typed/year candidates; never broaden a missing or external ref."""
    if (event.target_reference_json or {}).get("kind") == "self_reference":
        source_norma = event.dispositivo_fonte.norma
        return [source_norma] if source_norma else []
    reference = parse_target_reference(event)
    if reference is None or reference.jurisdiction in {"federal", "estadual", "distrital"}:
        return []
    result = []
    for norma in Norma.objects.filter(ano=reference.ano).only(
        "id", "tipo", "numero", "ano", "identity_json"
    ):
        if canonical_type(norma.tipo) != reference.type_key:
            continue
        if normalize_document_number(norma.numero) != reference.number_key:
            continue
        identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
        jurisdiction = str(identity.get("jurisdiction") or "").casefold()
        if jurisdiction and not jurisdiction.startswith("MUNICIPIO"):
            continue
        result.append(norma)
    return result


class EventReviewForm(forms.Form):
    decision = forms.ChoiceField(
        choices=(
            (RevisaoJuridica.Decision.APPROVE, "Confirmar relação"),
            (RevisaoJuridica.Decision.REJECT, "Rejeitar candidato"),
        )
    )
    reason = forms.CharField(widget=forms.Textarea(attrs={"rows": 4}), max_length=4000)
    expected_fingerprint = forms.CharField(widget=forms.HiddenInput)
    target_norma_id = forms.ChoiceField(required=False, label="Norma-alvo")
    target_dispositivo_id = forms.ChoiceField(required=False, label="Dispositivo (opcional)")

    def __init__(self, *args, event: EventoAlteracao, **kwargs):
        super().__init__(*args, **kwargs)
        candidates = candidate_normas_for_review(event)
        self.fields["target_norma_id"].choices = [("", "Selecione a norma")] + [
            (str(norma.pk), str(norma)) for norma in candidates
        ]
        selected_norma_id = self.data.get("target_norma_id") or (
            str(event.norma_alvo_id) if event.norma_alvo_id else ""
        )
        devices = Dispositivo.objects.none()
        if selected_norma_id and any(
            str(norma.pk) == str(selected_norma_id) for norma in candidates
        ):
            devices = Dispositivo.objects.filter(
                norma_id=selected_norma_id, is_active=True
            ).order_by("ordem", "pk")
        self.fields["target_dispositivo_id"].choices = [("", "Sem dispositivo específico")] + [
            (str(device.pk), f"{device.get_caminho_completo()}: {device.texto[:180]}")
            for device in devices
        ]
        self.fields["expected_fingerprint"].initial = event_review_fingerprint(event)

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Informe o motivo da decisão.")
        return reason


class EventTemporalReviewForm(forms.Form):
    effective_on = forms.DateField(
        label="Data de efeito jurídico",
        input_formats=["%Y-%m-%d"],
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    evidence_quote = forms.CharField(
        label="Trecho literal que fundamenta a data",
        widget=forms.Textarea(attrs={"rows": 3}),
        max_length=2000,
    )
    reason = forms.CharField(
        label="Motivo da revisão", widget=forms.Textarea(attrs={"rows": 3}), max_length=4000
    )
    expected_fingerprint = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, event: EventoAlteracao, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["expected_fingerprint"].initial = event_review_fingerprint(event)
        from src.processing.event_temporal_policy import event_temporal_decision

        candidate = event_temporal_decision(event)
        if candidate.status == "candidate":
            self.initial.setdefault("effective_on", candidate.effective_on)
            self.initial.setdefault("evidence_quote", candidate.basis.get("evidence_quote", ""))

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Informe o motivo da decisão.")
        return reason


def event_review_fingerprint(event: EventoAlteracao) -> str:
    """Bind a decision to the exact extracted event, source revision and evidence."""
    payload = {
        "event_id": event.pk,
        "is_active": event.is_active,
        "source_device_id": event.dispositivo_fonte_id,
        "source_revision": getattr(event.dispositivo_fonte, "revision_fingerprint", ""),
        "action": event.acao,
        "target_text": event.target_text,
        "reference_type": event.referencia_tipo,
        "reference_number": event.referencia_numero,
        "event_revision": event.revision_fingerprint,
        "target_reference": event.target_reference_json or {},
        "evidence": event.evidence_json or {},
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _decision_fingerprint(
    evidence_fingerprint: str,
    *,
    norma_id: int | None,
    dispositivo_id: int | None,
) -> str:
    payload = json.dumps([evidence_fingerprint, norma_id, dispositivo_id], separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def event_review_status(event: EventoAlteracao) -> str:
    """Return pending/rejected/confirmed only when the linked review is current."""
    review = getattr(event, "review_revision", None)
    if review is None:
        return "pending"
    current_fingerprint = _decision_fingerprint(
        event_review_fingerprint(event),
        norma_id=event.norma_alvo_id,
        dispositivo_id=event.dispositivo_alvo_id,
    )
    if review.target_fingerprint != current_fingerprint:
        return "pending"
    if review.decision == RevisaoJuridica.Decision.REJECT:
        return "rejected"
    if review.decision == RevisaoJuridica.Decision.APPROVE and event.validado:
        return "confirmed"
    return "pending"


def _actor_can_review(actor) -> bool:
    return bool(
        getattr(actor, "is_authenticated", False)
        and getattr(actor, "is_active", False)
        and getattr(actor, "is_staff", False)
        and actor.has_perm("legislation.change_eventoalteracao")
    )


def _validate_target(event: EventoAlteracao, norma: Norma, dispositivo: Dispositivo | None) -> None:
    if (event.target_reference_json or {}).get("kind") == "self_reference":
        if norma.pk != event.dispositivo_fonte.norma_id:
            raise ValidationError("Uma autorreferência deve apontar para a própria norma fonte.")
        if dispositivo is not None and dispositivo.norma_id != norma.pk:
            raise ValidationError("O dispositivo precisa pertencer à norma fonte.")
        return
    reference = parse_target_reference(event)
    if reference is None:
        raise ValidationError("Não há referência tipada, com ano explícito, para confirmar.")
    if reference.jurisdiction in {"federal", "estadual", "distrital"}:
        raise ValidationError(
            "Uma referência de jurisdição externa não pode ser confirmada como norma municipal."
        )
    if (
        canonical_type(norma.tipo) != reference.type_key
        or normalize_document_number(norma.numero) != reference.number_key
        or norma.ano != reference.ano
    ):
        raise ValidationError(
            "A norma escolhida diverge do tipo, número ou ano da referência extraída."
        )
    identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    jurisdiction = str(identity.get("jurisdiction") or "").casefold()
    if jurisdiction and not jurisdiction.startswith("MUNICIPIO"):
        raise ValidationError("A identidade escolhida não pertence ao escopo municipal do Jurix.")
    if dispositivo is not None:
        if dispositivo.norma_id != norma.pk:
            raise ValidationError("O dispositivo precisa pertencer à norma confirmada.")
        structural_type = (event.referencia_tipo or "").casefold()
        structural_number = (event.referencia_numero or "").strip()
        if structural_type in {"artigo", "paragrafo", "inciso", "alinea", "item"}:
            if dispositivo.tipo != structural_type:
                raise ValidationError("O tipo do dispositivo escolhido diverge da referência.")
            if (
                normalize_document_number(dispositivo.numero)
                != normalize_document_number(structural_number)
                and dispositivo.numero.casefold() != structural_number.casefold()
            ):
                raise ValidationError("O número do dispositivo escolhido diverge da referência.")


@transaction.atomic
def review_event(
    *,
    event_id: int,
    actor,
    decision: str,
    reason: str,
    expected_fingerprint: str,
    target_norma_id: int | None = None,
    target_dispositivo_id: int | None = None,
) -> RevisaoJuridica:
    """Approve or reject a relation with permission, freshness and audit checks."""
    if not _actor_can_review(actor):
        raise PermissionDenied("Você não tem permissão para revisar eventos jurídicos.")
    if decision not in {RevisaoJuridica.Decision.APPROVE, RevisaoJuridica.Decision.REJECT}:
        raise ValidationError("Decisão de revisão inválida.")
    if not reason or not reason.strip():
        raise ValidationError("Informe o motivo da decisão.")

    event = (
        EventoAlteracao.objects.select_for_update(of=("self",))
        .select_related("dispositivo_fonte", "norma_alvo", "dispositivo_alvo", "review_revision")
        .get(pk=event_id)
    )
    fingerprint = event_review_fingerprint(event)
    if not expected_fingerprint or expected_fingerprint != fingerprint:
        raise ValidationError(
            "A evidência mudou. Recarregue o evento antes de registrar a decisão."
        )

    norma = None
    dispositivo = None
    if decision == RevisaoJuridica.Decision.APPROVE:
        if target_dispositivo_id:
            dispositivo = (
                Dispositivo.objects.select_for_update()
                .select_related("norma")
                .get(pk=target_dispositivo_id)
            )
            norma = dispositivo.norma
        elif target_norma_id:
            norma = Norma.objects.select_for_update().get(pk=target_norma_id)
        else:
            raise ValidationError("Escolha a norma-alvo antes de confirmar a relação.")
        if target_norma_id and norma.pk != target_norma_id:
            raise ValidationError("O dispositivo não pertence à norma selecionada.")
        _validate_target(event, norma, dispositivo)

    decision_fingerprint = _decision_fingerprint(
        fingerprint,
        norma_id=norma.pk if norma else event.norma_alvo_id,
        dispositivo_id=dispositivo.pk if dispositivo else event.dispositivo_alvo_id,
    )
    same = (
        RevisaoJuridica.objects.filter(
            evento=event,
            target_fingerprint=decision_fingerprint,
            decision=decision,
            reason=reason.strip(),
            actor=actor,
        )
        .order_by("-created_at")
        .first()
    )
    same_target = (
        event.norma_alvo_id == norma.pk
        and event.dispositivo_alvo_id == (dispositivo.pk if dispositivo else None)
        if decision == RevisaoJuridica.Decision.APPROVE
        else True
    )
    if same and event.review_revision_id == same.pk and same_target:
        return same

    with corpus_write_boundary():
        review = RevisaoJuridica.objects.create(
            evento=event,
            target_fingerprint=decision_fingerprint,
            decision=decision,
            reason=reason.strip(),
            actor=actor,
        )
        if decision == RevisaoJuridica.Decision.APPROVE:
            event.norma_alvo = norma
            event.dispositivo_alvo = dispositivo
            event.validado = True
        else:
            # Retain the extracted candidate relation for audit, but remove its
            # operative approval. No source event or prior review is deleted.
            event.validado = False
        event.review_revision = review
        event.save(
            update_fields=[
                "norma_alvo",
                "dispositivo_alvo",
                "validado",
                "review_revision",
                "updated_at",
            ]
        )
    return review


@transaction.atomic
def review_event_effective_date(
    *,
    event_id: int,
    actor,
    effective_on: date,
    evidence_quote: str,
    reason: str,
    expected_fingerprint: str,
) -> RevisaoJuridica:
    """Confirm one explicit event date as a separate append-only decision."""
    from src.processing.event_temporal_policy import (
        _has_exact_quote,
        event_temporal_decision,
        temporal_candidate_fingerprint,
    )

    if not _actor_can_review(actor):
        raise PermissionDenied("Você não tem permissão para revisar datas de efeito.")
    if not isinstance(effective_on, date):
        raise ValidationError("Informe uma data de efeito válida.")
    if not evidence_quote or len(evidence_quote.strip()) < 12:
        raise ValidationError("Informe o trecho literal que fundamenta a data.")
    if not reason or not reason.strip():
        raise ValidationError("Informe o motivo da decisão temporal.")

    event = (
        EventoAlteracao.objects.select_for_update(of=("self",))
        .select_related(
            "dispositivo_fonte__norma", "norma_alvo", "dispositivo_alvo", "review_revision"
        )
        .get(pk=event_id)
    )
    from src.apps.legislation.event_review import event_review_status

    if event_review_status(event) != "confirmed" or not event.norma_alvo_id:
        raise ValidationError("Confirme primeiro, separadamente, a relação com o alvo jurídico.")
    temporal = event_temporal_decision(event)
    if temporal.status == "unsupported":
        raise ValidationError(temporal.reason)
    source_text = event.dispositivo_fonte.texto or ""
    if not _has_exact_quote(source_text, evidence_quote):
        raise ValidationError("O trecho informado não corresponde ao texto literal da fonte.")
    publication_on = temporal.publication_on
    if publication_on and effective_on < publication_on:
        raise ValidationError("Efeitos retroativos não são inferidos por esta revisão.")
    evidence_fingerprint = event_review_fingerprint(event)
    if not expected_fingerprint or evidence_fingerprint != expected_fingerprint:
        raise ValidationError("A evidência temporal mudou. Recarregue o evento antes de confirmar.")
    fingerprint = temporal_candidate_fingerprint(event, effective_on, evidence_quote)

    same = (
        RevisaoJuridica.objects.filter(
            evento=event,
            target_fingerprint=fingerprint,
            decision=RevisaoJuridica.Decision.APPROVE,
            reason=reason.strip(),
            actor=actor,
        )
        .order_by("-created_at")
        .first()
    )
    basis = event.effective_date_basis if isinstance(event.effective_date_basis, dict) else {}
    if (
        same
        and basis.get("review_id") == str(same.public_id)
        and event.effective_on == effective_on
    ):
        return same

    candidate_basis = (
        temporal.basis
        if temporal.status == "candidate"
        and temporal.effective_on == effective_on
        and temporal.basis.get("evidence_quote") == evidence_quote.strip()
        else {"kind": "human_reviewed_explicit_text", "evidence_quote": evidence_quote.strip()}
    )
    with corpus_write_boundary():
        review = RevisaoJuridica.objects.create(
            evento=event,
            target_fingerprint=fingerprint,
            decision=RevisaoJuridica.Decision.APPROVE,
            reason=reason.strip(),
            actor=actor,
        )
        event.effective_on = effective_on
        event.effective_date_status = "confirmed"
        event.effective_date_basis = {
            **candidate_basis,
            "effective_on": effective_on.isoformat(),
            "review_id": str(review.public_id),
            "review_type": "effective_date",
        }
        event.save(
            update_fields=[
                "effective_on",
                "effective_date_status",
                "effective_date_basis",
                "updated_at",
            ]
        )
    return review
