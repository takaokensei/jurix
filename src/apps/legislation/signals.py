"""Invalidate retrieval caches when the legal corpus changes outside Celery."""

import logging

from django.db.models.signals import post_delete, post_save

from src.processing.corpus_write_boundary import mark_corpus_dirty

from .models import (
    Dispositivo,
    DocumentoNormativo,
    EventoAlteracao,
    ExtracaoDocumento,
    Norma,
    RevisaoJuridica,
)

logger = logging.getLogger(__name__)


def _bump_after_commit(*, using: str = "default") -> None:
    from src.processing.cache_service import get_cache_service
    from src.processing.corpus_identity import refresh_corpus_revision

    try:
        revision = refresh_corpus_revision(using=using)
        if revision["changed"]:
            get_cache_service().bump_corpus_version()
    except Exception:
        # Keep the legal write committed, but never claim the snapshot is current.
        logger.error("Corpus identity refresh failed after a legal write; freshness is unknown.")
        try:
            from src.apps.operations.models import CorpusRevision

            CorpusRevision.objects.using(using).filter(key="municipal").update(
                completeness="unknown"
            )
        except Exception:
            logger.error("Could not mark corpus completeness unknown after refresh failure.")


def _schedule_bump(*, using="default", **kwargs) -> None:
    mark_corpus_dirty(using=using)


def _schedule_selected_document_bump(sender, instance, *, using="default", **kwargs) -> None:
    """Ignore staging writes; only selected source revisions affect RAG identity."""
    if sender is DocumentoNormativo:
        relevant = Norma.objects.using(using).filter(documento_base_id=instance.pk).exists()
    elif sender is ExtracaoDocumento:
        relevant = DocumentoNormativo.objects.using(using).filter(
            accepted_extraction_id=instance.pk,
            normas_como_documento_base__isnull=False,
        ).exists()
    else:
        review = instance
        relevant = (
            DocumentoNormativo.objects.using(using)
            .filter(pk=review.documento_id, normas_como_documento_base__isnull=False)
            .exists()
            if review.documento_id
            else EventoAlteracao.objects.using(using)
            .filter(pk=review.evento_id, is_active=True)
            .exists()
        )
    if relevant:
        mark_corpus_dirty(using=using)


post_save.connect(_schedule_bump, sender=Norma, dispatch_uid="jurix.norma.cache_invalidation")
post_delete.connect(
    _schedule_bump, sender=Norma, dispatch_uid="jurix.norma.cache_invalidation.delete"
)
post_save.connect(
    _schedule_bump, sender=Dispositivo, dispatch_uid="jurix.dispositivo.cache_invalidation"
)
post_delete.connect(
    _schedule_bump, sender=Dispositivo, dispatch_uid="jurix.dispositivo.cache_invalidation.delete"
)
post_save.connect(
    _schedule_bump, sender=EventoAlteracao, dispatch_uid="jurix.evento.cache_invalidation"
)
post_delete.connect(
    _schedule_bump,
    sender=EventoAlteracao,
    dispatch_uid="jurix.evento.cache_invalidation.delete",
)
post_save.connect(
    _schedule_selected_document_bump,
    sender=DocumentoNormativo,
    dispatch_uid="jurix.document.selected.cache_invalidation",
)
post_delete.connect(
    _schedule_selected_document_bump,
    sender=DocumentoNormativo,
    dispatch_uid="jurix.document.selected.cache_invalidation.delete",
)
post_save.connect(
    _schedule_selected_document_bump,
    sender=ExtracaoDocumento,
    dispatch_uid="jurix.extraction.accepted.cache_invalidation",
)
post_delete.connect(
    _schedule_selected_document_bump,
    sender=ExtracaoDocumento,
    dispatch_uid="jurix.extraction.accepted.cache_invalidation.delete",
)
post_save.connect(
    _schedule_selected_document_bump,
    sender=RevisaoJuridica,
    dispatch_uid="jurix.legal_review.cache_invalidation",
)
post_delete.connect(
    _schedule_selected_document_bump,
    sender=RevisaoJuridica,
    dispatch_uid="jurix.legal_review.cache_invalidation.delete",
)
