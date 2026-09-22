"""Product-workspace views: assistant, search, collections, history and settings."""

from django.conf import settings
from django.db.models import Count, Prefetch, Q
from django.shortcuts import redirect, render

from src.processing.rag_service import RAGService

from .models import ChatMessage, ChatSession, Norma


def assistente_view(request, session_slug=None):
    """Canonical assistant route; delegates rendering to the existing chat view."""
    from .views import chatbot_view

    return chatbot_view(request, session_slug=session_slug)


def legacy_chatbot_redirect(request):
    """Keep /normas/chatbot/ stable: delegate POST (fallback) to chatbot_view, redirect GET."""
    if request.method != "GET":
        from .views import chatbot_view
        return chatbot_view(request)
    return redirect("workspace:assistant")


def legacy_chatbot_session_redirect(request, session_slug):
    """Keep bookmarked chat session URLs working after the route migration."""
    if request.method != "GET":
        from .views import chatbot_view
        return chatbot_view(request, session_slug=session_slug)
    return redirect("workspace:assistant_session", session_slug=session_slug)


def settings_view(request):
    """Render persisted-by-browser workspace preferences and server-supported models."""
    return render(
        request,
        "legislation/workspace/settings.html",
        {
            "ollama_models": settings.OLLAMA_ALLOWED_MODELS,
            "default_model": settings.OLLAMA_MODEL,
            "norma_count": Norma.objects.filter(status="consolidated").count(),
            "active_nav": "settings",
        },
    )


def legal_search_view(request):
    """Dedicated semantic/legal search surface with lexical fallback."""
    query = request.GET.get("q", "").strip()
    norma_type = request.GET.get("tipo", "").strip()
    year_raw = request.GET.get("ano", "").strip()
    min_similarity_raw = request.GET.get("similaridade", "0.0").strip()

    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None

    try:
        min_similarity = max(0.0, min(float(min_similarity_raw), 1.0))
    except ValueError:
        min_similarity = 0.0

    results = []
    search_mode = "semantic"
    search_error = ""

    if query:
        try:
            results = RAGService().semantic_search(
                query_text=query,
                k=20,
                min_similarity=min_similarity,
            )
            results = [
                result
                for result in results
                if (not norma_type or result["dispositivo"].norma.tipo == norma_type)
                and (not year or result["dispositivo"].norma.ano == year)
            ]
        except Exception:
            search_mode = "lexical"
            search_error = "A busca semântica está temporariamente indisponível; exibindo correspondências textuais."

        if not results and search_mode == "semantic":
            # A zero-result semantic query is still a valid outcome; do not silently
            # substitute a different ranking model in that case.
            pass
        elif search_mode == "lexical":
            queryset = Norma.objects.filter(status="consolidated").filter(
                Q(ementa__icontains=query)
                | Q(numero__icontains=query)
                | Q(tipo__icontains=query)
                | Q(texto_consolidado__icontains=query)
            )
            if norma_type:
                queryset = queryset.filter(tipo=norma_type)
            if year:
                queryset = queryset.filter(ano=year)
            for norma in queryset.order_by("-ano", "-numero")[:20]:
                results.append(
                    {
                        "dispositivo": None,
                        "norma": norma,
                        "similarity_score": None,
                        "hierarchy": "Correspondência textual",
                        "texto": norma.ementa or norma.texto_consolidado[:500],
                    }
                )

    types = Norma.objects.filter(status="consolidated").values_list("tipo", flat=True).distinct().order_by("tipo")
    years = Norma.objects.filter(status="consolidated").values_list("ano", flat=True).distinct().order_by("-ano")

    return render(
        request,
        "legislation/workspace/search.html",
        {
            "query": query,
            "norma_type": norma_type,
            "year": year,
            "min_similarity": min_similarity,
            "results": results,
            "result_count": len(results),
            "search_mode": search_mode,
            "search_error": search_error,
            "types": types,
            "years": years,
            "active_nav": "search",
        },
    )


def collections_view(request):
    """First-class collections surface without fabricating persistence before its model exists."""
    return render(
        request,
        "legislation/workspace/collections.html",
        {
            "norma_count": Norma.objects.filter(status="consolidated").count(),
            "active_nav": "collections",
        },
    )


def history_view(request):
    """Unified history built from the durable chat session/message model."""
    sessions = []
    if request.user.is_authenticated:
        user_messages = Prefetch(
            "messages",
            queryset=ChatMessage.objects.filter(role="user").order_by("created_at"),
            to_attr="history_user_messages",
        )
        sessions = list(
            ChatSession.objects.filter(user=request.user)
            .annotate(message_count=Count("messages"))
            .prefetch_related(user_messages)
            .order_by("-updated_at", "-id")[:100]
        )
        for session in sessions:
            session.primary_query = (
                session.history_user_messages[0].content
                if session.history_user_messages
                else "Sem consulta registrada"
            )

    return render(
        request,
        "legislation/workspace/history.html",
        {
            "sessions": sessions,
            "active_nav": "history",
        },
    )
