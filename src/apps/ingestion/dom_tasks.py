"""Celery entrypoints for QA-only official DOM edition synchronization."""

from __future__ import annotations

from celery import shared_task


@shared_task(name="ingestion.sync_dom_natal_editions", ignore_result=False)
def sync_dom_natal_editions_task(
    lookback_months: int = 3,
    max_new_total: int = 5,
):
    """Stage newly discovered DOM editions only in the isolated QA profile."""
    from .dom_sync import sync_dom_natal_editions

    return sync_dom_natal_editions(
        lookback_months=lookback_months,
        max_new_total=max_new_total,
    )
