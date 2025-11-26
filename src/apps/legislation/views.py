"""
Views for the legislation app.

Provides web interfaces for viewing consolidated legal texts and
comparing versions.
"""

import logging
import traceback
from typing import Any, Dict
import json

from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.db.models import Q
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings

from .models import Norma, Dispositivo, EventoAlteracao, ChatSession, ChatMessage
from src.processing.rag_service import RAGService

logger = logging.getLogger(__name__)


class NormaListView(ListView):
    """
    List view for consolidated normas.
    
    Displays all normas with status='consolidated' in a table format.
    """
    model = Norma
    template_name = 'legislation/norma_list.html'
    context_object_name = 'normas'
    paginate_by = 20
    
    def get_queryset(self):
        """Filter to show only consolidated normas."""
        queryset = Norma.objects.filter(
            status='consolidated'
        ).order_by('-ano', '-numero')
        
        # Optional search filter
        search_query = self.request.GET.get('q')
        if search_query:
            queryset = queryset.filter(
                Q(ementa__icontains=search_query) |
                Q(numero__icontains=search_query) |
                Q(tipo__icontains=search_query)
            )
        
        return queryset
    
    def get_context_data(self, **kwargs):
        """Add additional context."""
        context = super().get_context_data(**kwargs)
        context['search_query'] = self.request.GET.get('q', '')
        context['total_consolidated'] = Norma.objects.filter(status='consolidated').count()
        return context


class NormaDetailView(DetailView):
    """
    Detail view for a single norma.
    
    Displays the consolidated text and all alteration events affecting
    this norma.
    """
    model = Norma
    template_name = 'legislation/norma_detail.html'
    context_object_name = 'norma'
    
    def get_context_data(self, **kwargs) -> Dict[str, Any]:
        """
        Add alteration events and dispositivos to context.
        """
        context = super().get_context_data(**kwargs)
        norma = self.object
        
        # Get all alteration events affecting this norma
        eventos_recebidos = EventoAlteracao.objects.filter(
            norma_alvo=norma
        ).select_related(
            'dispositivo_fonte',
            'dispositivo_fonte__norma',
            'dispositivo_alvo'
        ).order_by('created_at')
        
        # Get all dispositivos for this norma
        dispositivos = Dispositivo.objects.filter(
            norma=norma
        ).select_related('dispositivo_pai').order_by('ordem')
        
        # Get root dispositivos (for hierarchical display)
        root_dispositivos = dispositivos.filter(dispositivo_pai__isnull=True)
        
        # Statistics
        stats = {
            'total_dispositivos': dispositivos.count(),
            'total_eventos': eventos_recebidos.count(),
            'total_chars': len(norma.texto_consolidado) if norma.texto_consolidado else 0,
            'has_original': bool(norma.texto_original),
            'has_consolidated': bool(norma.texto_consolidado),
        }
        
        context.update({
            'eventos_recebidos': eventos_recebidos,
            'dispositivos': dispositivos,
            'root_dispositivos': root_dispositivos,
            'stats': stats,
        })
        
        return context


def norma_compare_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Compare view showing original vs consolidated text side-by-side.
    
    Args:
        request: HTTP request
        pk: Primary key of the norma
        
    Returns:
        Rendered comparison page
    """
    norma = get_object_or_404(Norma, pk=pk)
    
    # Split texts into lines for comparison
    original_lines = norma.texto_original.split('\n') if norma.texto_original else []
    consolidated_lines = norma.texto_consolidado.split('\n') if norma.texto_consolidado else []
    
    # Get alteration events
    eventos = EventoAlteracao.objects.filter(
        Q(norma_alvo=norma) | Q(dispositivo_fonte__norma=norma)
    ).select_related(
        'dispositivo_fonte',
        'dispositivo_fonte__norma',
        'dispositivo_alvo',
        'norma_alvo'
    ).order_by('created_at')
    
    context = {
        'norma': norma,
        'original_lines': original_lines,
        'consolidated_lines': consolidated_lines,
        'eventos': eventos,
        'original_length': len(original_lines),
        'consolidated_length': len(consolidated_lines),
    }
    
    return render(request, 'legislation/norma_compare.html', context)


def norma_dispositivos_tree_view(request: HttpRequest, pk: int) -> HttpResponse:
    """
    Display dispositivos in a hierarchical tree structure.
    
    Args:
        request: HTTP request
        pk: Primary key of the norma
        
    Returns:
        Rendered tree view page
    """
    norma = get_object_or_404(Norma, pk=pk)
    
    # Get all dispositivos
    dispositivos = Dispositivo.objects.filter(
        norma=norma
    ).select_related('dispositivo_pai').order_by('ordem')
    
    # Build tree structure
    def build_tree(parent_id=None):
        """Recursively build tree structure."""
        children = [d for d in dispositivos if d.dispositivo_pai_id == parent_id]
        tree = []
        for child in children:
            tree.append({
                'dispositivo': child,
                'children': build_tree(child.id)
            })
        return tree
    
    tree = build_tree(None)
    
    context = {
        'norma': norma,
        'tree': tree,
        'total_dispositivos': dispositivos.count(),
    }
    
    return render(request, 'legislation/norma_tree.html', context)


def chatbot_view(request: HttpRequest, session_slug: str = None) -> HttpResponse:
    """
    Chatbot interface for RAG-based legal question answering.
    
    GET: Renders the chat interface
    - /chatbot/ - Nova conversa (welcome state)
    - /chatbot/<slug>/ - Conversa específica (ex: /chatbot/abc123def456)
    
    POST: Processes questions and returns AI-generated answers
    """
    if request.method == 'GET':
        # Get or create active session for authenticated user
        active_session = None
        chat_sessions = []
        current_session_id = None
        
        if request.user.is_authenticated:
            # If session_slug provided, load that specific session
            if session_slug:
                try:
                    active_session = ChatSession.objects.get(slug=session_slug, user=request.user)
                    current_session_id = active_session.id
                    # Mark as active
                    ChatSession.objects.filter(user=request.user, is_active=True).update(is_active=False)
                    active_session.is_active = True
                    active_session.save(update_fields=['is_active'])
                except ChatSession.DoesNotExist:
                    # Invalid slug, redirect to new chat
                    from django.shortcuts import redirect
                    return redirect('legislation:chatbot')
            else:
                # No slug - this is a new conversation
                # Don't load any active session - show welcome state
                active_session = None
                current_session_id = None
            
            # Get recent sessions for sidebar (last 10)
            chat_sessions = ChatSession.objects.filter(
                user=request.user
            ).order_by('-updated_at')[:10]
            
            # Don't create session automatically - only create when user sends first message
            # This matches Gemini behavior: show welcome state until user actually sends something
        else:
            # For anonymous users, create temporary session in session storage
            session_id = request.session.get('temp_chat_session_id')
            if not session_id:
                # Create a temporary session object (not persisted)
                session_id = f"temp_{request.session.session_key}"
                request.session['temp_chat_session_id'] = session_id
        
        # Render chat interface
        context = {
            'page_title': 'Assistente Jurídico - Jurix',
            'total_dispositivos': Dispositivo.objects.filter(embedding__isnull=False).count(),
            'total_normas': Norma.objects.filter(status='consolidated').count(),
            'chat_sessions': chat_sessions,
            'active_session': active_session,
            'current_session_id': current_session_id,
            'current_session_slug': session_slug,
        }
        return render(request, 'legislation/chatbot.html', context)
    
    elif request.method == 'POST':
        # Process question via AJAX
        try:
            # Parse JSON body
            data = json.loads(request.body)
            question = data.get('question', '').strip()
            
            if not question:
                return JsonResponse({
                    'success': False,
                    'error': 'Pergunta vazia'
                }, status=400)
            
            # Get optional parameters
            k = data.get('k', 5)
            model = data.get('model', 'llama3')
            
            logger.info(f"Chatbot question received: '{question[:100]}...'")
            
            # Get session_id from request if regenerating
            session_id = data.get('session_id')
            regenerate = data.get('regenerate', False)
            
            # IMPORTANT: Create session IMMEDIATELY when user sends first message (before processing)
            # This ensures the session appears in history right away
            chat_session = None
            
            if request.user.is_authenticated:
                # Try to get existing session if session_id provided
                if session_id:
                    try:
                        chat_session = ChatSession.objects.get(id=session_id, user=request.user)
                    except ChatSession.DoesNotExist:
                        session_id = None  # Reset if session doesn't exist
                        pass
                
                if not chat_session:
                    chat_session = ChatSession.objects.filter(
                        user=request.user,
                        is_active=True
                    ).order_by('-updated_at').first()
                
                if not chat_session:
                    # Create new session with title from first question IMMEDIATELY
                    title = question[:50] + ('...' if len(question) > 50 else '')
                    # Create session WITHOUT slug first to avoid any database errors
                    chat_session = ChatSession.objects.create(
                        user=request.user,
                        title=title,
                        is_active=True
                    )
                    session_id = chat_session.id
                    
                    # Try to generate and set slug AFTER creation (if field exists)
                    session_slug = None
                    try:
                        if not getattr(chat_session, 'slug', None):
                            slug_value = chat_session.generate_slug()
                            ChatSession.objects.filter(pk=session_id).update(slug=slug_value)
                            chat_session.refresh_from_db()
                            session_slug = chat_session.slug
                        else:
                            session_slug = chat_session.slug
                    except Exception as e:
                        # Slug field doesn't exist or generation failed - ignore
                        logger.debug(f"Could not generate slug for session {session_id}: {e}")
                        pass
                    # Save user message immediately so session appears in history
                    ChatMessage.objects.create(
                        session=chat_session,
                        role='user',
                        content=question
                    )
                    logger.info(f"Created new chat session {session_id} (slug: {session_slug}) for user {request.user.username}")
                else:
                    session_id = chat_session.id
                    # Update session title if it's still the default
                    # Use direct query instead of related manager to avoid errors
                    try:
                        from .models import ChatMessage
                        has_messages = ChatMessage.objects.filter(session_id=session_id).exists()
                        if chat_session.title == 'Nova Conversa' and not has_messages:
                            chat_session.title = question[:50] + ('...' if len(question) > 50 else '')
                            chat_session.save()
                    except Exception as e:
                        logger.debug(f"Could not check messages for session {session_id}: {e}")
                    # Save user message if not regenerating
                    if not regenerate:
                        ChatMessage.objects.create(
                            session=chat_session,
                            role='user',
                            content=question
                        )
            
            # Initialize RAG service
            rag_service = RAGService()
            
            # Generate answer
            response = rag_service.answer_question(
                question=question,
                k=k,
                model=model
            )
            
            # Format sources for frontend
            sources = []
            for source in response.get('sources', []):
                disp = source['dispositivo']
                similarity = source.get('similarity_score', 0.0)
                distance = source.get('distance', 1.0)
                
                # Debug logging
                logger.debug(f"Source similarity: {similarity}, distance: {distance}")
                
                # Ensure similarity is a float and within valid range
                similarity_score = float(similarity) if similarity is not None else 0.0
                similarity_score = max(0.0, min(1.0, similarity_score))
                
                # Get PDF and SAPL URLs from norma
                norma = disp.norma
                pdf_url = norma.pdf_url if norma.pdf_url else None
                sapl_url = norma.sapl_url if norma.sapl_url else None
                
                sources.append({
                    'id': disp.id,
                    'text': disp.texto[:200] + ('...' if len(disp.texto) > 200 else ''),
                    'full_text': disp.texto,
                    'similarity_score': similarity_score,
                    'distance': float(distance) if distance is not None else 1.0,
                    'norma_ref': f"{norma.tipo} {norma.numero}/{norma.ano}",
                    'norma_id': norma.id,
                    'dispositivo_ref': disp.get_full_identifier(),
                    'hierarchy': source.get('context', {}).get('hierarchy', ''),
                    'pdf_url': pdf_url,
                    'sapl_url': sapl_url,
                    'dispositivo_id': disp.id
                })
            
            # Persist assistant message (user message already saved above)
            if request.user.is_authenticated and chat_session:
                # If regenerating, delete last assistant message
                # Use direct query instead of related manager
                if regenerate:
                    try:
                        from .models import ChatMessage
                        last_assistant = ChatMessage.objects.filter(
                            session_id=chat_session.id,
                            role='assistant'
                        ).order_by('-created_at').first()
                        if last_assistant:
                            last_assistant.delete()
                    except Exception as e:
                        logger.debug(f"Could not delete last assistant message: {e}")
                
                # Save assistant message
                ChatMessage.objects.create(
                    session=chat_session,
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
            
            # Get session slug if session exists (safely handle if migration not run)
            session_slug = None
            if chat_session:
                try:
                    session_slug = getattr(chat_session, 'slug', None)
                except AttributeError:
                    pass
            
            return JsonResponse({
                'success': True,
                'answer': response['answer'],
                'sources': sources,
                'confidence': response['confidence'],
                'session_id': session_id,
                'session_slug': session_slug,  # Include slug for URL update
                'metadata': {
                    'model': response.get('model', model),
                    'context_length': response.get('context_length', 0),
                    'sources_count': len(sources)
                }
            })
            
        except json.JSONDecodeError:
            return JsonResponse({
                'success': False,
                'error': 'JSON inválido'
            }, status=400)
        except Exception as e:
            logger.error(f"Error in chatbot POST: {e}", exc_info=True)
            import traceback
            logger.error(f"Traceback: {traceback.format_exc()}")
            return JsonResponse({
                'success': False,
                'error': f'Erro ao processar pergunta: {str(e)}',
                'traceback': traceback.format_exc() if settings.DEBUG else None
            }, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

