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

from .download_tasks import download_pdf_task

from .task_support import _invalidate_rag_cache, _normalize_norma_tipo

@shared_task(name="ingestion.cleanup_chat_attachments")
def cleanup_chat_attachments():
    from src.apps.legislation.attachment_service import cleanup_expired_attachments

    return cleanup_expired_attachments()

@shared_task(bind=True, name="ingestion.ingest_normas_task", max_retries=3, default_retry_delay=60)
def ingest_normas_task(
    self,
    limit: int = 50,
    offset: int = 0,
    tipo: str | None = None,
    ano: int | None = None,
    auto_download: bool = False,
) -> dict[str, Any]:
    """
    Task Celery para ingestão de normas da API SAPL.

    Responsabilidades:
    1. Buscar metadados de normas via SaplAPIClient
    2. Criar/Atualizar registros no modelo Norma
    3. Salvar metadados brutos para auditoria
    4. Opcionalmente disparar download de PDFs de forma assíncrona
    5. Reportar estatísticas de ingestão

    Args:
        limit: Número máximo de normas a buscar
        offset: Offset para paginação
        tipo: Filtro por tipo de norma
        ano: Filtro por ano
        auto_download: Se True, dispara automaticamente download_pdf_task para cada norma

    Returns:
        Dicionário com estatísticas da ingestão
    """
    task_id = self.request.id
    logger.info(
        f"[Task {task_id}] Iniciando ingestão: "
        f"limit={limit}, offset={offset}, tipo={tipo}, ano={ano}, auto_download={auto_download}"
    )

    stats = {
        "task_id": task_id,
        "total_fetched": 0,
        "created": 0,
        "updated": 0,
        "failed": 0,
        "errors": [],
        "download_tasks": [],  # IDs das tasks de download disparadas
    }

    client = None

    try:
        # Inicializar cliente SAPL
        client = SaplAPIClient()

        # Buscar normas da API
        logger.info(f"[Task {task_id}] Buscando normas da API SAPL...")
        normas_data = client.fetch_normas(limit=limit, offset=offset, tipo=tipo, ano=ano)

        stats["total_fetched"] = len(normas_data)
        logger.info(f"[Task {task_id}] {len(normas_data)} normas recuperadas da API")

        # Processar cada norma
        for norma_data in normas_data:
            try:
                result = _process_norma_data(norma_data, auto_download=auto_download)

                if result["created"]:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1

                # Registrar task de download se foi disparada
                if "download_task_id" in result:
                    stats["download_tasks"].append(result["download_task_id"])

            except Exception as e:
                stats["failed"] += 1
                error_msg = f"Norma ID {norma_data.get('id')}: {str(e)}"
                stats["errors"].append(error_msg)
                logger.error(f"[Task {task_id}] Erro ao processar norma: {error_msg}")

        logger.info(
            f"[Task {task_id}] Ingestão concluída: "
            f"{stats['created']} criadas, {stats['updated']} atualizadas, "
            f"{stats['failed']} falhas, "
            f"{len(stats['download_tasks'])} downloads disparados"
        )

        return stats

    except Exception as e:
        logger.error(f"[Task {task_id}] Falha crítica na ingestão: {str(e)}")
        stats["errors"].append(str(e))

        # Retry com backoff exponencial
        raise self.retry(exc=e, countdown=60 * (2**self.request.retries)) from e

    finally:
        if client:
            client.close()

@transaction.atomic
def _process_norma_data(norma_data: dict[str, Any], auto_download: bool = False) -> dict[str, Any]:
    """
    Processa dados brutos de uma norma e cria/atualiza o registro no banco.

    Args:
        norma_data: Dicionário com dados da API SAPL
        auto_download: Se True, dispara automaticamente a task de download do PDF

    Returns:
        Dicionário com resultado do processamento:
        {
            'created': bool,
            'norma_id': int,
            'sapl_id': int,
            'download_task_id': str (se auto_download=True)
        }
    """
    sapl_id = norma_data.get("id")

    if not sapl_id:
        raise ValueError("Norma sem ID no payload da API")

    # Extrair campos principais
    tipo_dict = norma_data.get("tipo", {})
    tipo_value = tipo_dict.get("descricao", "") if isinstance(tipo_dict, dict) else tipo_dict
    tipo = _normalize_norma_tipo(tipo_value)

    numero = norma_data.get("numero", "")
    ano = norma_data.get("ano")
    ementa = norma_data.get("ementa", "")
    observacao = norma_data.get("observacao", "")

    # Parsear datas (podem vir como string no formato ISO)
    data_publicacao = None
    if norma_data.get("data"):
        data_publicacao = parse_date(norma_data["data"])

    data_vigencia = None
    if norma_data.get("data_vigencia"):
        data_vigencia = parse_date(norma_data["data_vigencia"])

    # URL do PDF (se disponível)
    pdf_url = norma_data.get("texto_integral", "")

    # Montar URL da página no SAPL dinamicamente
    sapl_base_host = getattr(settings, "SAPL_BASE_URL", "https://sapl.natal.rn.leg.br/api").rstrip(
        "/"
    )
    if sapl_base_host.endswith("/api"):
        sapl_base_host = sapl_base_host[:-4]
    from src.apps.legislation.source_urls import canonical_sapl_url

    sapl_url = canonical_sapl_url(sapl_id=sapl_id) or f"{sapl_base_host}/norma/{sapl_id}/"

    # Preservar status caso a norma já tenha sido processada/consolidada
    existing = (
        Norma.objects.select_for_update().filter(sapl_id=sapl_id).only("status", "pdf_url").first()
    )
    preserved_status = "pending"
    if existing and existing.status in (
        "consolidated",
        "embedded",
        "segmented",
        "ocr_completed",
        "text_extracted",
    ):
        preserved_status = existing.status

    # Criar ou atualizar norma
    norma, created = Norma.objects.update_or_create(
        sapl_id=sapl_id,
        defaults={
            "tipo": tipo,
            "numero": str(numero),
            "ano": ano,
            "ementa": ementa,
            "observacao": observacao,
            "data_publicacao": data_publicacao,
            "data_vigencia": data_vigencia,
            "pdf_url": pdf_url,
            "sapl_url": sapl_url,
            "sapl_metadata": norma_data,  # Salvar payload bruto
            "status": preserved_status,  # Não desconsolida normas existentes
        },
    )

    if existing and existing.pdf_url != pdf_url:
        norma.status = "pending"
        norma.needs_review = True
        norma.processing_error = "Documento de origem alterado; requer reprocessamento."
        norma.texto_consolidado = ""
        norma.save(
            update_fields=[
                "status",
                "needs_review",
                "processing_error",
                "texto_consolidado",
                "updated_at",
            ]
        )
        Dispositivo.objects.filter(norma=norma).update(embedding=None)
        transaction.on_commit(_invalidate_rag_cache)

    action = "criada" if created else "atualizada"
    logger.info(f"Norma {norma} {action} com sucesso (ID DB={norma.id})")

    result = {"created": created, "norma_id": norma.id, "sapl_id": sapl_id}

    # Disparar download automático do PDF (se solicitado)
    if auto_download and pdf_url:
        logger.info(f"Disparando download automático do PDF para Norma ID={norma.id}")
        task = download_pdf_task.delay(norma.id)
        result["download_task_id"] = task.id

    return result

@shared_task(bind=True, name="ingestion.bulk_ingest_normas_task", max_retries=2)
def bulk_ingest_normas_task(
    self,
    max_normas: int = 500,
    tipo: str | None = None,
    ano: int | None = None,
    page_size: int = 50,
) -> dict[str, Any]:
    """
    Task para ingestão em massa com paginação automática.

    Args:
        max_normas: Número máximo de normas a ingerir
        tipo: Filtro por tipo
        ano: Filtro por ano
        page_size: Tamanho de cada página

    Returns:
        Estatísticas consolidadas
    """
    if isinstance(page_size, bool) or not isinstance(page_size, int) or page_size <= 0:
        raise ValueError("page_size must be a positive integer")
    if (
        isinstance(max_normas, bool)
        or not isinstance(max_normas, int)
        or not 1 <= max_normas <= 5000
    ):
        raise ValueError("max_normas must be between 1 and 5000")
    page_size = min(page_size, 100)
    task_id = self.request.id
    logger.info(
        f"[Task {task_id}] Iniciando ingestão em massa: "
        f"max_normas={max_normas}, tipo={tipo}, ano={ano}"
    )

    consolidated_stats = {
        "task_id": task_id,
        "dispatched_tasks": [],
        "total_batches": 0,
        "errors": [],
    }

    offset = 0

    try:
        while offset < max_normas:
            # Disparar subtask assíncrona para cada página
            subtask = ingest_normas_task.apply_async(
                kwargs={
                    "limit": min(page_size, max_normas - offset),
                    "offset": offset,
                    "tipo": tipo,
                    "ano": ano,
                }
            )
            consolidated_stats["dispatched_tasks"].append(subtask.id)
            consolidated_stats["total_batches"] += 1
            offset += page_size

            logger.info(
                f"[Task {task_id}] Disparada subtask assíncrona {subtask.id} (offset={offset})"
            )

        logger.info(
            f"[Task {task_id}] Disparo em massa concluído: "
            f"{consolidated_stats['total_batches']} tarefas Celery enfileiradas."
        )

        return consolidated_stats

    except Exception as e:
        logger.error(f"[Task {task_id}] Falha na ingestão em massa: {str(e)}")
        consolidated_stats["errors"].append(str(e))
        raise self.retry(exc=e) from e

@shared_task(
    bind=True,
    name="ingestion.ingest_sapl_corpus_task",
    max_retries=2,
)
def ingest_sapl_corpus_task(
    self,
    max_normas: int = 300,
    ano_inicio: int | None = None,
    ano_fim: int | None = None,
    auto_download: bool = False,
) -> dict[str, Any]:
    """Ingest a bounded municipal SAPL corpus without relying on broken offset pagination."""
    if isinstance(max_normas, bool) or not 1 <= max_normas <= 5000:
        raise ValueError("max_normas must be between 1 and 5000")
    task_id = self.request.id
    client = SaplAPIClient()
    stats = {
        "task_id": task_id,
        "requested": max_normas,
        "fetched": 0,
        "created": 0,
        "updated": 0,
        "failed": 0,
        "download_tasks": [],
        "errors": [],
    }
    try:
        normas_data = client.fetch_normas_for_corpus(
            target=max_normas,
            ano_inicio=ano_inicio,
            ano_fim=ano_fim,
        )
        stats["fetched"] = len(normas_data)
        for norma_data in normas_data:
            try:
                result = _process_norma_data(norma_data, auto_download=auto_download)
                if result["created"]:
                    stats["created"] += 1
                else:
                    stats["updated"] += 1
                if result.get("download_task_id"):
                    stats["download_tasks"].append(result["download_task_id"])
            except Exception as exc:
                stats["failed"] += 1
                stats["errors"].append(f"Norma ID {norma_data.get('id')}: {exc}")
                logger.exception("Falha ao ingerir norma SAPL durante corpus boundado")
        return stats
    except Exception as exc:
        logger.error("Falha crítica na ingestão do corpus SAPL: %s", exc, exc_info=True)
        raise self.retry(exc=exc, countdown=60 * (2**self.request.retries)) from exc
    finally:
        client.close()
