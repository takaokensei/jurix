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

from src.apps.legislation.models import Norma
from src.clients.sapl.sapl_client import SaplAPIClient
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor

logger = logging.getLogger(__name__)


def _normalize_norma_tipo(value: Any) -> str:
    """Convert SAPL type codes into the public legal type label."""
    raw = str(value or "").strip()
    return {"1": "Lei"}.get(raw, raw)


def _configure_tesseract() -> None:
    """Prefer the native Windows install over Unicode-path shims."""
    configured = getattr(settings, "TESSERACT_CMD", "")
    command = (
        Path(configured) if configured else Path(r"C:\Program Files\Tesseract-OCR\tesseract.exe")
    )
    if not command.exists():
        return
    pytesseract.pytesseract.tesseract_cmd = str(command)
    tessdata = command.parent / "tessdata"
    if tessdata.exists():
        os.environ["TESSDATA_PREFIX"] = str(tessdata)


def _invalidate_rag_cache() -> None:
    """
    Invalidate cached RAG answers/search results after the corpus changed.

    Best effort: a cache problem must never fail an ingestion/consolidation task.
    """
    try:
        get_cache_service().bump_corpus_version()
    except Exception:
        logger.warning("Could not invalidate the RAG cache", exc_info=True)


def _mark_norma_failed(
    norma_id: int, label: str, exc: Exception, *, set_failed_status: bool = True
) -> None:
    """
    Record a task failure on the Norma so it shows up for review.

    Best effort: a problem while recording must never mask the original error, but it
    is logged (the old code used a bare `except: pass`, which also swallowed
    SystemExit/KeyboardInterrupt and left no trace).

    Args:
        set_failed_status: False for steps (download) that keep the norma's status.
    """
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


def _resolve_norma_reference(tipo: str, numero: str, ano: str) -> Norma | None:
    """
    Attempt to resolve a norma reference to an existing Norma in the database.

    Args:
        tipo: Type of norma (Lei, Decreto, etc.)
        numero: Number of the norma
        ano: Year of the norma

    Returns:
        Norma instance if found, None otherwise
    """
    if not tipo or not numero or not ano:
        return None

    try:
        # Normalize tipo for matching
        tipo_normalized = tipo.strip().lower()
        numero_clean = numero.strip()
        ano_int = int(ano)

        # Try exact match
        norma = Norma.objects.filter(
            tipo__iexact=tipo_normalized, numero=numero_clean, ano=ano_int
        ).first()

        return norma
    except Exception as e:
        logger.debug(f"Could not resolve norma reference: {tipo} {numero}/{ano}: {e}")
        return None
