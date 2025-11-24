"""
Celery tasks for data ingestion from SAPL API.

Tasks para orquestrar a ingestão assíncrona de normas jurídicas.
"""

import logging
import time
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF
import pytesseract
from PIL import Image
import io

from celery import shared_task
from django.conf import settings
from django.utils.dateparse import parse_date

from src.clients.sapl.sapl_client import SaplAPIClient
from src.apps.legislation.models import Norma, Dispositivo, EventoAlteracao
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor

logger = logging.getLogger(__name__)


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
    tipo: Optional[str] = None,
    ano: Optional[int] = None,
    auto_download: bool = False
) -> Dict[str, Any]:
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
        raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        
    finally:
        if client:
            client.close()


def _process_norma_data(norma_data: Dict[str, Any], auto_download: bool = False) -> Dict[str, Any]:
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
    
    # Montar URL da página no SAPL
    sapl_url = f"https://sapl.natal.rn.leg.br/norma/normajuridica/{sapl_id}/"
    
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
            'status': 'pending',  # Pronta para pipeline de processamento
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
    tipo: Optional[str] = None,
    ano: Optional[int] = None,
    page_size: int = 50
) -> Dict[str, Any]:
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
        'total_fetched': 0,
        'created': 0,
        'updated': 0,
        'failed': 0,
        'errors': []
    }
    
    offset = 0
    
    try:
        while consolidated_stats['total_fetched'] < max_normas:
            # Chamar subtask para cada página
            result = ingest_normas_task(
                limit=page_size,
                offset=offset,
                tipo=tipo,
                ano=ano
            )
            
            # Consolidar estatísticas
            consolidated_stats['total_fetched'] += result['total_fetched']
            consolidated_stats['created'] += result['created']
            consolidated_stats['updated'] += result['updated']
            consolidated_stats['failed'] += result['failed']
            consolidated_stats['errors'].extend(result['errors'])
            
            # Se não retornou resultados, fim da paginação
            if result['total_fetched'] == 0:
                break
            
            offset += page_size
            
            logger.info(
                f"[Task {task_id}] Progresso: {consolidated_stats['total_fetched']} "
                f"normas processadas"
            )
        
        logger.info(
            f"[Task {task_id}] Ingestão em massa concluída: "
            f"{consolidated_stats['created']} criadas, "
            f"{consolidated_stats['updated']} atualizadas, "
            f"{consolidated_stats['failed']} falhas"
        )
        
        return consolidated_stats
        
    except Exception as e:
        logger.error(f"[Task {task_id}] Falha na ingestão em massa: {str(e)}")
        consolidated_stats['errors'].append(str(e))
        raise self.retry(exc=e)


@shared_task(
    bind=True,
    name='ingestion.download_pdf_task',
    max_retries=3,
    default_retry_delay=60
)
def download_pdf_task(self, norma_id: int) -> Dict[str, Any]:
    """
    Task Celery para baixar o PDF de uma norma específica de forma assíncrona.
    
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
        try:
            norma = Norma.objects.get(id=norma_id)
            norma.needs_review = True
            norma.processing_error = f"Erro crítico: {str(e)[:200]}"
            norma.save(update_fields=['needs_review', 'processing_error', 'updated_at'])
        except:
            pass  # Se falhar ao salvar, apenas logar
        
        # Retry
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        
        return {'success': False, 'error': str(e), 'norma_id': norma_id}


@shared_task(
    bind=True,
    name='ingestion.ocr_pdf_task',
    max_retries=2,
    default_retry_delay=120
)
def ocr_pdf_task(self, norma_id: int) -> Dict[str, Any]:
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
        try:
            norma = Norma.objects.get(id=norma_id)
            norma.needs_review = True
            norma.processing_error = f"Erro OCR: {str(e)[:200]}"
            norma.status = 'failed'
            norma.save(update_fields=['needs_review', 'processing_error', 'status', 'updated_at'])
        except:
            pass
        
        # Retry se ainda houver tentativas
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=120 * (2 ** self.request.retries))
        
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
def segment_text_task(self, norma_id: int) -> Dict[str, Any]:
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
            error_msg = f"No texto_original found for segmentation"
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
            error_msg = f"No legal elements found in text (no articles, paragraphs, etc.)"
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
        
        # Delete existing dispositivos (in case of reprocessing)
        deleted_count = Dispositivo.objects.filter(norma=norma).delete()[0]
        if deleted_count > 0:
            logger.info(f"[Task {task_id}] Deleted {deleted_count} existing dispositivos")
        
        # Create Dispositivo instances
        dispositivos_to_create = []
        dispositivos_map = {}  # index -> Dispositivo instance
        
        stats = {
            'artigo': 0,
            'paragrafo': 0,
            'inciso': 0,
            'alinea': 0
        }
        
        # First pass: create all dispositivos without parent relationships
        for elem in hierarchy:
            texto_limpo = parser.clean_text(elem['texto'])
            
            dispositivo = Dispositivo(
                norma=norma,
                tipo=elem['tipo'],
                numero=elem['numero'],
                texto=texto_limpo,
                texto_bruto=elem['full_match'],
                ordem=elem['index'],
                segmentation_confidence=1.0  # High confidence for regex matches
            )
            
            dispositivos_map[elem['index']] = dispositivo
            dispositivos_to_create.append(dispositivo)
            
            # Count by type
            tipo = elem['tipo']
            if tipo in stats:
                stats[tipo] += 1
        
        # Bulk create (fast)
        created_dispositivos = Dispositivo.objects.bulk_create(dispositivos_to_create)
        
        logger.info(
            f"[Task {task_id}] Created {len(created_dispositivos)} dispositivos "
            f"(bulk insert)"
        )
        
        # Second pass: set parent relationships
        updates_needed = []
        for elem in hierarchy:
            if elem['parent_index'] is not None:
                child = dispositivos_map[elem['index']]
                parent = dispositivos_map[elem['parent_index']]
                
                # Find the created instance by ordem
                child_db = Dispositivo.objects.get(norma=norma, ordem=elem['index'])
                parent_db = Dispositivo.objects.get(norma=norma, ordem=elem['parent_index'])
                
                child_db.dispositivo_pai = parent_db
                updates_needed.append(child_db)
        
        # Bulk update parents (if any)
        if updates_needed:
            Dispositivo.objects.bulk_update(updates_needed, ['dispositivo_pai'])
            logger.info(
                f"[Task {task_id}] Updated {len(updates_needed)} parent relationships"
            )
        
        # Update norma status
        norma.status = 'segmented'
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
        try:
            norma = Norma.objects.get(id=norma_id)
            norma.needs_review = True
            norma.processing_error = f"Segmentation error: {str(e)[:200]}"
            norma.status = 'failed'
            norma.save(update_fields=['needs_review', 'processing_error', 'status', 'updated_at'])
        except:
            pass
        
        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        
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
def extract_entities_task(self, norma_id: int) -> Dict[str, Any]:
    """
    Extract named entities and alteration events from segmented Norma.
    
    This task:
    1. Loads a Norma with status='segmented'
    2. Iterates through all its Dispositivos
    3. Uses NER (regex + SpaCy) to detect:
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
        
        # Validate status
        if norma.status != 'segmented':
            logger.warning(
                f"[Task {task_id}] Norma {norma} has status '{norma.status}', "
                f"expected 'segmented'. Proceeding anyway."
            )
        
        # Update status to processing
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
            norma.status = 'segmented'
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
        
        # Bulk create all events
        if events_to_create:
            EventoAlteracao.objects.bulk_create(events_to_create, batch_size=500)
            logger.info(
                f"[Task {task_id}] Created {len(events_to_create)} EventoAlteracao instances"
            )
        
        # Update norma status
        norma.status = 'entities_extracted'
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
        try:
            norma = Norma.objects.get(id=norma_id)
            norma.needs_review = True
            norma.processing_error = f"Entity extraction error: {str(e)[:200]}"
            norma.status = 'failed'
            norma.save(update_fields=['needs_review', 'processing_error', 'status', 'updated_at'])
        except:
            pass
        
        # Retry if attempts remaining
        if self.request.retries < self.max_retries:
            raise self.retry(exc=e, countdown=60 * (2 ** self.request.retries))
        
        return {
            'success': False,
            'error': str(e),
            'norma_id': norma_id
        }


def _resolve_norma_reference(tipo: str, numero: str, ano: str) -> Optional[Norma]:
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
