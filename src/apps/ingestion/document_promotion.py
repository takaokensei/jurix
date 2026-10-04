"""Explicit, auditable promotion of a reviewed source document to a Norma."""

from __future__ import annotations

import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.corpus_write_boundary import corpus_write_boundary
from src.processing.document_metadata import TYPE_SERIES, build_normative_identity
from src.processing.normative_reference import canonical_type


class PromotionBlocked(ValidationError):
    """A candidate is ambiguous, stale, or not legally cleared for use."""


def promotion_fingerprint(document: DocumentoNormativo) -> str:
    payload = {
        "document_key": document.document_key,
        "content_sha256": document.content_sha256,
        "metadata_json": document.metadata_json,
        "conflicts_json": document.conflicts_json,
        "role": document.role,
        "condition_of_use": document.condition_of_use,
        "accepted_extraction_id": document.accepted_extraction_id,
        "accepted_extraction_sha256": (
            document.accepted_extraction.extraction_sha256 if document.accepted_extraction_id else None
        ),
    }
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def identity_for_norma(norma: Norma):
    identity = norma.identity_json or {}
    type_key = identity.get("type") or norma.tipo
    series = identity.get("series") or TYPE_SERIES.get(canonical_type(type_key))
    return build_normative_identity(
        jurisdiction=identity.get("jurisdiction") or "BR-RN-NATAL",
        raw_type=type_key,
        series=series,
        number=norma.numero,
        year=norma.ano,
    )


def promotion_candidates(document: DocumentoNormativo) -> dict:
    candidate_key = (document.metadata_json or {}).get("identity_key")
    reason = None
    if not candidate_key:
        reason = "identity_unresolved"
    elif document.conflicts_json:
        reason = "metadata_conflict"
    elif document.role != DocumentoNormativo.Role.ORIGINAL:
        reason = "document_role_requires_explicit_original"
    elif not document.accepted_extraction_id:
        reason = "extraction_not_accepted"
    elif document.accepted_extraction.status != ExtracaoDocumento.Status.COMPLETE:
        reason = "extraction_incomplete"
    matches = list(Norma.objects.filter(identity_key=candidate_key)) if candidate_key else []
    return {
        "identity_key": candidate_key,
        "norma_ids": [norma.pk for norma in matches],
        "status": "blocked" if reason or len(matches) != 1 else "candidate",
        "reason": reason or ("no_matching_norma" if not matches else "multiple_matching_normas" if len(matches) > 1 else None),
    }


@transaction.atomic
def promote_document(
    *, document_id: str, norma_id: int, actor, reason: str, expected_fingerprint: str,
    confirm_public_record: bool = False, confirmed_identity_key: str = "",
    confirmed_role: str = "",
) -> dict:
    if not getattr(actor, "is_active", False) or not getattr(actor, "is_staff", False):
        raise PermissionDenied("Somente revisor staff autenticado pode promover documento.")
    if not reason or not reason.strip():
        raise PromotionBlocked("Informe o motivo da revisão.")
    document = DocumentoNormativo.objects.select_for_update().get(public_id=document_id)
    prior_review = RevisaoJuridica.objects.filter(
        documento=document, decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=expected_fingerprint,
    ).order_by("-created_at").first()
    if document.norma_id == norma_id and document.review_status == DocumentoNormativo.ReviewStatus.APPROVED and prior_review:
        return {"document_id": str(document.public_id), "norma_id": norma_id, "review_id": str(prior_review.public_id), "identity_key": (document.metadata_json or {}).get("identity_key"), "idempotent": True}
    current_fingerprint = promotion_fingerprint(document)
    if current_fingerprint != expected_fingerprint:
        raise PromotionBlocked("Fingerprint desatualizado; recarregue o candidato antes de revisar.")
    if (document.metadata_json or {}).get("synthetic"):
        raise PromotionBlocked("Fixture sintética não pode ser promovida como evidência jurídica humana.")
    if not confirm_public_record:
        raise PromotionBlocked("Confirme explicitamente a condição de registro público/licenciado.")
    if confirmed_role != DocumentoNormativo.Role.ORIGINAL:
        raise PromotionBlocked("Confirme explicitamente que o documento selecionado é o original.")
    if document.review_status == DocumentoNormativo.ReviewStatus.REJECTED:
        raise PromotionBlocked("Documento rejeitado exige nova revisão/superseding; não pode ser reativado diretamente.")
    candidates = promotion_candidates(document)
    if candidates["status"] != "candidate" or candidates["norma_ids"] != [norma_id]:
        raise PromotionBlocked(f"Candidato não resolvido: {candidates['reason'] or 'norma divergente'}")
    norma = Norma.objects.select_for_update().get(pk=norma_id)
    expected_identity = candidates["identity_key"]
    if confirmed_identity_key != expected_identity:
        raise PromotionBlocked("Identidade não foi confirmada ou diverge do candidato atual.")
    if identity_for_norma(norma).identity_key != expected_identity:
        raise PromotionBlocked("Identidade tipada do alvo diverge do candidato documental.")
    if norma.documento_base_id and norma.documento_base_id != document.pk:
        raise PromotionBlocked("A Norma já possui documento-base; substituição requer revisão própria.")
    if document.norma_id and document.norma_id != norma.pk:
        raise PromotionBlocked("Documento já associado a outra Norma; não será movido automaticamente.")

    review = RevisaoJuridica.objects.create(
        documento=document, target_fingerprint=current_fingerprint,
        decision=RevisaoJuridica.Decision.APPROVE, reason=reason.strip(), actor=actor,
    )
    document.norma = norma
    document.review_status = DocumentoNormativo.ReviewStatus.APPROVED
    document.condition_of_use = DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED
    document.save(update_fields=["norma", "review_status", "condition_of_use", "updated_at"])
    with corpus_write_boundary():
        norma.documento_base = document
        norma.identity_key = expected_identity
        norma.identity_json = (document.metadata_json or {}).get("identity_candidate", norma.identity_json)
        norma.save(update_fields=["documento_base", "identity_key", "identity_json", "updated_at"])
    return {"document_id": str(document.public_id), "norma_id": norma.pk, "review_id": str(review.public_id), "identity_key": expected_identity}
