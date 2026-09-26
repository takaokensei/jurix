# ruff: noqa: F401,F403,E501,E701
"""Stable public ingestion task API; implementations live by domain."""

from .consolidation_tasks import consolidate_norma_task
from .core_tasks import (
    bulk_ingest_normas_task,
    cleanup_chat_attachments,
    ingest_normas_bulk_task,
    ingest_normas_task,
    ingest_sapl_corpus_task,
)
from .download_tasks import download_pdf_task, full_sync_sapl_task, incremental_sync_sapl_task
from .ner_tasks import extract_entities_task, generate_embedding_task
from .ocr_tasks import ocr_pdf_task
from .segmentation_tasks import segment_text_task

__all__ = [
    "bulk_ingest_normas_task", "cleanup_chat_attachments", "consolidate_norma_task",
    "download_pdf_task", "extract_entities_task", "full_sync_sapl_task",
    "generate_embedding_task", "incremental_sync_sapl_task", "ingest_normas_bulk_task",
    "ingest_normas_task", "ingest_sapl_corpus_task", "ocr_pdf_task", "segment_text_task",
]
