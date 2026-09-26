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

@shared_task(bind=True, name="ingestion.segment_text_task", max_retries=2, default_retry_delay=60)
def segment_text_task(self, norma_id: int) -> dict[str, Any]:
    """
    Task Celery for segmenting legal text into hierarchical Dispositivo structure.

    Flow:
    1. Load norma with texto_original
    2. Parse text using regex patterns (LegalTextParser)
    3. Build hierarchy (parent-child relationships)
    4. Save Dispositivo instances to database
    5. Update norma status to 'segmented'

    Args:
        norma_id: ID of the norma in local database

    Returns:
        Dict with segmentation statistics:
        {
            'success': bool,
            'norma_id': int,
            'dispositivos_created': int,
            'articles': int,
            'paragraphs': int,
            'incisos': int,
            'alineas': int,
            'processing_time': float,
            'error': str (if failure)
        }

    Raises:
        Automatic retry in case of failure (2x with 60s backoff)
    """
    task_id = self.request.id
    start_time = time.time()

    logger.info(f"[Task {task_id}] Starting text segmentation for Norma ID={norma_id}")

    try:
        norma = Norma.objects.get(id=norma_id)

        # Validation: norma must have OCR text
        if not norma.texto_original:
            error_msg = "No texto_original found for segmentation"
            logger.warning(f"[Task {task_id}] {error_msg}")
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.save(update_fields=["needs_review", "processing_error", "updated_at"])
            return {"success": False, "error": error_msg, "norma_id": norma_id}

        # Mark as processing
        norma.status = "segmentation_processing"
        norma.save(update_fields=["status", "updated_at"])

        logger.info(f"[Task {task_id}] Parsing legal text ({len(norma.texto_original)} chars)")

        # Parse text with regex
        parser = LegalTextParser()
        elements = parser.parse_legal_text(norma.texto_original)

        if not elements:
            error_msg = "No legal elements found in text (no articles, paragraphs, etc.)"
            logger.warning(f"[Task {task_id}] {error_msg}")
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = "ocr_completed"  # Revert to previous status
            norma.save(update_fields=["needs_review", "processing_error", "status", "updated_at"])

            return {"success": False, "error": error_msg, "norma_id": norma_id}

        # Build hierarchy
        hierarchy = parser.build_hierarchy(elements)

        logger.info(
            f"[Task {task_id}] Found {len(hierarchy)} elements, " f"building hierarchical structure"
        )

        # Atomic transaction: delete existing and recreate with relationships
        with transaction.atomic():
            # Delete existing dispositivos (in case of reprocessing)
            deleted_count = Dispositivo.objects.filter(norma=norma).delete()[0]
            if deleted_count > 0:
                logger.info(f"[Task {task_id}] Deleted {deleted_count} existing dispositivos")

            # Create Dispositivo instances
            dispositivos_to_create = []
            stats = {
                "artigo": 0,
                "paragrafo": 0,
                "inciso": 0,
                "alinea": 0,
                "capitulo": 0,
                "secao": 0,
                "titulo": 0,
            }

            # First pass: create all dispositivos with materialized caminho/nivel
            for elem in hierarchy:
                texto_limpo = parser.clean_text(elem["texto"])

                dispositivo = Dispositivo(
                    norma=norma,
                    tipo=elem["tipo"],
                    numero=elem["numero"],
                    texto=texto_limpo,
                    texto_bruto=elem.get("full_match", ""),
                    ordem=elem["index"],
                    caminho=elem.get("caminho", ""),
                    nivel=elem.get("nivel", 0),
                    segmentation_confidence=1.0,  # High confidence for regex matches
                )

                dispositivos_to_create.append(dispositivo)

                # Count by type
                tipo = elem["tipo"]
                if tipo in stats:
                    stats[tipo] += 1
                else:
                    stats[tipo] = 1

            # Bulk create (fast)
            created_dispositivos = Dispositivo.objects.bulk_create(dispositivos_to_create)

            logger.info(
                f"[Task {task_id}] Created {len(created_dispositivos)} dispositivos "
                f"(bulk insert)"
            )

            # Second pass: set parent relationships using in-memory mapping O(1)
            db_by_ordem = {d.ordem: d for d in created_dispositivos}
            updates_needed = []
            for elem in hierarchy:
                if elem.get("parent_index") is not None:
                    child_db = db_by_ordem.get(elem["index"])
                    parent_db = db_by_ordem.get(elem["parent_index"])

                    if child_db and parent_db:
                        child_db.dispositivo_pai = parent_db
                        updates_needed.append(child_db)

            # Bulk update parents (if any)
            if updates_needed:
                Dispositivo.objects.bulk_update(updates_needed, ["dispositivo_pai"])
                logger.info(
                    f"[Task {task_id}] Updated {len(updates_needed)} parent relationships in bulk"
                )

            # Update norma status
            norma.status = Norma.Status.SEGMENTED
            norma.processing_error = ""
            norma.save(update_fields=["status", "processing_error", "updated_at"])

        processing_time = time.time() - start_time

        logger.info(
            f"[Task {task_id}] Segmentation completed for Norma {norma}: "
            f"{len(created_dispositivos)} dispositivos "
            f"({stats['artigo']} articles, {stats['paragrafo']} paragraphs, "
            f"{stats['inciso']} incisos, {stats['alinea']} alineas) "
            f"in {processing_time:.2f}s"
        )

        _invalidate_rag_cache()
        return {
            "success": True,
            "norma_id": norma_id,
            "norma_str": str(norma),
            "dispositivos_created": len(created_dispositivos),
            "articles": stats["artigo"],
            "paragraphs": stats["paragrafo"],
            "incisos": stats["inciso"],
            "alineas": stats["alinea"],
            "processing_time": processing_time,
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {"success": False, "error": error_msg, "norma_id": norma_id}

    except Exception as e:
        error_msg = f"Critical error in text segmentation for Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}")

        # Mark norma with error
        _mark_norma_failed(norma_id, "Segmentation error", e)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        return {"success": False, "error": str(e), "norma_id": norma_id}
