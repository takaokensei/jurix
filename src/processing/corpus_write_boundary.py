"""Coalesce legal-corpus invalidation at an explicit transactional write edge."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from django.db import transaction

logger = logging.getLogger(__name__)


@dataclass
class _BoundaryState:
    using: str
    dirty: bool = False
    depth: int = 1
    freshness_marked: bool = False


_active_boundary: ContextVar[_BoundaryState | None] = ContextVar(
    "jurix_corpus_write_boundary", default=None
)


def _mark_freshness_unknown(using: str) -> None:
    """Fail closed during the small commit-to-refresh interval."""
    try:
        from src.apps.operations.models import CorpusRevision

        CorpusRevision.objects.using(using).filter(key="municipal").exclude(
            completeness="unknown"
        ).update(completeness="unknown")
    except Exception:
        logger.error("Could not mark corpus freshness unknown during a legal write.")


def mark_corpus_dirty(*, using: str = "default") -> None:
    """Mark this transaction dirty, or retain legacy on-commit behavior outside it."""
    state = _active_boundary.get()
    if state is not None:
        if state.using != using:
            raise RuntimeError("A corpus write boundary cannot span database aliases.")
        state.dirty = True
        if not state.freshness_marked:
            _mark_freshness_unknown(using)
            state.freshness_marked = True
        return

    from src.apps.legislation.signals import _bump_after_commit

    _mark_freshness_unknown(using)
    transaction.on_commit(lambda: _bump_after_commit(using=using), using=using)


@contextmanager
def corpus_write_boundary(*, using: str = "default") -> Iterator[_BoundaryState]:
    """Group signals and bulk writes into one post-commit corpus refresh.

    Every boundary gets an atomic block/savepoint. Nested failures restore the
    prior dirty bit, and the outer transaction schedules at most one callback.
    ContextVar state is local to this execution context, never process-global.
    """
    existing = _active_boundary.get()
    if existing is not None:
        if existing.using != using:
            raise RuntimeError("A corpus write boundary cannot span database aliases.")
        dirty_before = existing.dirty
        freshness_marked_before = existing.freshness_marked
        existing.depth += 1
        try:
            with transaction.atomic(using=using):
                try:
                    yield existing
                except BaseException:
                    existing.dirty = dirty_before
                    existing.freshness_marked = freshness_marked_before
                    raise
        finally:
            existing.depth -= 1
        return

    state = _BoundaryState(using=using)
    token = _active_boundary.set(state)
    try:
        with transaction.atomic(using=using):
            yield state
            if state.dirty:
                from src.apps.legislation.signals import _bump_after_commit

                transaction.on_commit(lambda: _bump_after_commit(using=using), using=using)
    finally:
        _active_boundary.reset(token)
