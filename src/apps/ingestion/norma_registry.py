"""Register a human-reviewed normative identity without consolidating its text."""

from __future__ import annotations

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from src.apps.ingestion.document_promotion import (
    PromotionBlocked,
    identity_for_norma,
    promotion_fingerprint,
)
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.corpus_write_boundary import corpus_write_boundary
from src.processing.document_metadata import build_normative_identity

_TYPE_LABELS = {
    "lei": "Lei Ordinária",
    "lei_complementar": "Lei Complementar",
    "lei_promulgada": "Lei Promulgada",
    "decreto": "Decreto",
}
_IDENTITY_REVIEW_PREFIX = "[identidade normativa revisada] "
_ALLOWED_CONDITIONS = {
    DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
    DocumentoNormativo.ConditionOfUse.LICENSED,
}


def _candidate_identity(document: DocumentoNormativo):
    metadata = document.metadata_json or {}
    candidate = metadata.get("identity_candidate") or {}
    identity = build_normative_identity(
        jurisdiction=candidate.get("jurisdiction") or "",
        raw_type=candidate.get("type") or "",
        series=candidate.get("series"),
        number=candidate.get("number"),
        year=candidate.get("year"),
    )
    if not identity.identity_key or metadata.get("identity_key") != identity.identity_key:
        raise PromotionBlocked("Identidade candidata incompleta ou divergente; não é possível registrá-la.")
    if identity.identity_json["type"] not in _TYPE_LABELS:
        raise PromotionBlocked("Espécie normativa sem rótulo de cadastro seguro.")
    if document.conflicts_json:
        raise PromotionBlocked("Conflitos de metadados precisam ser resolvidos antes do cadastro.")
    if metadata.get("synthetic"):
        raise PromotionBlocked("Fixture sintética não pode gerar registro normativo.")
    return identity


def _find_or_create_pending_norma(identity):
    identity_json = identity.identity_json
    existing = Norma.objects.select_for_update().filter(identity_key=identity.identity_key).first()
    if existing:
        if identity_for_norma(existing).identity_key != identity.identity_key:
            raise PromotionBlocked("Chave canônica existente diverge dos metadados da Norma.")
        return existing, False

    number = identity_json["number"]
    year = identity_json["year"]
    same_legacy_identifier = list(
        Norma.objects.select_for_update()
        .filter(ano=year)
        .only("pk", "identity_key", "identity_json", "tipo", "numero", "ano")
        .order_by("pk")
    )
    legacy_identities = [
        (norma, identity_for_norma(norma)) for norma in same_legacy_identifier
    ]
    matches = [
        norma for norma, legacy_identity in legacy_identities
        if legacy_identity.identity_key == identity.identity_key
    ]
    same_typed_number_conflicts = [
        norma for norma, legacy_identity in legacy_identities
        if legacy_identity.identity_json.get("number") == number
        and legacy_identity.identity_json.get("type") == identity_json["type"]
        and legacy_identity.identity_key != identity.identity_key
    ]
    if same_typed_number_conflicts:
        raise PromotionBlocked("Conflito tipado com identificador legado; revisão manual necessária.")
    if len(matches) > 1:
        raise PromotionBlocked("Mais de uma Norma legada corresponde à identidade; revisão manual necessária.")
    if matches:
        norma = matches[0]
        if norma.identity_key not in {None, identity.identity_key}:
            raise PromotionBlocked("Conflito entre identidade canônica e registro legado.")
        norma.identity_key = identity.identity_key
        norma.identity_json = identity_json
        with corpus_write_boundary():
            norma.save(update_fields=["identity_key", "identity_json", "updated_at"])
        return norma, False

    defaults = {
        "tipo": _TYPE_LABELS[identity_json["type"]],
        "numero": number,
        "ano": year,
        "identity_json": identity_json,
        "status": Norma.Status.PENDING,
        "needs_review": True,
        "texto_original": "",
        "texto_consolidado": "",
        "documento_base": None,
        "sapl_id": None,
        "sapl_url": "",
    }
    try:
        with transaction.atomic():
            norma, created = Norma.objects.get_or_create(
                identity_key=identity.identity_key,
                defaults=defaults,
            )
    except IntegrityError as exc:
        # The exact typed/number/year legacy constraint may have won a race.
        raise PromotionBlocked(
            "Conflito com identificador legado; não associei a Norma pelo número isoladamente."
        ) from exc
    if identity_for_norma(norma).identity_key != identity.identity_key:
        raise PromotionBlocked("Registro existente não corresponde integralmente à identidade revisada.")
    return norma, created


@transaction.atomic
def register_reviewed_identity(
    *,
    document_id: str,
    reviewer,
    reason: str,
    fingerprint: str,
    confirmed_identity_key: str,
    confirmed_condition_of_use: str,
) -> dict:
    """Link a reviewed identity to a pending Norma; never accept or consolidate text.

    A staff reviewer must confirm both the exact canonical identity and a usable
    public-record/license basis. The document stays pending and its extraction is
    not accepted; a later, separate workflow is required for promotion.
    """
    if not getattr(reviewer, "is_active", False) or not getattr(reviewer, "is_staff", False):
        raise PermissionDenied("Somente revisor staff autenticado pode revisar identidade normativa.")
    if not reason or not reason.strip():
        raise PromotionBlocked("Informe o motivo da revisão da identidade.")
    if confirmed_condition_of_use not in _ALLOWED_CONDITIONS:
        raise PromotionBlocked("Confirme uma base de registro público revisado ou licença.")

    document = (
        DocumentoNormativo.objects.select_for_update(of=("self",))
        .select_related("accepted_extraction")
        .get(public_id=document_id)
    )
    identity = _candidate_identity(document)
    if confirmed_identity_key != identity.identity_key:
        raise PromotionBlocked("A identidade confirmada diverge da candidata atual.")

    prior_review = RevisaoJuridica.objects.filter(
        documento=document,
        decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=fingerprint,
        reason__startswith=_IDENTITY_REVIEW_PREFIX,
    ).order_by("-created_at", "-pk").first()
    if prior_review:
        if document.norma_id is None or document.norma.identity_key != identity.identity_key:
            raise PromotionBlocked("A revisão anterior não aponta para a Norma esperada.")
        return {
            "document_id": str(document.public_id),
            "norma_id": document.norma_id,
            "identity_key": identity.identity_key,
            "review_id": str(prior_review.public_id),
            "norma_created": False,
            "idempotent": True,
            "text_promoted": False,
        }

    if promotion_fingerprint(document) != fingerprint:
        raise PromotionBlocked("Fingerprint desatualizado; recarregue o documento antes da revisão.")
    if document.norma_id:
        raise PromotionBlocked("Documento já vinculado; a identidade existente exige revisão própria.")
    if document.review_status == DocumentoNormativo.ReviewStatus.REJECTED:
        raise PromotionBlocked("Documento rejeitado exige uma nova revisão/superseding.")

    norma, norma_created = _find_or_create_pending_norma(identity)
    if document.condition_of_use not in {
        DocumentoNormativo.ConditionOfUse.UNKNOWN,
        confirmed_condition_of_use,
    }:
        raise PromotionBlocked("A condição de uso conflita com a confirmação do revisor.")

    with corpus_write_boundary():
        review = RevisaoJuridica.objects.create(
            documento=document,
            target_fingerprint=fingerprint,
            decision=RevisaoJuridica.Decision.APPROVE,
            reason=f"{_IDENTITY_REVIEW_PREFIX}{reason.strip()}",
            actor=reviewer,
        )
        document.norma = norma
        document.condition_of_use = confirmed_condition_of_use
        # Identity approval does not approve extracted text or the document as a
        # consolidated source. Keep the separate review/promotion gates pending.
        document.save(update_fields=["norma", "condition_of_use", "updated_at"])

    return {
        "document_id": str(document.public_id),
        "norma_id": norma.pk,
        "identity_key": identity.identity_key,
        "review_id": str(review.public_id),
        "norma_created": norma_created,
        "idempotent": False,
        "text_promoted": False,
    }
