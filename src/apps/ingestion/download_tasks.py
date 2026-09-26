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

from .task_support import _mark_norma_failed

from .task_support import _invalidate_rag_cache

@shared_task(bind=True, name="ingestion.download_pdf_task", max_retries=3, default_retry_delay=60)
def download_pdf_task(self, norma_id: int) -> dict[str, Any]:
    """
    Celery task to download PDF of a specific legal norm asynchronously.

    Fluxo:
    1. Busca a norma no banco via ID
    2. Valida se existe URL de PDF
    3. Baixa o arquivo usando SaplAPIClient
    4. Salva em data/raw/{pk}.pdf
    5. Atualiza status da norma para 'pdf_downloaded'

    Args:
        norma_id: ID da norma no banco de dados local

    Returns:
        Dict com status do download: {'success': bool, 'path': str, 'error': str}

    Raises:
        Retry automático em caso de falha de rede (3x com backoff de 60s)
    """
    task_id = self.request.id
    logger.info(f"[Task {task_id}] Iniciando download de PDF para Norma ID={norma_id}")

    try:
        norma = Norma.objects.get(id=norma_id)

        # Validação: Norma precisa ter URL de PDF
        if not norma.pdf_url:
            logger.warning(f"[Task {task_id}] Norma {norma} não possui URL de PDF")
            norma.needs_review = True
            norma.processing_error = "URL de PDF não disponível no SAPL"
            norma.save(update_fields=["needs_review", "processing_error", "updated_at"])
            return {"success": False, "error": "URL de PDF não disponível", "norma_id": norma_id}

        # Criar diretório de destino (data/raw/)
        output_dir = Path(settings.RAW_DATA_DIR)
        output_dir.mkdir(parents=True, exist_ok=True)

        # Nome do arquivo: {pk_da_norma}.pdf (conforme especificação)
        filename = f"{norma.id}.pdf"
        output_path = output_dir / filename

        logger.debug(f"[Task {task_id}] Baixando PDF de {norma.pdf_url} para {output_path}")

        # Baixar PDF usando SaplAPIClient
        client = SaplAPIClient()
        try:
            success = client.download_pdf(norma.pdf_url, str(output_path))
        finally:
            client.close()

        if success:
            # Atualizar norma com caminho do PDF e status
            norma.pdf_path = str(output_path)
            norma.status = "pdf_downloaded"
            norma.processing_error = ""  # Limpar erros anteriores
            norma.save(update_fields=["pdf_path", "status", "processing_error", "updated_at"])

            logger.info(f"[Task {task_id}] PDF baixado com sucesso: Norma {norma} -> {output_path}")
            return {
                "success": True,
                "path": str(output_path),
                "norma_id": norma_id,
                "norma_str": str(norma),
            }
        else:
            # Marcar para revisão em caso de falha
            norma.needs_review = True
            norma.processing_error = "Falha no download do PDF (HTTP error ou timeout)"
            norma.save(update_fields=["needs_review", "processing_error", "updated_at"])

            logger.error(f"[Task {task_id}] Falha no download do PDF da Norma {norma}")

            # Retry com backoff exponencial
            raise self.retry(
                exc=Exception(f"Download falhou para norma_id={norma_id}"),
                countdown=60 * (2**self.request.retries),
            )

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} não encontrada no banco de dados"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {"success": False, "error": error_msg, "norma_id": norma_id}

    except Exception as e:
        error_msg = f"Erro crítico ao baixar PDF da Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}")

        # Tentar marcar a norma com erro (graceful degradation)
        _mark_norma_failed(norma_id, "Erro crítico", e, set_failed_status=False)

        # Retry
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

        return {"success": False, "error": str(e), "norma_id": norma_id}

def _sapl_payload_hash(payload: dict[str, Any]) -> str:
    """Stable source fingerprint used to make incremental SAPL sync idempotent."""
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

@shared_task(
    bind=True,
    name="ingestion.incremental_sync_sapl_task",
    max_retries=2,
)
def incremental_sync_sapl_task(
    self,
    limit: int = 100,
    tipo: str | None = None,
    ano: int | None = None,
) -> dict[str, Any]:
    """Persisted, resumable SAPL sync with an explicit safe-stop condition."""
    from src.apps.ingestion.sapl_sync import run_incremental_sync

    try:
        result = run_incremental_sync(
            limit=limit,
            tipo=tipo,
            ano=ano,
        )
        if result.get("error") and not result.get("busy"):
            raise RuntimeError(result["error"])
        return result
    except Exception as exc:
        logger.error("Incremental SAPL sync task failed", exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc

@shared_task(
    bind=True,
    name="ingestion.full_sync_sapl_task",
    max_retries=1,
    default_retry_delay=120,
)
def full_sync_sapl_task(
    self,
    limit: int = 100,
) -> dict[str, Any]:
    """Run a complete SAPL scan and flag locally retained records that disappeared."""
    from src.apps.ingestion.sapl_sync import run_full_sync

    try:
        result = run_full_sync(limit=limit)
        if result.get("error") and not result.get("busy"):
            raise RuntimeError(result["error"])
        return result
    except Exception as exc:
        logger.error("Full SAPL sync task failed", exc_info=True)
        raise self.retry(exc=exc, countdown=120) from exc
