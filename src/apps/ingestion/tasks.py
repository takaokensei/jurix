# ruff: noqa: F401,F403,E501,E701
"""Stable public ingestion task API; implementations live by domain."""

import logging

from src.apps.legislation.models import Norma

from . import core_tasks
from .consolidation_tasks import consolidate_norma_task
from .core_tasks import bulk_ingest_normas_task, cleanup_chat_attachments, ingest_normas_bulk_task, ingest_normas_task, ingest_sapl_corpus_task
from .download_tasks import _sapl_payload_hash, download_pdf_task, full_sync_sapl_task, incremental_sync_sapl_task
from .ner_tasks import extract_entities_task, generate_embedding_task
from .ocr_tasks import ocr_pdf_task
from .segmentation_tasks import segment_text_task
from .task_support import get_cache_service

logger = logging.getLogger(__name__)


def _process_norma_data(norma_data, auto_download=False):
    """Compatibility wrapper that keeps ``tasks.Norma`` patchable."""
    core_tasks.Norma = Norma
    return core_tasks._process_norma_data(norma_data, auto_download=auto_download)


def _invalidate_rag_cache():
    """Compatibility wrapper that keeps ``tasks.get_cache_service`` patchable."""
    try:
        get_cache_service().bump_corpus_version()
    except Exception:
        logger.warning("Could not invalidate the RAG cache", exc_info=True)


def _mark_norma_failed(norma_id, label, exc, *, set_failed_status=True):
    """Compatibility wrapper that keeps ``tasks.logger`` patchable."""
    try:
        norma = Norma.objects.get(id=norma_id)
        norma.needs_review = True
        norma.processing_error = f"{label}: {str(exc)[:200]}"
        update_fields = ["needs_review", "processing_error", "updated_at"]
        if set_failed_status:
            norma.status = "failed"
            update_fields.append("status")
        norma.save(update_fields=update_fields)
    except Exception:
        logger.warning(f"Could not record failure on Norma ID={norma_id}", exc_info=True)


__all__ = [
    "bulk_ingest_normas_task", "cleanup_chat_attachments", "consolidate_norma_task",
    "download_pdf_task", "extract_entities_task", "full_sync_sapl_task",
    "generate_embedding_task", "incremental_sync_sapl_task", "ingest_normas_bulk_task",
    "ingest_normas_task", "ingest_sapl_corpus_task", "ocr_pdf_task", "segment_text_task",
]
