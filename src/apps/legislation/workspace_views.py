"""Product-workspace views: assistant, search, collections, history and settings."""

import logging
import math
import re
from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Count, Prefetch, Q
from django.shortcuts import redirect, render
from django.utils.html import conditional_escape, mark_safe

from src.processing.rag_service import RAGService

from .models import ChatMessage, ChatSession, Collection, Norma

logger = logging.getLogger(__name__)


def _highlight_search_text(text, query):
    """Escape a result snippet and emphasize the user's exact search terms."""
    value = str(text or "")[:320]
    terms = [re.escape(part) for part in query.split() if len(part) >= 2]
    if not value or not terms:
        return conditional_escape(value)
    pattern = re.compile("(" + "|".join(terms) + ")", re.IGNORECASE)
    chunks = pattern.split(value)
    rendered = []
    for index, chunk in enumerate(chunks):
        escaped = conditional_escape(chunk)
        rendered.append(f"<mark>{escaped}</mark>" if index % 2 else escaped)
    return mark_safe("".join(rendered))


_HISTORY_STOPWORDS = {"para", "como", "sobre", "entre", "pela", "pelo", "uma", "que", "qual", "quais", "com", "dos", "das", "artigo", "art", "lei"}


def _history_tokens(value):
    return [token.casefold() for token in re.findall(r"[\wÀ-ÿ]{2,}", str(value or "")) if token.casefold() not in _HISTORY_STOPWORDS]


def _rank_history(sessions, query):
    """Rank matching sessions by weighted bag-of-words relevance, not recency alone."""
    query_terms = list(dict.fromkeys(_history_tokens(query)))
    if not query_terms:
        return sessions
    tokenized = []
    for session in sessions:
        title_tokens = _history_tokens(session.title)
        body_tokens = []
        for message in session.history_messages:
            body_tokens.extend(_history_tokens(str(message.content or "")[:3000]))
        tokenized.append((session, Counter(title_tokens), Counter(body_tokens), len(body_tokens)))
    doc_freq = {term: sum(1 for _, title, body, _ in tokenized if title[term] or body[term]) for term in query_terms}
    total = max(len(tokenized), 1)
    scored = []
    for session, title, body, length in tokenized:
        score = 0.0
        for term in query_terms:
            idf = math.log(1 + (total - doc_freq[term] + 0.5) / (doc_freq[term] + 0.5))
            frequency = body[term]
            body_score = frequency * 2.2 / (frequency + 1.2 * (0.25 + 0.75 * length / 700))
            score += idf * (title[term] * 2.8 + body_score)
        if score:
            scored.append((score, session.updated_at, session))
    return [row[2] for row in sorted(scored, key=lambda row: (row[0], row[1]), reverse=True)]


def _relevance_label(score):
    if score is None:
        return "Correspondência textual"
    value = max(0.0, min(1.0, float(score)))
    if value >= 0.8:
        return "Alta correspondência"
    if value >= 0.6:
        return "Boa correspondência"
    if value >= 0.4:
        return "Correspondência parcial"
    return "Baixa correspondência"


def _tipo_label(value):
    mapping = {
        "1": "Lei",
        "2": "Lei Complementar",
        "3": "Decreto",
        "4": "Resolução",
        "5": "Emenda à Lei Orgânica",
        "6": "Portaria",
    }
    text = str(value or "").strip()
    return mapping.get(text, "Lei" if text.isdigit() else (text or "Lei"))


def _deduplicate_search_results(results, limit=20):
    """Keep the strongest evidence row for each norm in the search surface.

    The vector search operates on devices, so a single norm can otherwise occupy
    several result slots.  The UI is a norm-oriented search surface; retaining
    the first (already ranked) hit gives the user one explainable result while
    preserving the best matching device as its evidence excerpt.
    """
    unique = []
    seen_normas = set()
    for result in results:
        norma = result.get("norma")
        if norma is None:
            dispositivo = result.get("dispositivo")
            norma = getattr(dispositivo, "norma", None)
        key = getattr(norma, "pk", None)
        if key is None:
            # Keep malformed/lexical rows visible rather than silently dropping
            # them; normal semantic rows always have a norm primary key.
            unique.append(result)
            continue
        if key in seen_normas:
            continue
        seen_normas.add(key)
        unique.append(result)
        if len(unique) >= limit:
            break
    return unique


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

    if len(query) > 200:
        search_error = "Busca muito longa (máximo de 200 caracteres)."
        search_mode = "não executada"

    if query and len(query) <= 200:
        try:
            retrieval = RAGService().semantic_search(
                query_text=query,
                # Retrieve a wider candidate set because device-level hits are
                # collapsed to one result per norm below.
                k=50,
                min_similarity=min_similarity,
                norma_type=norma_type or None,
                year=year,
                include_metadata=True,
            )
            results = retrieval["results"]
            search_mode = retrieval["mode"]
            if search_mode == "unavailable":
                search_mode = "lexical"
                search_error = (
                    "A busca semântica está temporariamente indisponível; "
                    "exibindo correspondências textuais."
                )
            results = [
                {**result, "relevance_label": _relevance_label(result.get("similarity_score"))}
                for result in results
            ]
            results = _deduplicate_search_results(results)
        except Exception:
            logger.warning(
                "Semantic legal search failed; falling back to lexical search",
                exc_info=True,
                extra={"query_length": len(query), "year": year, "norma_type": norma_type},
            )
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
                        "relevance_label": "Correspondência textual",
                        "hierarchy": "Correspondência textual",
                        "texto": norma.ementa or norma.texto_consolidado[:500],
                    }
                )
            results = _deduplicate_search_results(results)

    types = (
        Norma.objects.filter(status="consolidated")
        .values_list("tipo", flat=True)
        .distinct()
        .order_by("tipo")
    )
    years = (
        Norma.objects.filter(status="consolidated")
        .values_list("ano", flat=True)
        .distinct()
        .order_by("-ano")
    )

    type_options = []
    seen_labels = set()
    for value in types:
        label = _tipo_label(value)
        if label not in seen_labels:
            seen_labels.add(label)
            type_options.append({"value": value, "label": label})

    for result in results:
        source_text = result.get("texto")
        if not source_text and result.get("dispositivo"):
            source_text = result["dispositivo"].texto
        result["highlighted_text"] = _highlight_search_text(source_text, query)

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
            "types": type_options,
            "years": years,
            "active_nav": "search",
        },
    )


def collections_view(request):
    """List and create authenticated collections without fake client-only state."""
    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.info(request, "Entre para criar coleções persistentes.")
            return redirect("workspace:collections")
        name = request.POST.get("name", "").strip()
        description = request.POST.get("description", "").strip()
        if not name:
            messages.error(request, "Informe um nome para a coleção.")
        else:
            collection, created = Collection.objects.get_or_create(
                user=request.user, name=name, defaults={"description": description}
            )
            if not created and description and collection.description != description:
                collection.description = description
                collection.save(update_fields=["description", "updated_at"])
            messages.success(request, "Coleção criada." if created else "Coleção atualizada.")
        return redirect("workspace:collections")

    collections = []
    if request.user.is_authenticated:
        collections = list(
            Collection.objects.filter(user=request.user)
            .annotate(norma_count=Count("normas"))
            .order_by("-updated_at", "name")
        )
    return render(
        request,
        "legislation/workspace/collections.html",
        {
            "norma_count": Norma.objects.filter(status="consolidated").count(),
            "collections": collections,
            "active_nav": "collections",
        },
    )


def collection_detail_view(request, pk):
    """View and mutate a collection, always scoped to the authenticated owner."""
    if not request.user.is_authenticated:
        messages.info(request, "Entre para acessar suas coleções.")
        return redirect("workspace:collections")
    collection = (
        Collection.objects.filter(user=request.user)
        .prefetch_related("normas")
        .filter(pk=pk)
        .first()
    )
    if collection is None:
        from django.http import Http404

        raise Http404
    if request.method == "POST":
        norma_id = request.POST.get("norma_id")
        action = request.POST.get("action")
        norma = Norma.objects.filter(pk=norma_id, status="consolidated").first()
        if norma is None or action not in {"add", "remove"}:
            messages.error(request, "Não foi possível atualizar esta coleção.")
        elif action == "add":
            collection.normas.add(norma)
            messages.success(request, "Norma adicionada à coleção.")
        else:
            collection.normas.remove(norma)
            messages.success(request, "Norma removida da coleção.")
        return redirect("workspace:collection_detail", pk=collection.pk)
    return render(
        request,
        "legislation/workspace/collection_detail.html",
        {"collection": collection, "active_nav": "collections"},
    )


def history_view(request):
    """Unified history built from the durable chat session/message model."""
    sessions = []
    page_obj = None
    query = str(request.GET.get("q", "")).strip()[:120]
    if request.user.is_authenticated:
        history_messages = Prefetch(
            "messages",
            queryset=ChatMessage.objects.filter(role__in=("user", "assistant")).only("session_id", "role", "content", "created_at").order_by("-created_at")[:20],
            to_attr="history_messages",
        )
        try:
            page_number = max(int(request.GET.get("page", 1)), 1)
        except (TypeError, ValueError):
            page_number = 1
        queryset = ChatSession.objects.filter(user=request.user)
        if query:
            terms = _history_tokens(query)
            matches = Q(title__icontains=query)
            for term in terms[:8]:
                matches |= Q(title__icontains=term) | Q(messages__content__icontains=term)
            queryset = queryset.filter(matches).distinct()
        candidates = list(
            queryset
            .annotate(message_count=Count("messages", distinct=True))
            .prefetch_related(history_messages)
            .order_by("-updated_at", "-id")[:500]
        )
        if query:
            candidates = _rank_history(candidates, query)
        paginator = Paginator(candidates, 20)
        page_obj = paginator.get_page(page_number)
        sessions = list(page_obj)
        for session in sessions:
            recent_messages = sorted(session.history_messages, key=lambda message: message.created_at)
            first_user = next((m for m in recent_messages if m.role == "user"), None)
            first_answer = next((m for m in recent_messages if m.role == "assistant"), None)
            session.primary_query = first_answer.content if first_answer else (first_user.content if first_user else "Sem consulta registrada")

    return render(
        request,
        "legislation/workspace/history.html",
        {
            "sessions": sessions,
            "history_page": page_obj,
            "active_nav": "history",
            "history_query": query,
        },
    )
