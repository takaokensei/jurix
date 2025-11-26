"""
API Views for legislation app.

Provides REST API endpoints for:
- Semantic search
- Norma retrieval
- RAG-based question answering
"""

import logging
import json
import traceback
from typing import Any, Dict

from django.http import JsonResponse, HttpRequest
from django.views.decorators.http import require_http_methods
from django.conf import settings
from django.views.decorators.csrf import csrf_exempt
from django.core.paginator import Paginator
from django.db.models import Q

from src.apps.legislation.models import Norma, Dispositivo, ChatSession, ChatMessage
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


@csrf_exempt
@require_http_methods(["GET", "POST"])
def chat_sessions_api(request: HttpRequest) -> JsonResponse:
    """
    API endpoint for chat sessions management.
    
    GET /api/v1/chat/sessions/ - List all sessions for authenticated user
    POST /api/v1/chat/sessions/ - Create new session
    """
    if not request.user.is_authenticated:
        return JsonResponse({
            'success': False,
            'error': 'Authentication required'
        }, status=401)
    
    try:
        if request.method == 'GET':
            # Safely get limit parameter
            try:
                limit = min(int(request.GET.get('limit', 20)), 100)
            except (ValueError, TypeError):
                limit = 20
            
            # Query sessions with error handling
            try:
                # Use select_related to avoid N+1 queries, but don't select slug if it doesn't exist
                sessions = ChatSession.objects.filter(user=request.user).order_by('-updated_at')[:limit]
                # Force evaluation of queryset to catch any database errors early
                list(sessions)  # This will trigger the query and catch any errors
            except Exception as e:
                logger.error(f"Error querying ChatSession: {e}", exc_info=True)
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                return JsonResponse({
                    'success': False,
                    'error': f'Database error: {str(e)}',
                    'traceback': traceback.format_exc() if settings.DEBUG else None
                }, status=500)
            
            sessions_data = []
            for session in sessions:
                try:
                    # Get basic fields first (these should always exist)
                    session_id = session.id
                    session_title = getattr(session, 'title', None) or 'Conversa sem título'
                    session_is_active = getattr(session, 'is_active', False)
                    
                    # Safely get timestamps
                    session_created = None
                    session_updated = None
                    try:
                        if hasattr(session, 'created_at') and session.created_at:
                            session_created = session.created_at.isoformat()
                    except (AttributeError, Exception):
                        pass
                    try:
                        if hasattr(session, 'updated_at') and session.updated_at:
                            session_updated = session.updated_at.isoformat()
                    except (AttributeError, Exception):
                        pass
                    
                    # Safely get slug (may not exist if migration not run yet)
                    session_slug = None
                    try:
                        session_slug = getattr(session, 'slug', None)
                    except (AttributeError, Exception):
                        pass
                    
                    # Safely get message preview - wrap in try/except
                    latest_preview = ''
                    try:
                        # Use direct query instead of method to avoid any issues
                        from .models import ChatMessage
                        first_msg = ChatMessage.objects.filter(
                            session_id=session_id,
                            role='user'
                        ).order_by('created_at').first()
                        if first_msg:
                            latest_preview = first_msg.content[:50] + ('...' if len(first_msg.content) > 50 else '')
                    except Exception as e:
                        logger.debug(f"Could not get message preview for session {session_id}: {e}")
                        pass
                    
                    # Safely get message count
                    message_count = 0
                    try:
                        from .models import ChatMessage
                        message_count = ChatMessage.objects.filter(session_id=session_id).count()
                    except Exception as e:
                        logger.debug(f"Could not get message count for session {session_id}: {e}")
                        pass
                    
                    sessions_data.append({
                        'id': session_id,
                        'title': session_title,
                        'slug': session_slug,  # May be None if migration not run
                        'is_active': session_is_active,
                        'created_at': session_created,
                        'updated_at': session_updated,
                        'message_count': message_count,
                        'latest_message_preview': latest_preview
                    })
                except Exception as e:
                    # Skip this session if there's an error, log and continue
                    logger.error(f"Error processing session {getattr(session, 'id', 'unknown')}: {e}", exc_info=True)
                    continue
            
            return JsonResponse({'success': True, 'sessions': sessions_data, 'count': len(sessions_data)})
        
        elif request.method == 'POST':
            data = json.loads(request.body) if request.body else {}
            title = data.get('title', 'Nova Conversa')
            
            ChatSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
            session = ChatSession.objects.create(user=request.user, title=title[:200], is_active=True)
            
            # Safely get created_at
            session_created = None
            try:
                if hasattr(session, 'created_at') and session.created_at:
                    session_created = session.created_at.isoformat()
            except Exception:
                pass
            
            return JsonResponse({
                'success': True,
                'session': {
                    'id': session.id,
                    'title': session.title,
                    'is_active': session.is_active,
                    'created_at': session_created
                }
            }, status=201)
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in chat sessions API: {e}", exc_info=True)
        import traceback
        logger.error(f"Traceback: {traceback.format_exc()}")
        return JsonResponse({
            'success': False, 
            'error': str(e),
            'traceback': traceback.format_exc() if settings.DEBUG else None
        }, status=500)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def chat_session_detail_api(request: HttpRequest, session_id: int) -> JsonResponse:
    """API endpoint for single chat session operations."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Session not found'}, status=404)
    
    try:
        if request.method == 'GET':
            # Optimize: Load only last 25 messages for better UX (avoid loading hundreds of messages)
            # This is a good balance between showing context and performance
            limit = 25  # Last 25 messages is optimal for UX (shows recent context without lag)
            
            # Use direct query instead of related manager to avoid errors
            total_messages = 0
            messages = []
            try:
                total_messages = ChatMessage.objects.filter(session_id=session.id).count()
                # Get last N messages (most recent first, then reverse for chronological order)
                messages_queryset = ChatMessage.objects.filter(session_id=session.id).order_by('-created_at')[:limit]
                # Force evaluation and reverse
                messages = list(reversed(list(messages_queryset)))  # Reverse to show chronologically
            except Exception as e:
                logger.error(f"Error querying messages for session {session.id}: {e}", exc_info=True)
                import traceback
                logger.error(f"Traceback: {traceback.format_exc()}")
                total_messages = 0
                messages = []
            
            messages_data = []
            for msg in messages:
                try:
                    # Safely get created_at
                    msg_created = None
                    try:
                        if hasattr(msg, 'created_at') and msg.created_at:
                            msg_created = msg.created_at.isoformat()
                    except Exception:
                        pass
                    
                    messages_data.append({
                        'id': msg.id,
                        'role': msg.role,
                        'content': msg.content,
                        'sources': msg.sources_json if msg.role == 'assistant' else [],
                        'metadata': msg.metadata_json if msg.role == 'assistant' else {},
                        'created_at': msg_created
                    })
                except Exception as e:
                    logger.warning(f"Error processing message {getattr(msg, 'id', 'unknown')}: {e}")
                    continue
            
            # Safely get slug (may not exist if migration not run yet)
            session_slug = None
            try:
                session_slug = getattr(session, 'slug', None)
            except AttributeError:
                pass
            
            # Safely get timestamps with proper error handling
            session_created = None
            session_updated = None
            try:
                if hasattr(session, 'created_at'):
                    created_at_value = getattr(session, 'created_at', None)
                    if created_at_value:
                        session_created = created_at_value.isoformat()
            except (AttributeError, Exception) as e:
                logger.debug(f"Could not get created_at for session {session.id}: {e}")
                pass
            try:
                if hasattr(session, 'updated_at'):
                    updated_at_value = getattr(session, 'updated_at', None)
                    if updated_at_value:
                        session_updated = updated_at_value.isoformat()
            except (AttributeError, Exception) as e:
                logger.debug(f"Could not get updated_at for session {session.id}: {e}")
                pass
            
            return JsonResponse({
                'success': True,
                'session': {
                    'id': session.id,
                    'title': session.title,
                    'slug': session_slug,  # May be None if migration not run
                    'is_active': session.is_active,
                    'created_at': session_created,
                    'updated_at': session_updated,
                },
                'messages': messages_data,
                'count': len(messages_data),
                'total_count': total_messages,  # Total messages in session
                'has_more': total_messages > limit  # Indicates if there are older messages
            })
        
        elif request.method == 'DELETE':
            session.delete()
            return JsonResponse({'success': True, 'message': 'Session deleted'})
    
    except Exception as e:
        logger.error(f"Error in chat session detail API: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def chat_session_regenerate_api(request: HttpRequest, session_id: int) -> JsonResponse:
    """API endpoint to regenerate the last assistant response."""
    if not request.user.is_authenticated:
        return JsonResponse({'success': False, 'error': 'Authentication required'}, status=401)
    
    try:
        session = ChatSession.objects.get(id=session_id, user=request.user)
    except ChatSession.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Session not found'}, status=404)
    
    try:
        last_user_msg = session.messages.filter(role='user').order_by('-created_at').first()
        if not last_user_msg:
            return JsonResponse({'success': False, 'error': 'No user message found to regenerate'}, status=400)
        
        last_assistant = session.messages.filter(role='assistant').order_by('-created_at').first()
        if last_assistant:
            last_assistant.delete()
        
        data = json.loads(request.body) if request.body else {}
        k = data.get('k', 5)
        model = data.get('model', 'llama3')
        
        rag_service = RAGService()
        response = rag_service.answer_question(question=last_user_msg.content, k=k, model=model)
        
        sources = []
        for source in response.get('sources', []):
            disp = source['dispositivo']
            similarity = source.get('similarity_score', 0.0)
            similarity_score = max(0.0, min(1.0, float(similarity) if similarity is not None else 0.0))
            norma = disp.norma
            
            sources.append({
                'id': disp.id,
                'text': disp.texto[:200] + ('...' if len(disp.texto) > 200 else ''),
                'full_text': disp.texto,
                'similarity_score': similarity_score,
                'distance': float(source.get('distance', 1.0)),
                'norma_ref': f"{norma.tipo} {norma.numero}/{norma.ano}",
                'norma_id': norma.id,
                'dispositivo_ref': disp.get_full_identifier(),
                'hierarchy': source.get('context', {}).get('hierarchy', ''),
                'pdf_url': norma.pdf_url if norma.pdf_url else None,
                'sapl_url': norma.sapl_url if norma.sapl_url else None,
                'dispositivo_id': disp.id
            })
        
        ChatMessage.objects.create(
            session=session,
            role='assistant',
            content=response['answer'],
            sources_json=sources,
            metadata_json={
                'model': response.get('model', model),
                'confidence': response.get('confidence', 0.0),
                'context_length': response.get('context_length', 0),
                'sources_count': len(sources)
            }
        )
        
        return JsonResponse({
            'success': True,
            'answer': response['answer'],
            'sources': sources,
            'confidence': response['confidence'],
            'metadata': {
                'model': response.get('model', model),
                'context_length': response.get('context_length', 0),
                'sources_count': len(sources)
            }
        })
    
    except json.JSONDecodeError:
        return JsonResponse({'success': False, 'error': 'Invalid JSON'}, status=400)
    except Exception as e:
        logger.error(f"Error in chat session regenerate API: {e}", exc_info=True)
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

