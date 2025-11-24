"""
Celery tasks for data ingestion from SAPL API.

Tasks para orquestrar a ingestão assíncrona de normas jurídicas.
"""

import logging
from typing import Dict, Any, List, Optional
from datetime import datetime
from pathlib import Path

from celery import shared_task
from django.conf import settings
from django.utils.dateparse import parse_date

from src.clients.sapl.sapl_client import SaplAPIClient
from src.apps.legislation.models import Norma

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

