"""
API Views for legislation app.

Provides REST API endpoints for:
- Semantic search
- Norma retrieval
- RAG-based question answering
"""

import logging
import json
from typing import Any, Dict

from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q

from src.apps.legislation.models import Norma, Dispositivo
from src.processing.rag_service import RAGService

logger = logging.getLogger(__name__)


@require_http_methods(["GET"])
def semantic_search_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for semantic search using pgvector.
    
    GET /api/v1/search/semantic/?query=<text>&k=<int>&norma_id=<int>
    
    Query Parameters:
        - query (required): Search query text
        - k (optional): Number of results (default: 10, max: 50)
        - norma_id (optional): Filter by specific norma ID
        - min_similarity (optional): Minimum similarity score (0-1)
    
    Returns:
        JSON response with:
        - success: bool
        - query: str (original query)
        - results: list of dispositivos with similarity scores
        - count: int
        - metadata: dict with search parameters
    """
    try:
        # Extract query parameters
        query_text = request.GET.get('query', '').strip()
        
        if not query_text:
            return JsonResponse({
                'success': False,
                'error': 'Query parameter is required',
                'example': '/api/v1/search/semantic/?query=mudanca+de+zoneamento'
            }, status=400)
        
        # Parse optional parameters
        try:
            k = min(int(request.GET.get('k', 10)), 50)  # Max 50 results
        except ValueError:
            k = 10
        
        norma_id = request.GET.get('norma_id')
        if norma_id:
            try:
                norma_id = int(norma_id)
            except ValueError:
                norma_id = None
        
        try:
            min_similarity = float(request.GET.get('min_similarity', 0.0))
            min_similarity = max(0.0, min(1.0, min_similarity))  # Clamp to [0, 1]
        except ValueError:
            min_similarity = 0.0
        
        logger.info(
            f"API semantic search request: query='{query_text[:50]}...', "
            f"k={k}, norma_id={norma_id}, min_similarity={min_similarity}"
        )
        
        # Perform semantic search
        rag_service = RAGService()
        results = rag_service.semantic_search(
            query_text=query_text,
            k=k,
            norma_id=norma_id,
            min_similarity=min_similarity
        )
        
        # Format results for JSON response
        formatted_results = []
        for result in results:
            disp = result['dispositivo']
            
            formatted_results.append({
                'id': disp.id,
                'tipo': disp.tipo,
                'numero': disp.numero,
                'texto': disp.texto,
                'ordem': disp.ordem,
                'similarity_score': result['similarity_score'],
                'distance': result['distance'],
                'norma': {
                    'id': disp.norma.id,
                    'tipo': disp.norma.tipo,
                    'numero': disp.norma.numero,
                    'ano': disp.norma.ano,
                    'ementa': disp.norma.ementa[:200] if disp.norma.ementa else None,
                },
                'hierarchy': result['context']['hierarchy'],
                'parent': result['context']['parent'],
                'embedding_model': result['embedding_model'],
            })
        
        return JsonResponse({
            'success': True,
            'query': query_text,
            'results': formatted_results,
            'count': len(formatted_results),
            'metadata': {
                'k': k,
                'norma_id': norma_id,
                'min_similarity': min_similarity,
                'model': 'nomic-embed-text'
            }
        })
        
    except Exception as e:
        logger.error(f"Error in semantic search API: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET", "POST"])
@csrf_exempt
def rag_answer_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for RAG-based question answering.
    
    GET/POST /api/v1/search/answer/
    
    Parameters:
        - question (required): The legal question to answer
        - k (optional): Number of context items to retrieve (default: 5)
        - model (optional): LLM model to use (default: llama3)
    
    Returns:
        JSON response with:
        - success: bool
        - question: str
        - answer: str (generated answer)
        - sources: list of source dispositivos
        - confidence: float (0-1)
        - metadata: dict
    """
    try:
        # Handle both GET and POST
        if request.method == 'POST':
            try:
                data = json.loads(request.body)
                question = data.get('question', '').strip()
                k = data.get('k', 5)
                model = data.get('model', 'llama3')
            except json.JSONDecodeError:
                return JsonResponse({
                    'success': False,
                    'error': 'Invalid JSON in request body'
                }, status=400)
        else:  # GET
            question = request.GET.get('question', '').strip()
            k = int(request.GET.get('k', 5))
            model = request.GET.get('model', 'llama3')
        
        if not question:
            return JsonResponse({
                'success': False,
                'error': 'Question parameter is required',
                'example': '/api/v1/search/answer/?question=Como+funciona+o+IPTU+em+Natal'
            }, status=400)
        
        logger.info(f"RAG answer request: question='{question[:50]}...', k={k}, model={model}")
        
        # Generate answer using RAG
        rag_service = RAGService()
        response = rag_service.answer_question(
            question=question,
            k=k,
            model=model
        )
        
        # Format sources for JSON
        formatted_sources = []
        for source in response.get('sources', []):
            disp = source['dispositivo']
            formatted_sources.append({
                'id': disp.id,
                'text': disp.texto,
                'similarity_score': source['similarity_score'],
                'norma': f"{disp.norma.tipo} {disp.norma.numero}/{disp.norma.ano}",
                'hierarchy': source['context']['hierarchy']
            })
        
        return JsonResponse({
            'success': True,
            'question': question,
            'answer': response['answer'],
            'sources': formatted_sources,
            'confidence': response['confidence'],
            'metadata': {
                'k': k,
                'model': response.get('model', model),
                'context_length': response.get('context_length', 0)
            }
        })
        
    except Exception as e:
        logger.error(f"Error in RAG answer API: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def norma_list_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint to list normas.
    
    GET /api/v1/normas/?status=<status>&page=<int>&page_size=<int>
    
    Query Parameters:
        - status (optional): Filter by status (e.g., 'consolidated')
        - page (optional): Page number (default: 1)
        - page_size (optional): Items per page (default: 20, max: 100)
        - search (optional): Search in ementa, numero, tipo
    
    Returns:
        JSON response with paginated normas
    """
    try:
        # Extract parameters
        status = request.GET.get('status')
        search = request.GET.get('search', '').strip()
        
        try:
            page = max(int(request.GET.get('page', 1)), 1)
            page_size = min(int(request.GET.get('page_size', 20)), 100)
        except ValueError:
            page = 1
            page_size = 20
        
        # Build queryset
        queryset = Norma.objects.all()
        
        if status:
            queryset = queryset.filter(status=status)
        
        if search:
            queryset = queryset.filter(
                Q(ementa__icontains=search) |
                Q(numero__icontains=search) |
                Q(tipo__icontains=search)
            )
        
        queryset = queryset.order_by('-ano', '-numero')
        
        # Paginate
        paginator = Paginator(queryset, page_size)
        page_obj = paginator.get_page(page)
        
        # Format results
        normas = []
        for norma in page_obj:
            normas.append({
                'id': norma.id,
                'tipo': norma.tipo,
                'numero': norma.numero,
                'ano': norma.ano,
                'ementa': norma.ementa[:200] if norma.ementa else None,
                'status': norma.status,
                'data_publicacao': norma.data_publicacao.isoformat() if norma.data_publicacao else None,
                'url': f'/normas/{norma.id}/'
            })
        
        return JsonResponse({
            'success': True,
            'normas': normas,
            'pagination': {
                'page': page,
                'page_size': page_size,
                'total_pages': paginator.num_pages,
                'total_count': paginator.count,
                'has_next': page_obj.has_next(),
                'has_previous': page_obj.has_previous()
            }
        })
        
    except Exception as e:
        logger.error(f"Error in norma list API: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


@require_http_methods(["GET"])
def norma_detail_api(request: HttpRequest, pk: int) -> JsonResponse:
    """
    API endpoint to get norma details.
    
    GET /api/v1/normas/<id>/
    
    Returns:
        JSON response with norma details and dispositivos
    """
    try:
        norma = Norma.objects.get(pk=pk)
        
        # Get dispositivos
        dispositivos = Dispositivo.objects.filter(norma=norma).order_by('ordem')
        
        dispositivos_data = []
        for disp in dispositivos:
            dispositivos_data.append({
                'id': disp.id,
                'tipo': disp.tipo,
                'numero': disp.numero,
                'texto': disp.texto,
                'ordem': disp.ordem,
                'has_embedding': disp.embedding is not None,
            })
        
        return JsonResponse({
            'success': True,
            'norma': {
                'id': norma.id,
                'tipo': norma.tipo,
                'numero': norma.numero,
                'ano': norma.ano,
                'ementa': norma.ementa,
                'status': norma.status,
                'data_publicacao': norma.data_publicacao.isoformat() if norma.data_publicacao else None,
                'data_vigencia': norma.data_vigencia.isoformat() if norma.data_vigencia else None,
                'texto_consolidado': norma.texto_consolidado if norma.texto_consolidado else None,
            },
            'dispositivos': dispositivos_data,
            'count': len(dispositivos_data)
        })
        
    except Norma.DoesNotExist:
        return JsonResponse({
            'success': False,
            'error': f'Norma with ID {pk} not found'
        }, status=404)
    except Exception as e:
        logger.error(f"Error in norma detail API: {e}", exc_info=True)
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)

