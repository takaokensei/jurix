"""Register a human-reviewed normative identity without consolidating its text."""

from __future__ import annotations

import logging
import os
from copy import copy
from threading import Lock
from urllib.parse import urlsplit

from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, connections, transaction

from src.apps.ingestion.document_promotion import (
    PromotionBlocked,
    identity_for_norma,
    promotion_fingerprint,
)
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.corpus_write_boundary import corpus_write_boundary
from src.processing.document_metadata import build_normative_identity, extraction_identity_check
from src.processing.normative_reference import canonical_type

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
logger = logging.getLogger(__name__)
_SQLITE_REGISTRATION_LOCK = Lock()


def _is_synthetic_norma(norma: Norma) -> bool:
    identity_json = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    return identity_json.get("synthetic_fixture") is True or identity_json.get("synthetic") is True


def _queue_reviewed_identity_reconciliation(norma: Norma) -> int | None:
    """Queue only the bounded QA second pass after an identity review commits."""
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
    ):
        return None

    from src.apps.ingestion.normative_tasks import process_normative_work_item_task

    # Imported lazily because this entrypoint is deliberately unavailable outside
    # the isolated QA profile. The canonical identity revision is used when the
    # pending Norma has no text yet.
    from src.apps.ingestion.reconcile_corpus import enqueue_target_reconciliation

    queued = enqueue_target_reconciliation([norma.pk])
    if not queued["queued"]:
        return None
    item = queued["queued"][0]
    item_id = int(item["item_id"])
    if item["status"] == "pending":
        def dispatch_after_commit() -> None:
            try:
                process_normative_work_item_task.apply_async(
                    args=[item_id], queue="normative_qa"
                )
            except Exception:
                # The durable checkpoint remains pending for the bounded dispatcher.
                logger.warning(
                    "QA reconciliation checkpoint remains pending after dispatch failure (item_id=%s)",
                    item_id,
                )

        transaction.on_commit(dispatch_after_commit)
    return item_id


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


def _find_or_create_pending_norma(identity, *, document=None):
    identity_json = identity.identity_json
    existing = Norma.objects.select_for_update().filter(identity_key=identity.identity_key).first()
    if existing:
        if _is_synthetic_norma(existing):
            raise PromotionBlocked(
                "A identidade canônica pertence a uma Norma sintética; revisão manual de identidade necessária."
            )
        if identity_for_norma(existing).identity_key != identity.identity_key:
            raise PromotionBlocked("Chave canônica existente diverge dos metadados da Norma.")
        return existing, False, None

    if document is not None:
        sapl_norma, reconciliation = _reconcile_pending_sapl_norma(document, identity)
        if sapl_norma is not None:
            _apply_reviewed_sapl_identity(sapl_norma, identity, document)
            return sapl_norma, False, reconciliation

    number = identity_json["number"]
    year = identity_json["year"]
    same_legacy_identifier = list(
        Norma.objects.select_for_update()
        .filter(ano=year)
        .only("pk", "identity_key", "identity_json", "tipo", "numero", "ano")
        .order_by("pk")
    )
    legacy_identities = [
        (norma, identity_for_norma(norma))
        for norma in same_legacy_identifier
        if not _is_synthetic_norma(norma)
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
        if _is_synthetic_norma(norma):
            raise PromotionBlocked(
                "A identidade legada corresponde a uma Norma sintética; revisão manual necessária."
            )
        if norma.identity_key not in {None, identity.identity_key}:
            raise PromotionBlocked("Conflito entre identidade canônica e registro legado.")
        norma.identity_key = identity.identity_key
        norma.identity_json = identity_json
        with corpus_write_boundary():
            norma.save(update_fields=["identity_key", "identity_json", "updated_at"])
        return norma, False, None

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
        # A concurrent reviewer may have created this exact canonical identity.
        # Reuse only that exact winner; never fall back to number/year matching.
        winner = Norma.objects.select_for_update().filter(
            identity_key=identity.identity_key
        ).first()
        if winner:
            if _is_synthetic_norma(winner):
                raise PromotionBlocked(
                    "A identidade canônica pertence a uma Norma sintética; revisão manual de identidade necessária."
                ) from exc
            if identity_for_norma(winner).identity_key == identity.identity_key:
                return winner, False, None
        raise PromotionBlocked(
            "Conflito com identificador legado; não associei a Norma pelo número isoladamente."
        ) from exc
    if identity_for_norma(norma).identity_key != identity.identity_key:
        raise PromotionBlocked("Registro existente não corresponde integralmente à identidade revisada.")
    if _is_synthetic_norma(norma):
        raise PromotionBlocked(
            "A identidade canônica pertence a uma Norma sintética; revisão manual de identidade necessária."
        )
    return norma, created, None


def _reconcile_pending_sapl_norma(document, identity):
    """Return a safe legacy SAPL row only when its identity can be reviewed in place."""
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    try:
        sapl_id = int(metadata.get("sapl_id"))
    except (TypeError, ValueError):
        return None, None
    if document.source_kind != DocumentoNormativo.SourceKind.SAPL or document.norma_id:
        return None, None
    norma = Norma.objects.select_for_update().filter(sapl_id=sapl_id).first()
    if norma is None:
        return None, None
    if _is_synthetic_norma(norma):
        raise PromotionBlocked("A Norma SAPL correspondente é sintética; revisão de identidade bloqueada.")
    candidate = metadata.get("identity_candidate")
    if not isinstance(candidate, dict) or candidate != identity.identity_json:
        raise PromotionBlocked("A identidade SAPL candidata diverge dos metadados conferidos.")
    if metadata.get("identity_key") != identity.identity_key:
        raise PromotionBlocked("A chave da identidade SAPL candidata diverge.")
    if norma.numero != identity.identity_json["number"] or norma.ano != identity.identity_json["year"]:
        raise PromotionBlocked("Número ou ano do registro SAPL diverge; revisão manual específica necessária.")
    if canonical_type(norma.tipo) != identity.identity_json["type"]:
        raise PromotionBlocked("A espécie do registro SAPL diverge da candidata; revisão manual necessária.")
    publication_date = metadata.get("publication_date")
    if publication_date and norma.data_publicacao:
        if norma.data_publicacao.isoformat() != publication_date:
            raise PromotionBlocked("Data de publicação divergente; a revisão de identidade não pode alterá-la.")
    elif bool(publication_date) != bool(norma.data_publicacao):
        raise PromotionBlocked("Data de publicação ausente em uma das fontes; revisão temporal necessária.")
    old_url = urlsplit(norma.pdf_url)
    candidate_url = urlsplit(str(document.official_url or ""))
    if (
        old_url.hostname != "sapl.natal.rn.leg.br"
        or candidate_url.hostname != "sapl.natal.rn.leg.br"
        or old_url.path != candidate_url.path
        or old_url.query
        or candidate_url.query
        or old_url.fragment
        or candidate_url.fragment
    ):
        raise PromotionBlocked("O PDF SAPL existente não corresponde ao documento candidato.")
    if (
        norma.status != Norma.Status.PENDING
        or norma.texto_original
        or norma.texto_consolidado
        or norma.documento_base_id is not None
        or norma.dispositivos.exists()
        or norma.alteracoes_recebidas.exists()
        or norma.normative_snapshots.exists()
    ):
        raise PromotionBlocked("A Norma SAPL já contém texto ou relações; reconciliação automática bloqueada.")
    if Norma.objects.exclude(pk=norma.pk).filter(identity_key=identity.identity_key).exists():
        raise PromotionBlocked("A identidade canônica já pertence a outra Norma.")
    if document.review_status == DocumentoNormativo.ReviewStatus.REJECTED:
        raise PromotionBlocked("Documento SAPL rejeitado exige nova revisão/superseding.")
    return norma, {
        "previous_identity_key": norma.identity_key or "",
        "previous_type": norma.tipo,
        "previous_pdf_scheme": old_url.scheme,
    }


def _apply_reviewed_sapl_identity(norma, identity, document) -> None:
    """Normalize only identity fields after the reviewer confirms the exact source."""
    metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
    identity_json = identity.identity_json
    norma.tipo = _TYPE_LABELS[identity_json["type"]]
    norma.identity_key = identity.identity_key
    norma.identity_json = identity_json
    norma.pdf_url = document.official_url
    if metadata.get("sapl_url"):
        norma.sapl_url = str(metadata["sapl_url"])
    with corpus_write_boundary():
        norma.save(
            update_fields=[
                "tipo", "identity_key", "identity_json", "pdf_url", "sapl_url", "updated_at"
            ]
        )


@transaction.atomic
def _register_reviewed_identity_atomic(
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
    latest_extraction = document.extracoes.order_by("-created_at", "-pk").first()
    if latest_extraction:
        identity_check = extraction_identity_check(
            (document.metadata_json or {}).get("identity_candidate"),
            latest_extraction.metadata_candidates_json,
        )
        if identity_check["status"] == "conflict":
            raise PromotionBlocked(
                "A epígrafe extraída diverge da identidade candidata; não registre a identidade até resolver o conflito."
            )

    prior_review = RevisaoJuridica.objects.filter(
        documento=document,
        decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=fingerprint,
        reason__startswith=_IDENTITY_REVIEW_PREFIX,
    ).order_by("-created_at", "-pk").first()
    if prior_review:
        current_fingerprint = promotion_fingerprint(document)
        if current_fingerprint != fingerprint:
            # Registration itself changes UNKNOWN to the reviewer's confirmed
            # condition. Permit only that known post-review transition on retry.
            pre_review_document = copy(document)
            pre_review_document.condition_of_use = DocumentoNormativo.ConditionOfUse.UNKNOWN
            if promotion_fingerprint(pre_review_document) != fingerprint:
                raise PromotionBlocked(
                    "Fingerprint desatualizado; recarregue o documento antes da revisão."
                )
        if document.norma_id is None or document.norma.identity_key != identity.identity_key:
            raise PromotionBlocked("A revisão anterior não aponta para a Norma esperada.")
        reconciliation_item_id = _queue_reviewed_identity_reconciliation(document.norma)
        return {
            "document_id": str(document.public_id),
            "norma_id": document.norma_id,
            "identity_key": identity.identity_key,
            "review_id": str(prior_review.public_id),
            "norma_created": False,
            "idempotent": True,
            "text_promoted": False,
            "reconciliation_work_item_id": reconciliation_item_id,
        }

    if promotion_fingerprint(document) != fingerprint:
        raise PromotionBlocked("Fingerprint desatualizado; recarregue o documento antes da revisão.")
    if document.norma_id:
        raise PromotionBlocked("Documento já vinculado; a identidade existente exige revisão própria.")
    if document.review_status == DocumentoNormativo.ReviewStatus.REJECTED:
        raise PromotionBlocked("Documento rejeitado exige uma nova revisão/superseding.")

    norma, norma_created, reconciliation = _find_or_create_pending_norma(
        identity, document=document
    )
    if document.condition_of_use not in {
        DocumentoNormativo.ConditionOfUse.UNKNOWN,
        confirmed_condition_of_use,
    }:
        raise PromotionBlocked("A condição de uso conflita com a confirmação do revisor.")

    with corpus_write_boundary():
        review_reason = f"{_IDENTITY_REVIEW_PREFIX}{reason.strip()}"
        if reconciliation:
            review_reason += (
                " | metadados SAPL legados reconciliados após confirmação: "
                f"chave anterior={reconciliation['previous_identity_key'] or 'ausente'}; "
                f"tipo anterior={reconciliation['previous_type']}; "
                f"esquema PDF anterior={reconciliation['previous_pdf_scheme']}; "
                f"chave confirmada={identity.identity_key}."
            )
        review = RevisaoJuridica.objects.create(
            documento=document,
            target_fingerprint=fingerprint,
            decision=RevisaoJuridica.Decision.APPROVE,
            reason=review_reason,
            actor=reviewer,
        )
        document.norma = norma
        document.condition_of_use = confirmed_condition_of_use
        # Identity approval does not approve extracted text or the document as a
        # consolidated source. Keep the separate review/promotion gates pending.
        document.save(update_fields=["norma", "condition_of_use", "updated_at"])

    reconciliation_item_id = _queue_reviewed_identity_reconciliation(norma)
    return {
        "document_id": str(document.public_id),
        "norma_id": norma.pk,
        "identity_key": identity.identity_key,
        "review_id": str(review.public_id),
        "norma_created": norma_created,
        "legacy_sapl_identity_reconciled": bool(reconciliation),
        "idempotent": False,
        "text_promoted": False,
        "reconciliation_work_item_id": reconciliation_item_id,
    }


def register_reviewed_identity(
    *,
    document_id: str,
    reviewer,
    reason: str,
    fingerprint: str,
    confirmed_identity_key: str,
    confirmed_condition_of_use: str,
) -> dict:
    """Serialize SQLite's single writer; relational DBs rely on their unique key."""
    kwargs = {
        "document_id": document_id,
        "reviewer": reviewer,
        "reason": reason,
        "fingerprint": fingerprint,
        "confirmed_identity_key": confirmed_identity_key,
        "confirmed_condition_of_use": confirmed_condition_of_use,
    }
    if connections["default"].vendor == "sqlite":
        with _SQLITE_REGISTRATION_LOCK:
            return _register_reviewed_identity_atomic(**kwargs)
    return _register_reviewed_identity_atomic(**kwargs)
