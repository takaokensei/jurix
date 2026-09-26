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

from .task_support import _invalidate_rag_cache, _mark_norma_failed, _resolve_norma_reference

@shared_task(bind=True, name="ingestion.extract_entities", max_retries=3, default_retry_delay=60)
def extract_entities_task(self, norma_id: int) -> dict[str, Any]:
    """
    Extract named entities and alteration events from segmented Norma.

    This task:
    1. Loads a Norma with status='segmented'
    2. Iterates through all its Dispositivos
    3. Uses NER (regex-based) to detect:
       - Action verbs (revoga, altera, adiciona, etc.)
       - Legal references (Art. X, Lei Y/Z)
       - Target entities
    4. Creates EventoAlteracao instances for each detected event
    5. Updates Norma status to 'entities_extracted'

    Args:
        norma_id: Primary key of the Norma to process

    Returns:
        Dictionary with success status and extraction statistics
    """
    task_id = self.request.id
    start_time = time.time()

    logger.info(f"[Task {task_id}] Starting NER entity extraction for Norma ID={norma_id}")

    try:
        # Fetch Norma
        norma = Norma.objects.get(id=norma_id)
        original_status = norma.status

        # Validate status
        if norma.status not in ("segmented", "entities_extracted", "consolidated"):
            logger.warning(
                f"[Task {task_id}] Norma {norma} has status '{norma.status}', "
                f"expected 'segmented' or higher. Proceeding anyway."
            )

        # Only update status to entity_extraction if not already consolidated
        if original_status != "consolidated":
            norma.status = "entity_extraction"
            norma.save(update_fields=["status", "updated_at"])

        # Initialize NER extractor
        extractor = LegalNERExtractor()

        # Fetch all dispositivos for this norma
        dispositivos = Dispositivo.objects.filter(norma=norma).select_related("norma")

        if not dispositivos.exists():
            logger.warning(
                f"[Task {task_id}] No dispositivos found for Norma {norma}. "
                f"Cannot extract entities."
            )
            norma.status = (
                original_status
                if original_status in ("consolidated", "entities_extracted")
                else "segmented"
            )
            norma.save(update_fields=["status", "updated_at"])
            return {
                "success": True,
                "norma_id": norma_id,
                "events_created": 0,
                "dispositivos_processed": 0,
                "message": "No dispositivos to process",
            }

        logger.info(f"[Task {task_id}] Found {dispositivos.count()} dispositivos to analyze")

        # Extract events from each dispositivo
        events_to_create = []
        dispositivos_with_events = 0

        for dispositivo in dispositivos:
            texto = dispositivo.texto.strip()

            if len(texto) < 20:  # Skip very short texts
                continue

            # Extract events using NER
            extracted_events = extractor.extract_events(texto=texto, dispositivo_id=dispositivo.id)

            if extracted_events:
                dispositivos_with_events += 1

                for event_data in extracted_events:
                    # Try to resolve norma_alvo if we have norma_info
                    norma_alvo = None
                    if event_data.get("norma_referenciada"):
                        norma_info = event_data["norma_referenciada"]
                        # Attempt to find the referenced norma
                        norma_alvo = _resolve_norma_reference(
                            tipo=norma_info.get("tipo", ""),
                            numero=norma_info.get("numero", ""),
                            ano=norma_info.get("ano", ""),
                        )

                    # Handle self-references (desta Lei)
                    if event_data["referencia_tipo"] == "self_reference":
                        norma_alvo = norma

                    # Create EventoAlteracao instance
                    evento = EventoAlteracao(
                        dispositivo_fonte=dispositivo,
                        acao=event_data["acao"],
                        target_text=event_data["target_text"][:500],  # Truncate to max_length
                        norma_alvo=norma_alvo,
                        extraction_confidence=event_data["extraction_confidence"],
                        extraction_method=event_data["extraction_method"],
                        referencia_tipo=event_data["referencia_tipo"][:50],
                        referencia_numero=event_data["referencia_numero"][:50],
                    )
                    events_to_create.append(evento)

        # Atomically clean up prior events for this norma and bulk create the new clean events
        with transaction.atomic():
            EventoAlteracao.objects.filter(dispositivo_fonte__norma=norma).delete()
            if events_to_create:
                EventoAlteracao.objects.bulk_create(events_to_create, batch_size=500)

            # Preserve consolidated status if previously consolidated
            norma.status = (
                original_status if original_status == "consolidated" else "entities_extracted"
            )
            norma.processing_error = ""
            norma.save(update_fields=["status", "processing_error", "updated_at"])

        processing_time = time.time() - start_time

        # Calculate statistics by action type
        action_stats = {}
        for evento in events_to_create:
            action_stats[evento.acao] = action_stats.get(evento.acao, 0) + 1

        logger.info(
            f"[Task {task_id}] Entity extraction completed for Norma {norma}: "
            f"{len(events_to_create)} events from {dispositivos_with_events} dispositivos "
            f"(out of {dispositivos.count()} total) in {processing_time:.2f}s. "
            f"Action distribution: {action_stats}"
        )

        return {
            "success": True,
            "norma_id": norma_id,
            "norma_str": str(norma),
            "events_created": len(events_to_create),
            "dispositivos_processed": dispositivos.count(),
            "dispositivos_with_events": dispositivos_with_events,
            "action_stats": action_stats,
            "processing_time": processing_time,
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {"success": False, "error": error_msg, "norma_id": norma_id}

    except Exception as e:
        error_msg = f"Critical error in entity extraction for Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}", exc_info=True)

        # Mark norma with error
        _mark_norma_failed(norma_id, "Entity extraction error", e)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        return {"success": False, "error": str(e), "norma_id": norma_id}

@shared_task(bind=True, name="ingestion.generate_embedding", max_retries=3, default_retry_delay=60)
def generate_embedding_task(
    self, dispositivo_id: int, model: str = "nomic-embed-text"
) -> dict[str, Any]:
    """
    Generate embedding vector for a Dispositivo using Ollama.

    This task:
    1. Loads a Dispositivo by ID
    2. Prepares text for embedding (dispositivo content + context)
    3. Calls Ollama API to generate embedding
    4. Stores embedding in dispositivo.embedding field
    5. Updates metadata (model, timestamp)

    Args:
        dispositivo_id: Primary key of the Dispositivo
        model: Ollama model to use for embedding (default: nomic-embed-text)

    Returns:
        Dictionary with success status and embedding statistics
    """
    task_id = self.request.id
    start_time = time.time()

    logger.info(
        f"[Task {task_id}] Starting embedding generation for Dispositivo ID={dispositivo_id}"
    )

    try:
        # Fetch Dispositivo
        dispositivo = Dispositivo.objects.select_related("norma").get(id=dispositivo_id)

        # Prepare text for embedding
        # Include context: norma info + dispositivo hierarchy + content
        norma = dispositivo.norma
        context_parts = [
            f"{norma.tipo} {norma.numero}/{norma.ano}",
            f"{dispositivo.get_full_identifier()}",
            dispositivo.texto,
        ]

        # Add parent context for better embeddings
        if dispositivo.dispositivo_pai:
            context_parts.insert(2, f"Contexto: {dispositivo.dispositivo_pai}")

        embedding_text = " | ".join(context_parts)

        logger.debug(f"[Task {task_id}] Prepared text of {len(embedding_text)} chars for embedding")

        # Initialize Ollama service
        ollama = OllamaService(model=model)

        # Check if Ollama is healthy
        if not ollama.check_health():
            raise Exception("Ollama service is not accessible")

        # Generate embedding
        embedding = ollama.generate_embedding(embedding_text, model=model)

        if not embedding:
            raise Exception("Failed to generate embedding (None returned)")

        # Store embedding using SQL to avoid dimension mismatch issues
        from django.db import connection
        from django.utils import timezone

        # Use SQL directly - first clear, then set new embedding
        with connection.cursor() as cursor:
            # Step 1: Clear old embedding first
            cursor.execute(
                "UPDATE legislation_dispositivo SET embedding = NULL WHERE id = %s",
                [dispositivo_id],
            )

            # Step 2: Set new embedding (now that field is NULL, dimension mismatch won't occur)
            vector_str = "[" + ",".join(map(str, embedding)) + "]"
            now = timezone.now()
            cursor.execute(
                """
                UPDATE legislation_dispositivo
                SET embedding = %s::vector,
                    embedding_model = %s,
                    embedding_generated_at = %s,
                    updated_at = %s
                WHERE id = %s
                """,
                [vector_str, model, now, now, dispositivo_id],
            )

        # Refresh from DB to get updated values
        dispositivo.refresh_from_db()

        processing_time = time.time() - start_time

        logger.info(
            f"[Task {task_id}] Embedding generated for Dispositivo {dispositivo}: "
            f"dimension={len(embedding)}, model={model}, time={processing_time:.2f}s"
        )

        _invalidate_rag_cache()
        return {
            "success": True,
            "dispositivo_id": dispositivo_id,
            "dispositivo_str": str(dispositivo),
            "embedding_dimension": len(embedding),
            "model": model,
            "text_length": len(embedding_text),
            "processing_time": processing_time,
        }

    except Dispositivo.DoesNotExist:
        error_msg = f"Dispositivo ID={dispositivo_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {"success": False, "error": error_msg, "dispositivo_id": dispositivo_id}

    except Exception as e:
        error_msg = (
            f"Critical error in embedding generation for Dispositivo ID={dispositivo_id}: {str(e)}"
        )
        logger.error(f"[Task {task_id}] {error_msg}", exc_info=True)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        return {"success": False, "error": str(e), "dispositivo_id": dispositivo_id}
