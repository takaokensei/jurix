"""Audited, step-specific human review actions for normative source documents."""

from __future__ import annotations

import hashlib
import json

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.corpus_write_boundary import corpus_write_boundary
from src.processing.document_metadata import extraction_identity_check

_EXTRACTION_REVIEW_PREFIX = "[extração documental revisada] "
_SEGMENTATION_REVIEW_PREFIX = "[segmentação documental revisada] "


class DocumentReviewBlocked(ValidationError):
    """A document review is unauthorized, stale, or outside the safe workflow."""


def extraction_review_fingerprint(
    document: DocumentoNormativo, extraction: ExtracaoDocumento
) -> str:
    payload = {
        "action": "accept_extraction",
        "document_public_id": str(document.public_id),
        "document_fingerprint": promotion_fingerprint(document),
        "extraction_id": extraction.pk,
        "extraction_sha256": extraction.extraction_sha256,
        "text_version": extraction.text_version,
        "status": extraction.status,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@transaction.atomic
def accept_document_extraction(
    *, document_id: str, extraction_id: int, reviewer, reason: str, expected_fingerprint: str
) -> dict:
    """Accept one immutable text extraction without promoting or segmenting it."""
    if not (
        getattr(reviewer, "is_authenticated", False)
        and getattr(reviewer, "is_active", False)
        and getattr(reviewer, "is_staff", False)
        and reviewer.has_perms((
            "legislation.change_documentonormativo",
            "legislation.add_revisaojuridica",
        ))
    ):
        raise PermissionDenied("Você não tem permissão para aceitar extração documental.")
    reason = str(reason or "").strip()
    if not reason:
        raise DocumentReviewBlocked("Informe o motivo da conferência da extração.")

    document = (
        DocumentoNormativo.objects.select_for_update(of=("self",))
        .select_related("norma", "accepted_extraction")
        .get(public_id=document_id)
    )
    extraction = ExtracaoDocumento.objects.get(pk=extraction_id, documento=document)
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    if metadata.get("synthetic"):
        raise DocumentReviewBlocked("Fixture sintética não pode ser aceita como extração jurídica revisada.")
    identity_check = extraction_identity_check(
        metadata.get("identity_candidate"), extraction.metadata_candidates_json
    )
    if identity_check["status"] == "conflict":
        raise DocumentReviewBlocked(
            "A epígrafe extraída diverge da identidade candidata; resolva a divergência antes de aceitar o texto."
        )
    if document.conflicts_json:
        raise DocumentReviewBlocked("Resolva os conflitos documentais antes de aceitar a extração.")
    if document.review_status == DocumentoNormativo.ReviewStatus.REJECTED:
        raise DocumentReviewBlocked("Documento rejeitado exige nova revisão formal.")
    if document.role != DocumentoNormativo.Role.ORIGINAL:
        raise DocumentReviewBlocked("Somente a extração do documento original pode ser selecionada nesta etapa.")
    if document.condition_of_use not in {
        DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
        DocumentoNormativo.ConditionOfUse.LICENSED,
    }:
        raise DocumentReviewBlocked("A condição de uso ainda não foi revisada.")
    if not document.norma_id or document.norma.identity_key != metadata.get("identity_key"):
        raise DocumentReviewBlocked("A identidade normativa precisa ser registrada e conferida primeiro.")
    if extraction.status != ExtracaoDocumento.Status.COMPLETE or not extraction.legal_text.strip():
        raise DocumentReviewBlocked("Somente uma extração completa e com texto legal pode ser aceita.")

    current_fingerprint = extraction_review_fingerprint(document, extraction)
    if current_fingerprint != expected_fingerprint:
        raise DocumentReviewBlocked("Fingerprint desatualizado; recarregue e compare o documento novamente.")
    prior_review = RevisaoJuridica.objects.filter(
        documento=document,
        decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=current_fingerprint,
        reason__startswith=_EXTRACTION_REVIEW_PREFIX,
    ).order_by("-created_at", "-pk").first()
    if document.accepted_extraction_id == extraction.pk and prior_review:
        return {
            "document_id": str(document.public_id),
            "extraction_id": extraction.pk,
            "review_id": str(prior_review.public_id),
            "idempotent": True,
            "text_promoted": False,
            "segmented": False,
        }
    if document.accepted_extraction_id:
        raise DocumentReviewBlocked(
            "Já existe uma extração aceita. Substituição exige uma revisão versionada própria."
        )

    review = RevisaoJuridica.objects.create(
        documento=document,
        target_fingerprint=current_fingerprint,
        decision=RevisaoJuridica.Decision.APPROVE,
        reason=f"{_EXTRACTION_REVIEW_PREFIX}{reason}",
        actor=reviewer,
    )
    document.accepted_extraction = extraction
    with corpus_write_boundary():
        document.save(update_fields=["accepted_extraction", "updated_at"])
    return {
        "document_id": str(document.public_id),
        "extraction_id": extraction.pk,
        "review_id": str(review.public_id),
        "idempotent": False,
        "text_promoted": False,
        "segmented": False,
    }


def segmentation_review_fingerprint(
    document: DocumentoNormativo, extraction: ExtracaoDocumento
) -> str:
    """Fingerprint the exact ordered segmentation without storing legal text in a log."""
    segments = []
    for row in DocumentoDispositivo.objects.filter(extracao=extraction).order_by("ordem", "pk"):
        segments.append({
            "key": row.structural_key,
            "parent": row.parent_key,
            "type": row.tipo,
            "number": row.numero,
            "order": row.ordem,
            "text_sha256": hashlib.sha256(row.texto.encode("utf-8")).hexdigest(),
            "start": row.start_offset,
            "end": row.end_offset,
            "page": row.page_index,
            "marker": row.marker,
        })
    payload = {
        "action": "review_segmentation",
        "document_public_id": str(document.public_id),
        "document_fingerprint": promotion_fingerprint(document),
        "extraction_id": extraction.pk,
        "extraction_sha256": extraction.extraction_sha256,
        "segments": segments,
    }
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def has_reviewed_document_segmentation(
    document: DocumentoNormativo, extraction: ExtracaoDocumento
) -> bool:
    fingerprint = segmentation_review_fingerprint(document, extraction)
    return RevisaoJuridica.objects.filter(
        documento=document,
        decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=fingerprint,
        reason__startswith=_SEGMENTATION_REVIEW_PREFIX,
    ).exists()


@transaction.atomic
def review_document_segmentation(
    *, document_id: str, extraction_id: int, reviewer, reason: str, expected_fingerprint: str
) -> dict:
    """Record human review of frozen, generated segments; never edits the segments."""
    if not (
        getattr(reviewer, "is_authenticated", False)
        and getattr(reviewer, "is_active", False)
        and getattr(reviewer, "is_staff", False)
        and reviewer.has_perms((
            "legislation.change_documentonormativo",
            "legislation.add_revisaojuridica",
        ))
    ):
        raise PermissionDenied("Você não tem permissão para revisar a segmentação documental.")
    reason = str(reason or "").strip()
    if not reason:
        raise DocumentReviewBlocked("Informe o motivo da revisão da segmentação.")

    document = (
        DocumentoNormativo.objects.select_for_update(of=("self",))
        .select_related("norma", "accepted_extraction")
        .get(public_id=document_id)
    )
    extraction = ExtracaoDocumento.objects.get(pk=extraction_id, documento=document)
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    if metadata.get("synthetic"):
        raise DocumentReviewBlocked("Fixture sintética não pode receber revisão jurídica humana.")
    if document.conflicts_json:
        raise DocumentReviewBlocked("Resolva os conflitos documentais antes de revisar a segmentação.")
    if (
        document.review_status != DocumentoNormativo.ReviewStatus.APPROVED
        or document.role != DocumentoNormativo.Role.ORIGINAL
        or document.condition_of_use not in {
            DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            DocumentoNormativo.ConditionOfUse.LICENSED,
        }
        or document.norma_id is None
        or document.norma.documento_base_id != document.pk
        or document.accepted_extraction_id != extraction.pk
        or extraction.status != ExtracaoDocumento.Status.COMPLETE
    ):
        raise DocumentReviewBlocked(
            "A Norma precisa ter documento original, identidade, extração e promoção revisados antes da segmentação."
        )
    segments = list(DocumentoDispositivo.objects.filter(extracao=extraction).order_by("ordem", "pk"))
    if not segments:
        raise DocumentReviewBlocked("Gere a segmentação preliminar antes de revisá-la.")
    if any(
        row.start_offset is None
        or row.end_offset is None
        or not row.texto.strip()
        or extraction.legal_text[row.start_offset:row.end_offset] != row.texto
        for row in segments
    ):
        raise DocumentReviewBlocked("Há segmento sem correspondência exata no texto-fonte; revisão bloqueada.")

    current_fingerprint = segmentation_review_fingerprint(document, extraction)
    if current_fingerprint != expected_fingerprint:
        raise DocumentReviewBlocked("Segmentação mudou desde a conferência; recarregue e revise novamente.")
    prior_review = RevisaoJuridica.objects.filter(
        documento=document,
        decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=current_fingerprint,
        reason__startswith=_SEGMENTATION_REVIEW_PREFIX,
    ).order_by("-created_at", "-pk").first()
    if prior_review:
        return {
            "document_id": str(document.public_id),
            "extraction_id": extraction.pk,
            "review_id": str(prior_review.public_id),
            "segment_count": len(segments),
            "idempotent": True,
        }
    review = RevisaoJuridica.objects.create(
        documento=document,
        target_fingerprint=current_fingerprint,
        decision=RevisaoJuridica.Decision.APPROVE,
        reason=f"{_SEGMENTATION_REVIEW_PREFIX}{reason}",
        actor=reviewer,
    )
    return {
        "document_id": str(document.public_id),
        "extraction_id": extraction.pk,
        "review_id": str(review.public_id),
        "segment_count": len(segments),
        "idempotent": False,
    }
