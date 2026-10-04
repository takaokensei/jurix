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
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from PIL import Image

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.clients.sapl.sapl_client import SaplAPIClient
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.event_revision import event_revision_identity
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor

from .task_support import _invalidate_rag_cache, _mark_norma_failed, _resolve_norma_reference

logger = logging.getLogger(__name__)


def _normalize_with_offsets(value: str) -> tuple[str, list[int]]:
    """Collapse whitespace for quote matching while retaining source indexes."""
    normalized = []
    offsets = []
    index = 0
    while index < len(value):
        if value[index].isspace():
            end = index + 1
            while end < len(value) and value[end].isspace():
                end += 1
            normalized.append(" ")
            offsets.append(index)
            index = end
        else:
            normalized.append(value[index])
            offsets.append(index)
            index += 1
    return "".join(normalized), offsets


def _map_event_evidence(dispositivo: Dispositivo, evidence: dict) -> dict:
    result = {"schema_version": 2, "device_evidence": evidence}
    norma = dispositivo.norma
    document = getattr(norma, "documento_base", None)
    extraction = getattr(document, "accepted_extraction", None) if document else None
    if not document or not extraction:
        result["source_status"] = "legacy_source_unlinked"
        return result

    result.update({
        "document_public_id": str(document.public_id),
        "document_key": document.document_key,
        "content_sha256": document.content_sha256,
        "extraction_sha256": extraction.extraction_sha256,
        "structural_key": dispositivo.structural_key,
    })
    segment = extraction.dispositivos_documentais.filter(
        structural_key=dispositivo.structural_key
    ).first()
    if not segment:
        result["source_status"] = "document_device_not_found"
        return result
    source_text = segment.texto
    normalized_source, source_offsets = _normalize_with_offsets(source_text)
    normalized_quote, _ = _normalize_with_offsets(str(evidence.get("quote") or ""))
    positions = []
    cursor = 0
    while normalized_quote and (found := normalized_source.find(normalized_quote, cursor)) >= 0:
        positions.append(found)
        cursor = found + 1
    if len(positions) != 1:
        result["source_status"] = "quote_not_unique_or_not_found"
        return result
    normalized_start = positions[0]
    normalized_end = normalized_start + len(normalized_quote) - 1
    local_start = source_offsets[normalized_start]
    local_end = source_offsets[normalized_end] + 1
    start = segment.start_offset + local_start
    end = segment.start_offset + local_end
    result.update({
        "source_status": "verified_span",
        "source_start_offset": start,
        "source_end_offset": end,
        "source_quote": extraction.legal_text[start:end],
        "page": next(
            (span.get("page") for span in extraction.page_map_json
             if span.get("start", 0) <= start < span.get("end", 0)),
            None,
        ),
    })
    return result


def _persist_embedding_if_current(
    *, dispositivo_id: int, source_revision: str, model: str, embedding: list[float]
) -> bool:
    """Compare-and-set vector persistence; a newer text revision wins every race."""
    vector_str = "[" + ",".join(map(str, embedding)) + "]"
    now = timezone.now()
    with connection.cursor() as cursor:
        cursor.execute(
            """
            UPDATE legislation_dispositivo
            SET embedding = %s::vector,
                embedding_model = %s,
                embedding_generated_at = %s,
                embedding_revision_fingerprint = %s,
                updated_at = %s
            WHERE id = %s AND is_active = TRUE AND revision_fingerprint = %s
            """,
            [vector_str, model, now, source_revision, now, dispositivo_id, source_revision],
        )
        return cursor.rowcount == 1


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
        dispositivos = Dispositivo.objects.filter(norma=norma, is_active=True).select_related(
            "norma"
        )

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
        extracted_rows = []
        occurrences: dict[tuple, int] = {}
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
                        if event_data.get("target_resolution") != "ambiguous_multiple_normas":
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
                    evidence = event_data.get("evidence") or {}
                    evento.evidence_json = _map_event_evidence(dispositivo, evidence)
                    reference = event_data.get("norma_referenciada") or {}
                    evento.target_reference_json = {
                        "schema_version": 1,
                        "kind": "self_reference" if event_data["referencia_tipo"] == "self_reference" else "normative_reference",
                        "type_candidate": reference.get("tipo"),
                        "number_candidate": reference.get("numero"),
                        "year_candidate": reference.get("ano") or None,
                        "structural_type": event_data["referencia_tipo"],
                        "structural_number": event_data["referencia_numero"],
                        "resolution_status": event_data.get("target_resolution", "unresolved"),
                        "jurisdiction_status": "unknown",
                    }
                    occurrence_key = (
                        dispositivo.pk,
                        evento.acao,
                        evento.target_text,
                        evento.referencia_tipo,
                        evento.referencia_numero,
                        norma_alvo.pk if norma_alvo else None,
                    )
                    occurrence = occurrences.get(occurrence_key, 0)
                    occurrences[occurrence_key] = occurrence + 1
                    source_identity = dispositivo.structural_key or f"device:{dispositivo.pk}"
                    fingerprint, provenance = event_revision_identity(
                        source_identity=source_identity,
                        source_revision=dispositivo.revision_fingerprint,
                        action=evento.acao,
                        target_text=evento.target_text,
                        reference_type=evento.referencia_tipo,
                        reference_number=evento.referencia_numero,
                        target_norma_id=norma_alvo.pk if norma_alvo else None,
                        occurrence=occurrence,
                        evidence=evento.evidence_json,
                    )
                    evento.revision_fingerprint = fingerprint
                    evento.provenance_json = provenance
                    extracted_rows.append(evento)

        # Reconcile by evidence revision: keep reviewed IDs and retain superseded events for audit.
        with transaction.atomic():
            norma = Norma.objects.select_for_update().get(pk=norma_id)
            existing_rows = list(
                EventoAlteracao.objects.select_for_update()
                .filter(dispositivo_fonte__norma=norma, is_active=True)
                .select_related("dispositivo_fonte")
                .order_by("pk")
            )
            existing_by_fingerprint: dict[str, list[EventoAlteracao]] = {}
            old_occurrences: dict[tuple, int] = {}
            for existing in existing_rows:
                source = existing.dispositivo_fonte
                occurrence_key = (
                    source.pk,
                    existing.acao,
                    existing.target_text,
                    existing.referencia_tipo,
                    existing.referencia_numero,
                    existing.norma_alvo_id,
                )
                occurrence = old_occurrences.get(occurrence_key, 0)
                old_occurrences[occurrence_key] = occurrence + 1
                was_legacy = not existing.revision_fingerprint
                if was_legacy:
                    fingerprint, provenance = event_revision_identity(
                        source_identity=source.structural_key or f"device:{source.pk}",
                        source_revision=source.revision_fingerprint,
                        action=existing.acao,
                        target_text=existing.target_text,
                        reference_type=existing.referencia_tipo,
                        reference_number=existing.referencia_numero,
                        target_norma_id=existing.norma_alvo_id,
                        occurrence=occurrence,
                        evidence=existing.evidence_json,
                    )
                    existing.revision_fingerprint = fingerprint
                    existing.provenance_json = provenance
                existing_by_fingerprint.setdefault(existing.revision_fingerprint, []).append(
                    existing
                )

            matched_ids: set[int] = set()
            events_created = 0
            events_preserved = 0
            for extracted in extracted_rows:
                matches = existing_by_fingerprint.get(extracted.revision_fingerprint, [])
                existing = next((row for row in matches if row.pk not in matched_ids), None)
                if existing is None:
                    extracted.save(force_insert=True)
                    events_created += 1
                    continue
                matched_ids.add(existing.pk)
                events_preserved += 1
                update_fields = []
                if was_legacy:
                    existing.provenance_json = extracted.provenance_json
                    existing.revision_fingerprint = extracted.revision_fingerprint
                    update_fields.extend(["provenance_json", "revision_fingerprint"])
                if not existing.is_active:
                    existing.is_active = True
                    update_fields.append("is_active")
                if update_fields:
                    existing.save(update_fields=[*update_fields, "updated_at"])

            events_inactivated = 0
            for existing in existing_rows:
                if existing.pk not in matched_ids:
                    existing.is_active = False
                    existing.save(update_fields=["is_active", "updated_at"])
                    events_inactivated += 1

            # Preserve consolidated status if previously consolidated
            norma.status = (
                original_status if original_status == "consolidated" else "entities_extracted"
            )
            norma.processing_error = ""
            norma.save(update_fields=["status", "processing_error", "updated_at"])

        processing_time = time.time() - start_time

        # Calculate statistics by action type
        action_stats = {}
        for evento in extracted_rows:
            action_stats[evento.acao] = action_stats.get(evento.acao, 0) + 1

        logger.info(
            f"[Task {task_id}] Entity extraction completed for Norma {norma}: "
            f"{events_created} new, {events_preserved} preserved, "
            f"{events_inactivated} inactivated from {dispositivos_with_events} dispositivos "
            f"(out of {dispositivos.count()} total) in {processing_time:.2f}s. "
            f"Action distribution: {action_stats}"
        )

        return {
            "success": True,
            "norma_id": norma_id,
            "norma_str": str(norma),
            "events_created": events_created,
            "events_preserved": events_preserved,
            "events_inactivated": events_inactivated,
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
        if not dispositivo.is_active:
            return {
                "success": False,
                "stale_input": True,
                "error": "Dispositivo inativo; embeddings só são gerados para a revisão atual.",
                "dispositivo_id": dispositivo_id,
            }

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

        source_revision = dispositivo.revision_fingerprint

        # Persist only if this exact source revision is still current. Never clear a good
        # previous vector before the compare-and-set succeeds.
        if not _persist_embedding_if_current(
            dispositivo_id=dispositivo_id,
            source_revision=source_revision,
            model=model,
            embedding=embedding,
        ):
            logger.info("Discarded stale embedding result for Dispositivo ID=%s", dispositivo_id)
            return {
                "success": False,
                "stale_input": True,
                "error": "O texto mudou durante a geração; o vetor antigo foi descartado.",
                "dispositivo_id": dispositivo_id,
            }

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
