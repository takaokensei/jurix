"""Bounded SAPL ingestion orchestration.

The previous bulk task enqueued every page immediately. With a Celery worker
configured as ``solo`` this turns a large import into an unbounded backlog and
makes failures difficult to diagnose. This task processes pages sequentially
inside one Celery execution while retaining the existing page task as the
single implementation of page processing.
"""
from __future__ import annotations

import logging
from typing import Any

from celery import shared_task
from django.conf import settings

logger = logging.getLogger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=30)
def bounded_sapl_ingest_task(
    self,
    max_normas: int = 500,
    batch_size: int = 25,
    offset: int = 0,
    **filters: Any,
) -> dict[str, Any]:
    """Ingest SAPL pages serially without flooding Redis/Celery."""
    from src.apps.ingestion.tasks import ingest_normas_task

    max_normas = max(1, min(int(max_normas), int(getattr(settings, "SAPL_MAX_BULK_NORMAS", 5000))))
    batch_size = max(1, min(int(batch_size), 100))
    offset = max(0, int(offset))
    pages = 0
    processed = 0
    failures: list[dict[str, Any]] = []

    while processed < max_normas:
        page_limit = min(batch_size, max_normas - processed)
        result = ingest_normas_task.apply(
            kwargs={
                "limit": page_limit,
                "offset": offset,
                **filters,
            }
        )
        pages += 1
        if not result.successful():
            error = str(result.result)
            failures.append({"offset": offset, "error": error})
            logger.error("SAPL page failed at offset=%s: %s", offset, error)
            raise self.retry(exc=RuntimeError(error))

        value = result.result if isinstance(result.result, dict) else {}
        fetched = int(value.get("count", value.get("processed", page_limit)) or 0)
        processed += max(0, min(fetched, page_limit))
        offset += page_limit

        # A page task that returns zero records means there is no more data.
        if fetched == 0 or fetched < page_limit:
            break

    from src.processing.target_reconciliation import reconcile_unresolved_event_targets
    reconciliation = reconcile_unresolved_event_targets(limit=max_normas * 10)

    return {
        "success": not failures,
        "pages": pages,
        "requested": max_normas,
        "processed": processed,
        "next_offset": offset,
        "failures": failures,
        "target_reconciliation": reconciliation,
    }
