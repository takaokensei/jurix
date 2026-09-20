"""
Celery tasks for data ingestion from SAPL API.

Tasks para orquestrar a ingestão assíncrona de normas jurídicas.
"""

import io
import logging
import time
from pathlib import Path
from typing import Any

import fitz  # PyMuPDF
import pytesseract
from celery import shared_task
from django.conf import settings
from django.db import transaction
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
        update_fields = ['needs_review', 'processing_error', 'updated_at']
        if set_failed_status:
            norma.status = 'failed'
            update_fields.append('status')
        norma.save(update_fields=update_fields)
    except Exception:
        logger.warning(f"Could not record failure on Norma ID={norma_id}", exc_info=True)



@shared_task(
    bind=True,
    name='ingestion.ingest_normas_task',
    max_retries=3,
    default_retry_delay=60
)
def ingest_normas_task(
    self,
    limit: int = 50,
    offset: int = 0,
    tipo: str | None = None,
    ano: int | None = None,
    auto_download: bool = False
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
        'task_id': task_id,
        'total_fetched': 0,
        'created': 0,
        'updated': 0,
        'failed': 0,
        'errors': [],
        'download_tasks': []  # IDs das tasks de download disparadas
    }

    client = None

    try:
        # Inicializar cliente SAPL
        client = SaplAPIClient()

        # Buscar normas da API
        logger.info(f"[Task {task_id}] Buscando normas da API SAPL...")
        normas_data = client.fetch_normas(
            limit=limit,
            offset=offset,
            tipo=tipo,
            ano=ano
        )

        stats['total_fetched'] = len(normas_data)
        logger.info(f"[Task {task_id}] {len(normas_data)} normas recuperadas da API")

        # Processar cada norma
        for norma_data in normas_data:
            try:
                result = _process_norma_data(norma_data, auto_download=auto_download)

                if result['created']:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1

                # Registrar task de download se foi disparada
                if 'download_task_id' in result:
                    stats['download_tasks'].append(result['download_task_id'])

            except Exception as e:
                stats['failed'] += 1
                error_msg = f"Norma ID {norma_data.get('id')}: {str(e)}"
                stats['errors'].append(error_msg)
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
        stats['errors'].append(str(e))

        # Retry com backoff exponencial
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) from e

    finally:
        if client:
            client.close()


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
    sapl_id = norma_data.get('id')

    if not sapl_id:
        raise ValueError("Norma sem ID no payload da API")

    # Extrair campos principais
    tipo_dict = norma_data.get('tipo', {})
    tipo = tipo_dict.get('descricao', '') if isinstance(tipo_dict, dict) else str(tipo_dict)

    numero = norma_data.get('numero', '')
    ano = norma_data.get('ano')
    ementa = norma_data.get('ementa', '')
    observacao = norma_data.get('observacao', '')
    texto_integral = norma_data.get('texto_integral', '')

    # Parsear datas (podem vir como string no formato ISO)
    data_publicacao = None
    if norma_data.get('data'):
        data_publicacao = parse_date(norma_data['data'])

    data_vigencia = None
    if norma_data.get('data_vigencia'):
        data_vigencia = parse_date(norma_data['data_vigencia'])

    # URL do PDF (se disponível)
    pdf_url = norma_data.get('texto_integral', '')

    # Montar URL da página no SAPL dinamicamente
    sapl_base_host = getattr(settings, 'SAPL_BASE_URL', 'https://sapl.natal.rn.leg.br/api').rstrip('/')
    if sapl_base_host.endswith('/api'):
        sapl_base_host = sapl_base_host[:-4]
    sapl_url = f"{sapl_base_host}/norma/normajuridica/{sapl_id}/"

    # Preservar status caso a norma já tenha sido processada/consolidada
    existing = Norma.objects.filter(sapl_id=sapl_id).only('status').first()
    preserved_status = 'pending'
    if existing and existing.status in ('consolidated', 'embedded', 'segmented', 'ocr_completed', 'text_extracted'):
        preserved_status = existing.status

    # Criar ou atualizar norma
    norma, created = Norma.objects.update_or_create(
        sapl_id=sapl_id,
        defaults={
            'tipo': tipo,
            'numero': str(numero),
            'ano': ano,
            'ementa': ementa,
            'observacao': observacao,
            'data_publicacao': data_publicacao,
            'data_vigencia': data_vigencia,
            'texto_original': texto_integral,
            'pdf_url': pdf_url,
            'sapl_url': sapl_url,
            'sapl_metadata': norma_data,  # Salvar payload bruto
            'status': preserved_status,  # Não desconsolida normas existentes
        }
    )

    action = "criada" if created else "atualizada"
    logger.info(f"Norma {norma} {action} com sucesso (ID DB={norma.id})")

    result = {
        'created': created,
        'norma_id': norma.id,
        'sapl_id': sapl_id
    }

    # Disparar download automático do PDF (se solicitado)
    if auto_download and pdf_url:
        logger.info(f"Disparando download automático do PDF para Norma ID={norma.id}")
        task = download_pdf_task.delay(norma.id)
        result['download_task_id'] = task.id

    return result


@shared_task(
    bind=True,
    name='ingestion.bulk_ingest_normas_task',
    max_retries=2
)
def bulk_ingest_normas_task(
    self,
    max_normas: int = 500,
    tipo: str | None = None,
    ano: int | None = None,
    page_size: int = 50
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
    task_id = self.request.id
    logger.info(
        f"[Task {task_id}] Iniciando ingestão em massa: "
        f"max_normas={max_normas}, tipo={tipo}, ano={ano}"
    )

    consolidated_stats = {
        'task_id': task_id,
        'dispatched_tasks': [],
        'total_batches': 0,
        'errors': []
    }

    offset = 0

    try:
        while offset < max_normas:
            # Disparar subtask assíncrona para cada página
            subtask = ingest_normas_task.delay(
                limit=page_size,
                offset=offset,
                tipo=tipo,
                ano=ano
            )
            consolidated_stats['dispatched_tasks'].append(subtask.id)
            consolidated_stats['total_batches'] += 1
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
        consolidated_stats['errors'].append(str(e))
        raise self.retry(exc=e) from e


# Celery task for asynchronous PDF download from SAPL API
# Downloads legal norm PDFs and stores them in data/raw/ directory
# Implements retry logic with exponential backoff for network failures
@shared_task(
    bind=True,
    name='ingestion.download_pdf_task',
    max_retries=3,
    default_retry_delay=60
)
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
            norma.processing_error = 'URL de PDF não disponível no SAPL'
            norma.save(update_fields=['needs_review', 'processing_error', 'updated_at'])
            return {'success': False, 'error': 'URL de PDF não disponível', 'norma_id': norma_id}

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
            norma.status = 'pdf_downloaded'
            norma.processing_error = ''  # Limpar erros anteriores
            norma.save(update_fields=['pdf_path', 'status', 'processing_error', 'updated_at'])

            logger.info(
                f"[Task {task_id}] PDF baixado com sucesso: Norma {norma} -> {output_path}"
            )
            return {
                'success': True,
                'path': str(output_path),
                'norma_id': norma_id,
                'norma_str': str(norma)
            }
        else:
            # Marcar para revisão em caso de falha
            norma.needs_review = True
            norma.processing_error = 'Falha no download do PDF (HTTP error ou timeout)'
            norma.save(update_fields=['needs_review', 'processing_error', 'updated_at'])

            logger.error(f"[Task {task_id}] Falha no download do PDF da Norma {norma}")

            # Retry com backoff exponencial
            raise self.retry(
                exc=Exception(f"Download falhou para norma_id={norma_id}"),
                countdown=60 * (2 ** self.request.retries)
            )

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} não encontrada no banco de dados"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {'success': False, 'error': error_msg, 'norma_id': norma_id}

    except Exception as e:
        error_msg = f"Erro crítico ao baixar PDF da Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}")

        # Tentar marcar a norma com erro (graceful degradation)
        _mark_norma_failed(norma_id, "Erro crítico", e, set_failed_status=False)

        # Retry
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) from e

        return {'success': False, 'error': str(e), 'norma_id': norma_id}


@shared_task(
    bind=True,
    name='ingestion.ocr_pdf_task',
    max_retries=2,
    default_retry_delay=120
)
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
            norma.save(update_fields=['needs_review', 'processing_error', 'updated_at'])
            return {
                'success': False,
                'error': error_msg,
                'norma_id': norma_id
            }

        # Marcar como processando
        norma.status = 'ocr_processing'
        norma.save(update_fields=['status', 'updated_at'])

        logger.info(f"[Task {task_id}] Abrindo PDF: {norma.pdf_path}")

        # Abrir PDF com PyMuPDF
        pdf_document = fitz.open(norma.pdf_path)
        total_pages = len(pdf_document)

        logger.info(f"[Task {task_id}] PDF tem {total_pages} página(s)")

        # Extrair texto de cada página
        extracted_text_pages = []

        for page_num in range(total_pages):
            page = pdf_document[page_num]

            # Tentar extrair texto nativo primeiro (mais rápido e preciso)
            native_text = page.get_text("text").strip()

            if native_text and len(native_text) > 100:
                # Texto nativo encontrado (PDF com texto embutido)
                logger.debug(f"[Task {task_id}] Página {page_num + 1}: Usando texto nativo")
                extracted_text_pages.append(native_text)
            else:
                # Texto nativo insuficiente, usar OCR
                logger.debug(f"[Task {task_id}] Página {page_num + 1}: Aplicando OCR com Tesseract")

                # Converter página em imagem (DPI 300 para melhor qualidade)
                pix = page.get_pixmap(dpi=300)
                img_bytes = pix.tobytes("png")
                img = Image.open(io.BytesIO(img_bytes))

                # Aplicar Tesseract OCR (português)
                ocr_text = pytesseract.image_to_string(
                    img,
                    lang='por',
                    config='--psm 6'  # Assume block of text
                )

                extracted_text_pages.append(ocr_text.strip())

        pdf_document.close()

        # Consolidar texto de todas as páginas
        full_text = "\n\n".join([
            f"--- Página {i + 1} ---\n{text}"
            for i, text in enumerate(extracted_text_pages) if text
        ])

        total_chars = len(full_text)
        processing_time = time.time() - start_time

        if not full_text or total_chars < 50:
            # OCR falhou ou retornou texto muito curto
            error_msg = f"OCR retornou texto insuficiente ({total_chars} chars)"
            logger.warning(f"[Task {task_id}] {error_msg}")
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = 'ocr_processing'  # Manter como processando para retry
            norma.save(update_fields=['needs_review', 'processing_error', 'status', 'updated_at'])

            # Retry
            raise self.retry(
                exc=Exception(error_msg),
                countdown=120 * (2 ** self.request.retries)
            )

        # Salvar texto extraído
        norma.texto_original = full_text
        norma.status = 'ocr_completed'
        norma.processing_error = ''  # Limpar erros
        norma.save(update_fields=['texto_original', 'status', 'processing_error', 'updated_at'])

        logger.info(
            f"[Task {task_id}] OCR concluído com sucesso: Norma {norma} "
            f"({total_pages} páginas, {total_chars} caracteres, {processing_time:.2f}s)"
        )

        return {
            'success': True,
            'norma_id': norma_id,
            'norma_str': str(norma),
            'pages_processed': total_pages,
            'total_chars': total_chars,
            'processing_time': processing_time
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} não encontrada no banco de dados"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {'success': False, 'error': error_msg, 'norma_id': norma_id}

    except Exception as e:
        error_msg = f"Erro crítico no OCR da Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}")

        # Marcar norma com erro
        _mark_norma_failed(norma_id, "Erro OCR", e)

        # Retry se ainda houver tentativas
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=120 * (2 ** self.request.retries)) from e

        return {
            'success': False,
            'error': str(e),
            'norma_id': norma_id
        }


@shared_task(
    bind=True,
    name='ingestion.segment_text_task',
    max_retries=2,
    default_retry_delay=60
)
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
            norma.save(update_fields=['needs_review', 'processing_error', 'updated_at'])
            return {
                'success': False,
                'error': error_msg,
                'norma_id': norma_id
            }

        # Mark as processing
        norma.status = 'segmentation_processing'
        norma.save(update_fields=['status', 'updated_at'])

        logger.info(f"[Task {task_id}] Parsing legal text ({len(norma.texto_original)} chars)")

        # Parse text with regex
        parser = LegalTextParser()
        elements = parser.parse_legal_text(norma.texto_original)

        if not elements:
            error_msg = "No legal elements found in text (no articles, paragraphs, etc.)"
            logger.warning(f"[Task {task_id}] {error_msg}")
            norma.needs_review = True
            norma.processing_error = error_msg
            norma.status = 'ocr_completed'  # Revert to previous status
            norma.save(update_fields=['needs_review', 'processing_error', 'status', 'updated_at'])

            return {
                'success': False,
                'error': error_msg,
                'norma_id': norma_id
            }

        # Build hierarchy
        hierarchy = parser.build_hierarchy(elements)

        logger.info(
            f"[Task {task_id}] Found {len(hierarchy)} elements, "
            f"building hierarchical structure"
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
                'artigo': 0,
                'paragrafo': 0,
                'inciso': 0,
                'alinea': 0,
                'capitulo': 0,
                'secao': 0,
                'titulo': 0,
            }

            # First pass: create all dispositivos with materialized caminho/nivel
            for elem in hierarchy:
                texto_limpo = parser.clean_text(elem['texto'])

                dispositivo = Dispositivo(
                    norma=norma,
                    tipo=elem['tipo'],
                    numero=elem['numero'],
                    texto=texto_limpo,
                    texto_bruto=elem.get('full_match', ''),
                    ordem=elem['index'],
                    caminho=elem.get('caminho', ''),
                    nivel=elem.get('nivel', 0),
                    segmentation_confidence=1.0  # High confidence for regex matches
                )

                dispositivos_to_create.append(dispositivo)

                # Count by type
                tipo = elem['tipo']
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
                if elem.get('parent_index') is not None:
                    child_db = db_by_ordem.get(elem['index'])
                    parent_db = db_by_ordem.get(elem['parent_index'])

                    if child_db and parent_db:
                        child_db.dispositivo_pai = parent_db
                        updates_needed.append(child_db)

            # Bulk update parents (if any)
            if updates_needed:
                Dispositivo.objects.bulk_update(updates_needed, ['dispositivo_pai'])
                logger.info(
                    f"[Task {task_id}] Updated {len(updates_needed)} parent relationships in bulk"
                )

            # Update norma status
            norma.status = Norma.Status.SEGMENTED
            norma.processing_error = ''
            norma.save(update_fields=['status', 'processing_error', 'updated_at'])

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
            'success': True,
            'norma_id': norma_id,
            'norma_str': str(norma),
            'dispositivos_created': len(created_dispositivos),
            'articles': stats['artigo'],
            'paragraphs': stats['paragrafo'],
            'incisos': stats['inciso'],
            'alineas': stats['alinea'],
            'processing_time': processing_time
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {'success': False, 'error': error_msg, 'norma_id': norma_id}

    except Exception as e:
        error_msg = f"Critical error in text segmentation for Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}")

        # Mark norma with error
        _mark_norma_failed(norma_id, "Segmentation error", e)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) from e

        return {
            'success': False,
            'error': str(e),
            'norma_id': norma_id
        }


@shared_task(
    bind=True,
    name='ingestion.extract_entities',
    max_retries=3,
    default_retry_delay=60
)
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

    logger.info(
        f"[Task {task_id}] Starting NER entity extraction for Norma ID={norma_id}"
    )

    try:
        # Fetch Norma
        norma = Norma.objects.get(id=norma_id)
        original_status = norma.status

        # Validate status
        if norma.status not in ('segmented', 'entities_extracted', 'consolidated'):
            logger.warning(
                f"[Task {task_id}] Norma {norma} has status '{norma.status}', "
                f"expected 'segmented' or higher. Proceeding anyway."
            )

        # Only update status to entity_extraction if not already consolidated
        if original_status != 'consolidated':
            norma.status = 'entity_extraction'
            norma.save(update_fields=['status', 'updated_at'])

        # Initialize NER extractor
        extractor = LegalNERExtractor()

        # Fetch all dispositivos for this norma
        dispositivos = Dispositivo.objects.filter(norma=norma).select_related('norma')

        if not dispositivos.exists():
            logger.warning(
                f"[Task {task_id}] No dispositivos found for Norma {norma}. "
                f"Cannot extract entities."
            )
            norma.status = original_status if original_status in ('consolidated', 'entities_extracted') else 'segmented'
            norma.save(update_fields=['status', 'updated_at'])
            return {
                'success': True,
                'norma_id': norma_id,
                'events_created': 0,
                'dispositivos_processed': 0,
                'message': 'No dispositivos to process'
            }

        logger.info(
            f"[Task {task_id}] Found {dispositivos.count()} dispositivos to analyze"
        )

        # Extract events from each dispositivo
        events_to_create = []
        dispositivos_with_events = 0

        for dispositivo in dispositivos:
            texto = dispositivo.texto.strip()

            if len(texto) < 20:  # Skip very short texts
                continue

            # Extract events using NER
            extracted_events = extractor.extract_events(
                texto=texto,
                dispositivo_id=dispositivo.id
            )

            if extracted_events:
                dispositivos_with_events += 1

                for event_data in extracted_events:
                    # Try to resolve norma_alvo if we have norma_info
                    norma_alvo = None
                    if event_data.get('norma_referenciada'):
                        norma_info = event_data['norma_referenciada']
                        # Attempt to find the referenced norma
                        norma_alvo = _resolve_norma_reference(
                            tipo=norma_info.get('tipo', ''),
                            numero=norma_info.get('numero', ''),
                            ano=norma_info.get('ano', '')
                        )

                    # Handle self-references (desta Lei)
                    if event_data['referencia_tipo'] == 'self_reference':
                        norma_alvo = norma

                    # Create EventoAlteracao instance
                    evento = EventoAlteracao(
                        dispositivo_fonte=dispositivo,
                        acao=event_data['acao'],
                        target_text=event_data['target_text'][:500],  # Truncate to max_length
                        norma_alvo=norma_alvo,
                        extraction_confidence=event_data['extraction_confidence'],
                        extraction_method=event_data['extraction_method'],
                        referencia_tipo=event_data['referencia_tipo'][:50],
                        referencia_numero=event_data['referencia_numero'][:50],
                    )
                    events_to_create.append(evento)

        # Atomically clean up prior events for this norma and bulk create the new clean events
        with transaction.atomic():
            EventoAlteracao.objects.filter(dispositivo_fonte__norma=norma).delete()
            if events_to_create:
                EventoAlteracao.objects.bulk_create(events_to_create, batch_size=500)

            # Preserve consolidated status if previously consolidated
            norma.status = original_status if original_status == 'consolidated' else 'entities_extracted'
            norma.processing_error = ''
            norma.save(update_fields=['status', 'processing_error', 'updated_at'])

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
            'success': True,
            'norma_id': norma_id,
            'norma_str': str(norma),
            'events_created': len(events_to_create),
            'dispositivos_processed': dispositivos.count(),
            'dispositivos_with_events': dispositivos_with_events,
            'action_stats': action_stats,
            'processing_time': processing_time
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {'success': False, 'error': error_msg, 'norma_id': norma_id}

    except Exception as e:
        error_msg = f"Critical error in entity extraction for Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}", exc_info=True)

        # Mark norma with error
        _mark_norma_failed(norma_id, "Entity extraction error", e)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) from e

        return {
            'success': False,
            'error': str(e),
            'norma_id': norma_id
        }


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
            tipo__iexact=tipo_normalized,
            numero=numero_clean,
            ano=ano_int
        ).first()

        return norma
    except Exception as e:
        logger.debug(f"Could not resolve norma reference: {tipo} {numero}/{ano}: {e}")
        return None


@shared_task(
    bind=True,
    name='ingestion.consolidate_norma',
    max_retries=3,
    default_retry_delay=60
)
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

    logger.info(
        f"[Task {task_id}] Starting consolidation for Norma ID={norma_id}"
    )

    try:
        # Fetch Norma
        norma = Norma.objects.get(id=norma_id)

        # Validate status
        if norma.status != 'entities_extracted':
            logger.warning(
                f"[Task {task_id}] Norma {norma} has status '{norma.status}', "
                f"expected 'entities_extracted'. Proceeding anyway."
            )

        # Update status to processing
        norma.status = 'consolidation'
        norma.save(update_fields=['status', 'updated_at'])

        # Initialize consolidation engine
        engine = ConsolidationEngine(norma)

        # Execute consolidation
        logger.info(f"[Task {task_id}] Executing consolidation algorithm...")
        consolidated_text = engine.consolidate()

        # Get statistics
        stats = engine.get_statistics()

        # Save consolidated text
        norma.texto_consolidado = consolidated_text
        norma.status = 'consolidated'
        norma.processing_error = ''
        update_fields = ['texto_consolidado', 'status', 'processing_error', 'updated_at']
        if stats['needs_review']:
            # Unapplied events or heuristically extracted additions: flag for a
            # human. Never clear the flag here; only a reviewer may do that.
            norma.needs_review = True
            update_fields.append('needs_review')
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
            'success': True,
            'norma_id': norma_id,
            'norma_str': str(norma),
            'total_dispositivos': stats['total_dispositivos'],
            'revoked_count': stats['revoked_count'],
            'altered_count': stats['altered_count'],
            'added_count': stats['added_count'],
            'events_processed': stats['events_processed'],
            'events_applied': stats['events_applied'],
            'events_unresolved': stats['events_unresolved'],
            'needs_review': stats['needs_review'],
            'consolidated_length': len(consolidated_text),
            'processing_time': processing_time
        }

    except Norma.DoesNotExist:
        error_msg = f"Norma ID={norma_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {'success': False, 'error': error_msg, 'norma_id': norma_id}

    except Exception as e:
        error_msg = f"Critical error in consolidation for Norma ID={norma_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}", exc_info=True)

        # Mark norma with error
        _mark_norma_failed(norma_id, "Consolidation error", e)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) from e

        return {
            'success': False,
            'error': str(e),
            'norma_id': norma_id
        }


@shared_task(
    bind=True,
    name='ingestion.generate_embedding',
    max_retries=3,
    default_retry_delay=60
)
def generate_embedding_task(self, dispositivo_id: int, model: str = "nomic-embed-text") -> dict[str, Any]:
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
        dispositivo = Dispositivo.objects.select_related('norma').get(id=dispositivo_id)

        # Prepare text for embedding
        # Include context: norma info + dispositivo hierarchy + content
        norma = dispositivo.norma
        context_parts = [
            f"{norma.tipo} {norma.numero}/{norma.ano}",
            f"{dispositivo.get_full_identifier()}",
            dispositivo.texto
        ]

        # Add parent context for better embeddings
        if dispositivo.dispositivo_pai:
            context_parts.insert(2, f"Contexto: {dispositivo.dispositivo_pai}")

        embedding_text = " | ".join(context_parts)

        logger.debug(
            f"[Task {task_id}] Prepared text of {len(embedding_text)} chars for embedding"
        )

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
                [dispositivo_id]
            )

            # Step 2: Set new embedding (now that field is NULL, dimension mismatch won't occur)
            vector_str = '[' + ','.join(map(str, embedding)) + ']'
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
                [vector_str, model, now, now, dispositivo_id]
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
            'success': True,
            'dispositivo_id': dispositivo_id,
            'dispositivo_str': str(dispositivo),
            'embedding_dimension': len(embedding),
            'model': model,
            'text_length': len(embedding_text),
            'processing_time': processing_time
        }

    except Dispositivo.DoesNotExist:
        error_msg = f"Dispositivo ID={dispositivo_id} not found in database"
        logger.error(f"[Task {task_id}] {error_msg}")
        return {'success': False, 'error': error_msg, 'dispositivo_id': dispositivo_id}

    except Exception as e:
        error_msg = f"Critical error in embedding generation for Dispositivo ID={dispositivo_id}: {str(e)}"
        logger.error(f"[Task {task_id}] {error_msg}", exc_info=True)

        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries)) from e

        return {
            'success': False,
            'error': str(e),
            'dispositivo_id': dispositivo_id
        }

