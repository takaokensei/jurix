"""Stable public ingestion task API."""

from __future__ import annotations

import sys
from typing import Any

from . import tasks_legacy
from .consolidation_tasks import consolidate_norma_task
from .core_tasks import cleanup_chat_attachments, extract_entities_task
from .download_tasks import (
    bulk_ingest_normas_task,
    download_pdf_task,
    full_sync_sapl_task,
    incremental_sync_sapl_task,
    ingest_normas_task,
    ingest_sapl_corpus_task,
)
from .ner_tasks import generate_embedding_task
from .ocr_tasks import ocr_pdf_task
from .segmentation_tasks import segment_text_task
from .tasks_legacy import *  # noqa: F403,F401

ingest_normas_bulk_task = bulk_ingest_normas_task

__all__ = [
    "bulk_ingest_normas_task",
    "cleanup_chat_attachments",
    "consolidate_norma_task",
    "download_pdf_task",
    "extract_entities_task",
    "full_sync_sapl_task",
    "generate_embedding_task",
    "incremental_sync_sapl_task",
    "ingest_normas_bulk_task",
    "ingest_normas_task",
    "ingest_sapl_corpus_task",
    "ocr_pdf_task",
    "segment_text_task",
]


class _TasksModule(sys.modules[__name__].__class__):
    def __getattr__(self, name: str) -> Any:
        return getattr(tasks_legacy, name)

    def __setattr__(self, name: str, value: Any) -> None:
        super().__setattr__(name, value)
        if hasattr(tasks_legacy, name) or name.startswith("_") or name == "logger":
            setattr(tasks_legacy, name, value)


sys.modules[__name__].__class__ = _TasksModule
