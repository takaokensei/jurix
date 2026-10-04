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
from src.processing.document_extraction import extract_pdf_document
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor

from .task_support import _configure_tesseract, _mark_norma_failed

logger = logging.getLogger(__name__)


@shared_task(bind=True, name="ingestion.ocr_pdf_task", max_retries=2, default_retry_delay=120)
def ocr_pdf_task(self, norma_id: int) -> dict[str, Any]:
    """
    Task Celery para extrair texto de PDF usando Tesseract OCR.

    Fluxo:
    1. Busca a norma no banco via ID
    2. Valida se existe PDF baixado (pdf_path)
    3. Converte PDF em imagens (PyMuPDF)
    4. Aplica OCR em cada página (Tesseract)
    5. Salva texto consolidado em texto_original
    6. Atualiza status para 'ocr_completed'

    Args:
        norma_id: ID da norma no banco de dados local

    Returns:
        Dict com estatísticas do OCR:
        {
            'success': bool,
            'norma_id': int,
            'pages_processed': int,
            'total_chars': int,
            'processing_time': float,
            'error': str (se falha)
        }

    Raises:
        Retry automático em caso de falha (2x com backoff de 120s)
    """
    task_id = self.request.id
    start_time = time.time()

    logger.info(f"[Task {task_id}] Iniciando OCR para Norma ID={norma_id}")

    try:
        norma = Norma.objects.get(id=norma_id)

        # Validação: Norma precisa ter PDF baixado
        if not norma.pdf_path or not Path(norma.pdf_path).exists():
            error_msg = f"PDF não encontrado no caminho: {norma.pdf_path}"
            logger.warning(f"[Task {task_id}] {error_msg}")
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.save(update_fields=["needs_review", "processing_error", "updated_at"])
            return {"success": False, "error": error_msg, "norma_id": norma_id}

        # Marcar como processando
        norma.status = "ocr_processing"
        norma.save(update_fields=["status", "updated_at"])

        logger.info(f"[Task {task_id}] Abrindo PDF: {norma.pdf_path}")

        # OCR is selective: native text remains preferred unless an image-backed
        # page has objectively insufficient/corrupt text.
        pdf_document = fitz.open(norma.pdf_path)
        total_pages = len(pdf_document)
        pdf_document.close()

        logger.info(f"[Task {task_id}] PDF tem {total_pages} página(s)")

        max_pages = int(getattr(settings, "SAPL_OCR_MAX_PAGES", 200))
        if total_pages > max_pages:
            pdf_document.close()
            error_msg = (
                f"PDF excede o limite de OCR configurado ({total_pages} páginas > {max_pages})."
            )
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = "pdf_downloaded"
            norma.save(
                update_fields=[
                    "needs_review",
                    "processing_error",
                    "status",
                    "updated_at",
                ]
            )
            logger.warning(
                f"[Task {task_id}] {error_msg} Norma ID={norma_id} marcada para revisão."
            )
            return {
                "success": False,
                "error": error_msg,
                "norma_id": norma_id,
                "pages_processed": 0,
                "total_chars": 0,
                "processing_time": time.time() - start_time,
            }

        _configure_tesseract()
        extraction = extract_pdf_document(
            norma.pdf_path,
            max_pages=max_pages,
            ocr_timeout_seconds=90,
        )
        full_text = extraction["legal_text"]
        methods = extraction["quality"]["page_methods"]
        logger.info(
            "[Task %s] Extração por página: %s nativas, %s OCR, %s ilegíveis",
            task_id,
            methods["native"],
            methods["ocr"],
            methods["unreadable"],
        )

        if not extraction["complete"]:
            error_msg = (
                "Extração documental incompleta; páginas ilegíveis ou vazias: "
                f"{extraction['quality']['unreadable_pages']}"
            )
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = "pdf_downloaded"
            norma.save(update_fields=["needs_review", "processing_error", "status", "updated_at"])
            return {
                "success": False,
                "needs_review": True,
                "error": error_msg,
                "norma_id": norma_id,
                "pages_processed": total_pages,
                "page_methods": methods,
            }

        total_chars = len(full_text)
        processing_time = time.time() - start_time

        if not full_text or total_chars < 50:
            # OCR falhou ou retornou texto muito curto
            error_msg = f"OCR retornou texto insuficiente ({total_chars} chars)"
            logger.warning(f"[Task {task_id}] {error_msg}")
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = "pdf_downloaded"
            # Preserve previously stored text; an empty extraction is never certified.
            norma.save(update_fields=["needs_review", "processing_error", "status", "updated_at"])
            return {"success": False, "needs_review": True, "error": error_msg, "norma_id": norma_id}

        # Salvar texto extraído
        norma.texto_original = full_text
        norma.status = "ocr_completed"
        norma.needs_review = extraction["needs_review"]
        norma.processing_error = ""  # Limpar erros
        norma.save(
            update_fields=["texto_original", "status", "needs_review", "processing_error", "updated_at"]
        )

        logger.info(
            f"[Task {task_id}] OCR concluído com sucesso: Norma {norma} "
            f"({total_pages} páginas, {total_chars} caracteres, {processing_time:.2f}s)"
        )

        return {
            "success": True,
            "norma_id": norma_id,
            "norma_str": str(norma),
            "pages_processed": total_pages,
            "total_chars": total_chars,
            "processing_time": processing_time,
            "page_methods": methods,
            "extraction_sha256": extraction["extraction_sha256"],
            "policy_fingerprint": extraction["policy_fingerprint"],
            "needs_review": extraction["needs_review"],
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} não encontrada no banco de dados"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {"success": False, "error": error_msg, "norma_id": norma_id}

    except Exception as e:
        error_msg = f"Erro crítico no OCR da Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}")

        # Marcar norma com erro
        _mark_norma_failed(norma_id, "Erro OCR", e)

        # Retry se ainda houver tentativas
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=120 * (2**self.request.retries)) from e

        return {"success": False, "error": str(e), "norma_id": norma_id}
