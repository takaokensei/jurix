"""Compatibility facade for ingestion tasks."""

from .tasks_legacy import (
    bulk_ingest_normas_task,
    download_pdf_task,
    full_sync_sapl_task,
    incremental_sync_sapl_task,
    ingest_normas_task,
)

__all__ = [
    "bulk_ingest_normas_task",
    "download_pdf_task",
    "full_sync_sapl_task",
    "incremental_sync_sapl_task",
    "ingest_normas_task",
]
