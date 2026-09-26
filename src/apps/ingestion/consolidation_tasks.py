# ruff: noqa: F401,F403,E501,E701
from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import fitz
import pytesseract
from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from PIL import Image

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.clients.sapl.sapl_client import SaplAPIClient
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor

logger = logging.getLogger(__name__)

from .task_support import _invalidate_rag_cache, _mark_norma_failed

@shared_task(bind=True, name="ingestion.consolidate_norma", max_retries=3, default_retry_delay=60)
def consolidate_norma_task(self, norma_id: int) -> dict[str, Any]:
    """
    Consolidate a Norma by applying all alteration events.

    This task:
    1. Loads a Norma with status='entities_extracted'
    2. Loads all its Dispositivos
    3. Loads all EventoAlteracao affecting the norma
    4. Uses ConsolidationEngine to apply alterations temporally
    5. Generates consolidated text
    6. Saves to norma.texto_consolidado
    7. Updates Norma status to 'consolidated'

    Args:
        norma_id: Primary key of the Norma to consolidate

    Returns:
        Dictionary with success status and consolidation statistics
    """
    task_id = self.request.id
    start_time = time.time()

    logger.info(f"[Task {task_id}] Starting consolidation for Norma ID={norma_id}")

    try:
        # Fetch Norma
        norma = Norma.objects.get(id=norma_id)

        # Validate status
        if norma.status != "entities_extracted":
            logger.warning(
                f"[Task {task_id}] Norma {norma} has status '{norma.status}', "
                f"expected 'entities_extracted'. Proceeding anyway."
            )

        # Update status to processing
        norma.status = "consolidation"
        norma.save(update_fields=["status", "updated_at"])

        # Initialize consolidation engine
        engine = ConsolidationEngine(norma)

        # Execute consolidation
        logger.info(f"[Task {task_id}] Executing consolidation algorithm...")
        consolidated_text = engine.consolidate()

        # Get statistics
        stats = engine.get_statistics()

        # Save consolidated text
        norma.texto_consolidado = consolidated_text
        update_fields = ["texto_consolidado", "updated_at"]
        if stats["needs_review"]:
            # Unapplied events or heuristically extracted additions: flag for a
            # human. Never clear the flag here; only a reviewer may do that.
            norma.status = "failed"
            norma.needs_review = True
            unresolved = stats.get("events_unresolved", 0)
            norma.processing_error = (
                "Consolidação requer revisão humana: "
                f"{unresolved} evento(s) de alteração não resolvido(s)."
            )
            update_fields.extend(["status", "needs_review", "processing_error"])
            success = False
        else:
            norma.status = "consolidated"
            norma.processing_error = ""
            update_fields.extend(["status", "processing_error"])
            success = True
        norma.save(update_fields=update_fields)

        processing_time = time.time() - start_time

        logger.info(
            f"[Task {task_id}] Consolidation completed for Norma {norma}: "
            f"{stats['total_dispositivos']} dispositivos, "
            f"{stats['revoked_count']} revoked, "
            f"{stats['altered_count']} altered, "
            f"{stats['added_count']} added, "
            f"{stats['events_applied']}/{stats['events_processed']} events applied "
            f"({stats['events_unresolved']} unresolved, "
            f"needs_review={stats['needs_review']}) "
            f"in {processing_time:.2f}s"
        )

        _invalidate_rag_cache()
        return {
            "success": success,
            "norma_id": norma_id,
            "norma_str": str(norma),
            "total_dispositivos": stats["total_dispositivos"],
            "revoked_count": stats["revoked_count"],
            "altered_count": stats["altered_count"],
            "added_count": stats["added_count"],
            "events_processed": stats["events_processed"],
            "events_applied": stats["events_applied"],
            "events_unresolved": stats["events_unresolved"],
            "needs_review": stats["needs_review"],
            "consolidated_length": len(consolidated_text),
            "processing_time": processing_time,
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {"success": False, "error": error_msg, "norma_id": norma_id}

    except Exception as e:
        error_msg = f"Critical error in consolidation for Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}", exc_info=True)

        # Mark norma with error
        _mark_norma_failed(norma_id, "Consolidation error", e)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        return {"success": False, "error": str(e), "norma_id": norma_id}
