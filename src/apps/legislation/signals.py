"""Invalidate retrieval caches when the legal corpus changes outside Celery."""

from django.db import transaction
from django.db.models.signals import post_delete, post_save

from .models import Dispositivo, Norma


def _bump_after_commit() -> None:
    from src.processing.cache_service import get_cache_service

    try:
        get_cache_service().bump_corpus_version()
    except Exception:
        # Cache invalidation is best effort; it must never break a legal write.
        return


def _schedule_bump(**kwargs) -> None:
    transaction.on_commit(_bump_after_commit)


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
