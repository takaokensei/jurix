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
    ano: Optional[int] = None
) -> Dict[str, Any]:
    """
    Task Celery para ingestão de normas da API SAPL.
    
    Responsabilidades:
    1. Buscar metadados de normas via SaplAPIClient
    2. Criar/Atualizar registros no modelo Norma
    3. Salvar metadados brutos para auditoria
    4. Reportar estatísticas de ingestão
    
    Args:
        limit: Número máximo de normas a buscar
        offset: Offset para paginação
        tipo: Filtro por tipo de norma
        ano: Filtro por ano
        
    Returns:
        Dicionário com estatísticas da ingestão
    """
    task_id = self.request.id
    logger.info(
        f"[Task {task_id}] Iniciando ingestão: "
        f"limit={limit}, offset={offset}, tipo={tipo}, ano={ano}"
    )
    
    stats = {
        'task_id': task_id,
        'total_fetched': 0,
        'created': 0,
        'updated': 0,
        'failed': 0,
        'errors': []
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
                result = _process_norma_data(norma_data)
                
                if result['created']:
                    stats['created'] += 1
                else:
                    stats['updated'] += 1
                    
            except Exception as e:
                stats['failed'] += 1
                error_msg = f"Norma ID {norma_data.get('id')}: {str(e)}"
                stats['errors'].append(error_msg)
                logger.error(f"[Task {task_id}] Erro ao processar norma: {error_msg}")
        
        logger.info(
            f"[Task {task_id}] Ingestão concluída: "
            f"{stats['created']} criadas, {stats['updated']} atualizadas, "
            f"{stats['failed']} falhas"
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


def _process_norma_data(norma_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Processa dados brutos de uma norma e cria/atualiza o registro no banco.
    
    Args:
        norma_data: Dicionário com dados da API SAPL
        
    Returns:
        Dicionário com resultado do processamento {'created': bool, 'norma_id': int}
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
    
    return {
        'created': created,
        'norma_id': norma.id,
        'sapl_id': sapl_id
    }


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


@shared_task(name='ingestion.download_pdf_task')
def download_pdf_task(norma_id: int) -> Dict[str, Any]:
    """
    Task para baixar o PDF de uma norma específica.
    
    Args:
        norma_id: ID da norma no banco de dados local
        
    Returns:
        Status do download
    """
    logger.info(f"Iniciando download de PDF para Norma ID={norma_id}")
    
    try:
        norma = Norma.objects.get(id=norma_id)
        
        if not norma.pdf_url:
            logger.warning(f"Norma {norma} não possui URL de PDF")
            return {'success': False, 'error': 'URL de PDF não disponível'}
        
        # Criar diretório de destino
        output_dir = Path(settings.RAW_DATA_DIR) / 'pdfs'
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Nome do arquivo: Lei_123_2020.pdf
        filename = f"{norma.tipo.replace(' ', '_')}_{norma.numero}_{norma.ano}.pdf"
        output_path = output_dir / filename
        
        # Baixar PDF
        client = SaplAPIClient()
        success = client.download_pdf(norma.pdf_url, str(output_path))
        client.close()
        
        if success:
            # Atualizar norma com caminho do PDF
            norma.pdf_path = str(output_path)
            norma.status = 'pdf_downloaded'
            norma.save(update_fields=['pdf_path', 'status', 'updated_at'])
            
            logger.info(f"PDF baixado com sucesso para Norma {norma}")
            return {'success': True, 'path': str(output_path)}
        else:
            norma.needs_review = True
            norma.processing_error = 'Falha no download do PDF'
            norma.save(update_fields=['needs_review', 'processing_error', 'updated_at'])
            
            return {'success': False, 'error': 'Falha no download'}
        
    except Norma.DoesNotExist:
        logger.error(f"Norma ID={norma_id} não encontrada")
        return {'success': False, 'error': 'Norma não encontrada'}
    except Exception as e:
        logger.error(f"Erro ao baixar PDF da Norma ID={norma_id}: {str(e)}")
        return {'success': False, 'error': str(e)}

