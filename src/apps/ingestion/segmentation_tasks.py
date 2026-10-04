# ruff: noqa: F401,F403,E501,E701,I001
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
from django.core.exceptions import ValidationError
from django.db import connection, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_date
from PIL import Image

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.clients.sapl.sapl_client import SaplAPIClient
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.device_hierarchy import validate_hierarchy
from src.processing.device_revision import (
    ordered_hierarchy_rows,
    parsed_device_identities,
    revision_fingerprint,
    structural_key,
)
from src.processing.document_segmentation import segment_document_extraction
from src.processing.legal_parser import LegalTextParser, extract_publication_metadata
from src.processing.ner_extractor import LegalNERExtractor

from .task_support import _invalidate_rag_cache, _mark_norma_failed

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="ingestion.segment_document_extraction_task", max_retries=2, default_retry_delay=60)
def segment_document_extraction_task(self, extraction_id: int) -> dict[str, Any]:
    """Create immutable document-level device rows for the accepted base extraction."""
    try:
        result = segment_document_extraction(extraction_id)
        return {
            "success": True,
            "extraction_id": result.extraction_id,
            "devices_created": result.created,
            "unchanged": result.unchanged,
            "review_diagnostics": list(result.diagnostics),
            "legacy_device_map": result.legacy_device_map,
        }
    except ValidationError as exc:
        logger.info(
            "Document extraction segmentation requires review: extraction_id=%s",
            extraction_id,
        )
        return {"success": False, "extraction_id": extraction_id, "requires_review": True, "error": str(exc)}
    except Exception as exc:
        logger.warning(
            "Document extraction segmentation refused or failed: extraction_id=%s error_type=%s",
            extraction_id,
            type(exc).__name__,
        )
        raise self.retry(exc=exc) from exc


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

        # Preserve official publication metadata found in the OCR colophon.
        # Effective date is inferred only when the law explicitly says it
        # enters into force on publication; the session/signature date is not
        # an effective date.
        metadata = extract_publication_metadata(norma.texto_original)
        metadata_fields = []
        if metadata["data_publicacao"] and not norma.data_publicacao:
            norma.data_publicacao = metadata["data_publicacao"]
            metadata_fields.append("data_publicacao")
        if metadata["vigencia_na_publicacao"] and norma.data_publicacao and not norma.data_vigencia:
            norma.data_vigencia = norma.data_publicacao
            metadata_fields.append("data_vigencia")

        # Mark as processing
        norma.status = "segmentation_processing"
        norma.save(update_fields=["status", "updated_at", *metadata_fields])

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
        try:
            validate_hierarchy(hierarchy)
            identities = parsed_device_identities(hierarchy)
            hierarchy_in_order = ordered_hierarchy_rows(hierarchy)
        except ValueError as exc:
            error_msg = str(exc)
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = "ocr_completed"
            norma.save(update_fields=["needs_review", "processing_error", "status", "updated_at"])
            return {"success": False, "error": error_msg, "norma_id": norma_id}

        logger.info(
            f"[Task {task_id}] Found {len(hierarchy)} elements, building hierarchical structure"
        )

        # Reconcile atomically: preserve device PKs and historical FKs across re-segmentation.
        with transaction.atomic():
            norma = Norma.objects.select_for_update().get(pk=norma_id)
            existing_rows = list(
                Dispositivo.objects.select_related("dispositivo_pai")
                .filter(norma=norma)
                .order_by("pk")
            )
            existing_keys: dict[str, Dispositivo] = {}
            existing_key_cache: dict[int, str] = {}

            def existing_key(device: Dispositivo, active: set[int] | None = None) -> str:
                if device.pk in existing_key_cache:
                    return existing_key_cache[device.pk]
                active = set() if active is None else active
                if device.pk in active:
                    raise ValueError(
                        "A hierarquia persistida contém um ciclo; reconciliação cancelada."
                    )
                active.add(device.pk)
                parent = device.dispositivo_pai
                if parent and parent.norma_id != norma.pk:
                    raise ValueError("Dispositivo persistido aponta para pai de outra norma.")
                parent_key = existing_key(parent, active) if parent else "root"
                key = device.structural_key or structural_key(
                    parent_key, device.tipo, device.numero
                )
                active.remove(device.pk)
                existing_key_cache[device.pk] = key
                return key

            for device in existing_rows:
                key = existing_key(device)
                if key in existing_keys:
                    raise ValueError(
                        "Há identidades estruturais duplicadas na norma; reconciliação cancelada."
                    )
                existing_keys[key] = device

            new_keys = [identity[0] for identity in identities.values()]
            if len(new_keys) != len(set(new_keys)):
                raise ValueError("O parser produziu identidades estruturais duplicadas.")

            # Temporarily move ordens above the current range to satisfy the unique constraint
            # while rows are updated/reordered one at a time.
            if existing_rows:
                max_order = max(device.ordem for device in existing_rows)
                Dispositivo.objects.filter(norma=norma).update(
                    ordem=F("ordem") + max_order + len(existing_rows) + 1
                )

            dispositivos_by_index: dict[int, Dispositivo] = {}
            matched_keys: set[str] = set()
            created_count = 0
            updated_count = 0
            stats = {
                "artigo": 0,
                "paragrafo": 0,
                "inciso": 0,
                "alinea": 0,
                "capitulo": 0,
                "secao": 0,
                "titulo": 0,
            }

            for elem in hierarchy_in_order:
                texto_limpo = parser.clean_text(elem["texto"])
                index = elem["index"]
                key, fingerprint = identities[index]
                dispositivo = existing_keys.get(key)
                if dispositivo is None:
                    dispositivo = Dispositivo(norma=norma)
                    created_count += 1
                else:
                    matched_keys.add(key)
                    updated_count += 1
                previous_fingerprint = dispositivo.revision_fingerprint or revision_fingerprint(
                    dispositivo.texto, dispositivo.texto_bruto
                )
                dispositivo.tipo = elem["tipo"]
                dispositivo.numero = elem["numero"]
                dispositivo.texto = texto_limpo
                dispositivo.texto_bruto = elem.get("full_match", "")
                dispositivo.ordem = index
                dispositivo.caminho = elem.get("caminho", "")
                dispositivo.nivel = elem.get("nivel", 0)
                dispositivo.segmentation_confidence = 1.0
                dispositivo.structural_key = key
                dispositivo.revision_fingerprint = fingerprint
                dispositivo.is_active = True
                parent_index = elem.get("parent_index")
                dispositivo.dispositivo_pai = (
                    dispositivos_by_index[parent_index] if parent_index is not None else None
                )
                if dispositivo.pk and previous_fingerprint != fingerprint:
                    dispositivo.embedding = None
                    dispositivo.embedding_model = ""
                    dispositivo.embedding_generated_at = None
                    dispositivo.embedding_revision_fingerprint = ""
                dispositivo.save()
                dispositivos_by_index[index] = dispositivo

                # Count by type
                tipo = elem["tipo"]
                if tipo in stats:
                    stats[tipo] += 1
                else:
                    stats[tipo] = 1

            inactivated_count = 0
            for old_key, device in existing_keys.items():
                if old_key not in matched_keys:
                    device.is_active = False
                    device.save(update_fields=["is_active", "updated_at"])
                    inactivated_count += 1

            # Update norma status
            norma.status = Norma.Status.SEGMENTED
            norma.processing_error = ""
            norma.save(update_fields=["status", "processing_error", "updated_at"])

        processing_time = time.time() - start_time

        logger.info(
            f"[Task {task_id}] Segmentation completed for Norma {norma}: "
            f"{created_count} novos, {updated_count} atualizados, "
            f"{inactivated_count} inativados "
            f"({stats['artigo']} articles, {stats['paragrafo']} paragraphs, "
            f"{stats['inciso']} incisos, {stats['alinea']} alineas) "
            f"in {processing_time:.2f}s"
        )

        _invalidate_rag_cache()
        return {
            "success": True,
            "norma_id": norma_id,
            "norma_str": str(norma),
            "dispositivos_created": created_count,
            "dispositivos_updated": updated_count,
            "dispositivos_inactivated": inactivated_count,
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
