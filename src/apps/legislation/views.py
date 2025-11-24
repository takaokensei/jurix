"""
Views for the legislation app.

Provides web interfaces for viewing consolidated legal texts and
comparing versions.
"""

import logging
from typing import Any, Dict
import json

from django.shortcuts import render, get_object_or_404
from django.views.generic import ListView, DetailView
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.db.models import Q
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt

from .models import Norma, Dispositivo, EventoAlteracao
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


def chatbot_view(request: HttpRequest) -> HttpResponse:
    """
    Chatbot interface for RAG-based legal question answering.
    
    GET: Renders the chat interface
    POST: Processes questions and returns AI-generated answers
    """
    if request.method == 'GET':
        # Render chat interface
        context = {
            'page_title': 'Assistente Jurídico - Jurix',
            'total_dispositivos': Dispositivo.objects.filter(embedding__isnull=False).count(),
            'total_normas': Norma.objects.filter(status='consolidated').count(),
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
            return JsonResponse({
                'success': False,
                'error': 'JSON inválido'
            }, status=400)
        except Exception as e:
            logger.error(f"Error in chatbot: {e}", exc_info=True)
            return JsonResponse({
                'success': False,
                'error': f'Erro ao processar pergunta: {str(e)}'
            }, status=500)
    
    return JsonResponse({'error': 'Method not allowed'}, status=405)

