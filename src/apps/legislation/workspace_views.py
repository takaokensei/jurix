"""Product-workspace views: assistant, search, collections, history and settings."""

import logging
import math
import re
from collections import Counter

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.html import conditional_escape, mark_safe
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from src.apps.legislation.document_models import DocumentoNormativo
from src.clients.sapl.sapl_types import resolve_norma_type_display
from src.processing.normative_reference import (
    canonical_type,
    normalize_number,
    parse_normative_references,
)
from src.processing.rag_service import RAGService

from .models import ChatMessage, ChatSession, Collection, Dispositivo, Norma, NormaTopic, Topic
from .norma_queries import consolidated_normas_for_product

logger = logging.getLogger(__name__)


@require_http_methods(["GET", "POST"])
def workspace_login_view(request):
    """Sign in administrator-provisioned accounts without enabling open signup."""
    requested_next = (
        request.POST.get("next")
        if request.method == "POST"
        else request.GET.get("next", "")
    )
    if request.user.is_authenticated:
        return redirect(_safe_login_destination(request, requested_next))

    form = AuthenticationForm(request, data=request.POST or None)
    if request.method == "POST" and form.is_valid():
        auth_login(request, form.get_user())
        return redirect(_safe_login_destination(request, requested_next))

    return render(
        request,
        "legislation/workspace/login.html",
        {"form": form, "next": requested_next},
        status=200,
    )


def _safe_login_destination(request, candidate):
    if candidate and url_has_allowed_host_and_scheme(
        candidate, allowed_hosts={request.get_host()}, require_https=request.is_secure()
    ):
        return candidate
    return reverse("workspace:assistant")


@require_POST
def workspace_logout_view(request):
    auth_logout(request)
    return redirect("workspace:assistant")


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


_HISTORY_STOPWORDS = {
    "para",
    "como",
    "sobre",
    "entre",
    "pela",
    "pelo",
    "uma",
    "que",
    "qual",
    "quais",
    "com",
    "dos",
    "das",
    "artigo",
    "art",
    "lei",
}


def _history_tokens(value):
    return [
        token.casefold()
        for token in re.findall(r"[\wÀ-ÿ]{2,}", str(value or ""))
        if token.casefold() not in _HISTORY_STOPWORDS
    ]


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
    doc_freq = {
        term: sum(1 for _, title, body, _ in tokenized if title[term] or body[term])
        for term in query_terms
    }
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
    return resolve_norma_type_display(value)


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


def _exclude_synthetic_search_results(results):
    """Keep seeded QA norms out of user-facing legal search results."""
    visible = []
    for result in results:
        norma = result.get("norma")
        if norma is None:
            dispositivo = result.get("dispositivo")
            norma = getattr(dispositivo, "norma", None)
        identity = getattr(norma, "identity_json", None)
        if isinstance(identity, dict) and identity.get("synthetic_fixture") is True:
            continue
        visible.append(result)
    return visible


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
    archive_review_count = _archive_review_count()
    return render(
        request,
        "legislation/workspace/settings.html",
        {
            "ollama_models": settings.OLLAMA_ALLOWED_MODELS,
            "default_model": settings.OLLAMA_MODEL,
            "norma_count": consolidated_normas_for_product().count(),
            "archive_review_count": archive_review_count,
            "archive_assistant_enabled": (
                archive_review_count > 0
                and getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
            ),
            "active_nav": "settings",
        },
    )


def _archive_review_count():
    """Count local PDF candidates only when the separate archive surface is enabled."""
    if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
        return 0
    return DocumentoNormativo.objects.filter(
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        norma__isnull=True,
        review_status__in=(
            DocumentoNormativo.ReviewStatus.PENDING,
            DocumentoNormativo.ReviewStatus.IN_REVIEW,
        ),
    ).count()


def _exact_normative_search_results(reference, norma_type, year):
    """Resolve an explicit typed law/year before running semantic retrieval."""
    if reference is None or reference.year is None:
        return None
    if year is not None and year != reference.year:
        return []
    selected_type = canonical_type(_tipo_label(norma_type)) if norma_type else ""
    if selected_type and selected_type != reference.type_key:
        return []

    digits = normalize_number(reference.number)
    if not digits:
        return []
    groups = []
    first_group_size = len(digits) % 3 or 3
    groups.append(digits[:first_group_size])
    groups.extend(digits[index : index + 3] for index in range(first_group_size, len(digits), 3))
    number_forms = {digits, ".".join(groups)}

    candidates = consolidated_normas_for_product().filter(
        status="consolidated", ano=reference.year, numero__in=number_forms
    ).order_by("pk")
    norms = [
        norma
        for norma in candidates
        if canonical_type(norma.get_tipo_display_name()) == reference.type_key
    ]
    if not norms:
        return []

    if reference.article:
        article_number = normalize_number(reference.article)
        devices = Dispositivo.objects.filter(
            norma_id__in=[norma.pk for norma in norms], tipo="artigo", is_active=True
        ).select_related("norma").order_by("ordem", "pk")
        device = next(
            (item for item in devices if normalize_number(item.numero) == article_number), None
        )
        if device is None:
            return []
        return [
            {
                "dispositivo": device,
                "norma": device.norma,
                "similarity_score": None,
                "relevance_label": "Dispositivo identificado",
                "hierarchy": "Referência normativa exata",
                "texto": device.texto,
            }
        ]

    norma = norms[0]
    excerpt = norma.ementa or (
        "Norma identificada pela referência exata. Consulte a ficha para os dispositivos e metadados."
    )
    return [
        {
            "dispositivo": None,
            "norma": norma,
            "similarity_score": None,
            "relevance_label": "Norma identificada",
            "hierarchy": "Referência normativa exata",
            "texto": excerpt,
        }
    ]


def legal_search_view(request):
    """Dedicated semantic/legal search surface with lexical fallback."""
    query = request.GET.get("q", "").strip()
    norma_type = request.GET.get("tipo", "").strip()
    year_raw = request.GET.get("ano", "").strip()
    min_similarity_raw = request.GET.get("similaridade", "0.0").strip()
    topic_code = request.GET.get("tema", "").strip()[:64]

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
    empty_state_title = "Nenhuma correspondência semântica encontrada."
    empty_state_description = (
        "Tente um termo mais amplo ou reduza o limiar. Para localizar uma norma específica "
        "por número ou ementa, use a busca direta no acervo."
    )

    if len(query) > 200:
        search_error = "Busca muito longa (máximo de 200 caracteres)."
        search_mode = "não executada"

    if query and len(query) <= 200:
        references = parse_normative_references(query)
        exact_reference = references[0] if len(references) == 1 else None
        exact_results = _exact_normative_search_results(exact_reference, norma_type, year)
        if exact_results is not None:
            results = exact_results
            search_mode = "lexical"
            if not results:
                search_error = (
                    "Referência normativa exata não localizada no acervo municipal. "
                    "Confira o tipo, o número e o ano informados."
                )
                empty_state_title = "Norma não encontrada no acervo"
                empty_state_description = (
                    "Não há uma norma com essa referência exata no acervo municipal. "
                    "Confira o tipo, o número e o ano ou pesquise por um assunto relacionado."
                )
        else:
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
                queryset = consolidated_normas_for_product().filter(
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

    topic_options = list(Topic.objects.filter(active=True).order_by("label").values("code", "label"))
    topic_label = ""
    if topic_code:
        topic = Topic.objects.filter(code=topic_code, active=True).first()
        confirmed_norma_ids = set(NormaTopic.objects.filter(
            topic__code=topic_code,
            topic__active=True,
            status=NormaTopic.Status.CONFIRMED,
        ).values_list("norma_id", flat=True))
        if topic:
            topic_label = topic.label
        if not query and topic:
            topic_norms = consolidated_normas_for_product().filter(
                pk__in=confirmed_norma_ids,
                status="consolidated",
            )
            if norma_type:
                topic_norms = topic_norms.filter(tipo=norma_type)
            if year:
                topic_norms = topic_norms.filter(ano=year)
            results = [
                {
                    "dispositivo": None,
                    "norma": norma,
                    "similarity_score": None,
                    "relevance_label": "Afinidade temática",
                    "hierarchy": f"Tema confirmado: {topic.label}",
                    "texto": norma.ementa or (norma.texto_consolidado or "")[:500],
                }
                for norma in topic_norms.order_by("-ano", "-numero", "pk")[:50]
            ]
            search_mode = "topic"
            if not results:
                empty_state_title = "Nenhuma norma com esse tema confirmado"
                empty_state_description = (
                    "Não há normas consolidadas para este tema com os filtros selecionados. "
                    "Temas indicam afinidade e não representam alteração ou vigência jurídica."
                )
        else:
            results = [
                result for result in results
                if (norma := (result.get("norma") or getattr(result.get("dispositivo"), "norma", None)))
                and norma.pk in confirmed_norma_ids
            ]

    results = _exclude_synthetic_search_results(results)

    archive_search_available = False
    if query and not results and getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
        archive_search_available = DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            norma__isnull=True,
        ).exists()
    archive_assistant_available = (
        archive_search_available
        and getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
    )

    types = (
        consolidated_normas_for_product()
        .values_list("tipo", flat=True)
        .distinct()
        .order_by("tipo")
    )
    years = (
        consolidated_normas_for_product()
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
            "has_search": bool(query or topic_code),
            "archive_search_available": archive_search_available,
            "archive_assistant_available": archive_assistant_available,
            "norma_type": norma_type,
            "year": year,
            "min_similarity": min_similarity,
            "topic_code": topic_code,
            "topic_label": topic_label,
            "topics": topic_options,
            "results": results,
            "result_count": len(results),
            "search_mode": search_mode,
            "search_error": search_error,
            "empty_state_title": empty_state_title,
            "empty_state_description": empty_state_description,
            "types": type_options,
            "years": years,
            "active_nav": "search",
        },
    )


def collections_view(request):
    """List and create authenticated collections without fake client-only state."""
    archive_review_count = _archive_review_count()
    archive_assistant_enabled = (
        archive_review_count > 0
        and getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
    )
    form_values = {"name": "", "description": ""}
    if request.method == "POST":
        if not request.user.is_authenticated:
            messages.info(request, "Entre para criar coleções persistentes.")
            return redirect("workspace:collections")
        form_values = {
            "name": request.POST.get("name", ""),
            "description": request.POST.get("description", ""),
        }
        name = form_values["name"].strip()
        description = form_values["description"].strip()
        form_errors = {}
        if not name or len(name) > 120:
            form_errors["name"] = "Informe um nome com até 120 caracteres."
        if len(description) > 500:
            form_errors["description"] = "A descrição deve ter no máximo 500 caracteres."
        if form_errors:
            return render(
                request,
                "legislation/workspace/collections.html",
                {
                    "norma_count": consolidated_normas_for_product().count(),
                    "archive_review_count": archive_review_count,
                    "archive_assistant_enabled": archive_assistant_enabled,
                    "collections": list(
                        Collection.objects.filter(user=request.user)
                        .annotate(norma_count=Count("normas"))
                        .order_by("-updated_at", "name")
                    ),
                    "active_nav": "collections",
                    "collection_form_values": form_values,
                    "collection_form_errors": form_errors,
                    "collection_dialog_open": True,
                },
                status=400,
            )

        collection, created = Collection.objects.get_or_create(
            user=request.user, name=name, defaults={"description": description}
        )
        updated = False
        if not created and description and collection.description != description:
            collection.description = description
            collection.save(update_fields=["description", "updated_at"])
            updated = True
        if created:
            messages.success(request, "Coleção criada.")
        elif updated:
            messages.success(request, "Coleção atualizada.")
        else:
            messages.info(request, "A coleção já existe; nenhum dado foi alterado.")
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
            "norma_count": consolidated_normas_for_product().count(),
            "archive_review_count": archive_review_count,
            "archive_assistant_enabled": archive_assistant_enabled,
            "collections": collections,
            "active_nav": "collections",
            "collection_form_values": form_values,
            "collection_form_errors": {},
            "collection_dialog_open": False,
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
        submitted_norma_id = request.POST.get("norma_id", "")
        action = request.POST.get("action")
        try:
            parsed_norma_id = int(submitted_norma_id)
        except (TypeError, ValueError):
            parsed_norma_id = 0
        if not 0 < parsed_norma_id <= 9_223_372_036_854_775_807:
            norma = None
        elif action == "add":
            norma = Norma.objects.filter(pk=parsed_norma_id, status="consolidated").first()
        elif action == "remove":
            norma = Norma.objects.filter(pk=parsed_norma_id, status="consolidated").first()
        else:
            norma = None

        if norma is None or action not in {"add", "remove"}:
            error = (
                "Informe um identificador de norma válido."
                if norma is None
                else "Ação de coleção inválida."
            )
            return render(
                request,
                "legislation/workspace/collection_detail.html",
                {
                    "collection": collection,
                    "active_nav": "collections",
                    "collection_form_error": error,
                },
                status=400,
            )
        if action == "add":
            if collection.normas.filter(pk=norma.pk).exists():
                messages.info(request, "Esta norma já está nesta coleção.")
            else:
                collection.normas.add(norma)
                messages.success(request, "Norma adicionada à coleção.")
        else:
            if not collection.normas.filter(pk=norma.pk).exists():
                messages.info(request, "Esta norma já não está nesta coleção.")
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
            queryset=ChatMessage.objects.filter(role__in=("user", "assistant"))
            .only("session_id", "role", "content", "created_at")
            .order_by("-created_at")[:20],
            to_attr="history_messages",
        )
        initial_user_query = (
            ChatMessage.objects.filter(session_id=OuterRef("pk"), role="user")
            .order_by("created_at", "pk")
            .values("content")[:1]
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
            queryset.annotate(message_count=Count("messages", distinct=True))
            .annotate(primary_query=Subquery(initial_user_query))
            .prefetch_related(history_messages)
            .order_by("-updated_at", "-id")[:500]
        )
        if query:
            candidates = _rank_history(candidates, query)
        paginator = Paginator(candidates, 20)
        page_obj = paginator.get_page(page_number)
        sessions = list(page_obj)
        for session in sessions:
            session.primary_query = session.primary_query or "Sem consulta registrada"

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
