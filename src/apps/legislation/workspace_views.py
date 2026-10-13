"""Product-workspace views: assistant, search, collections, history and settings."""

import logging
import math
import re
import uuid
from collections import Counter
from datetime import date

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import conditional_escape, mark_safe
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.event_review import event_review_status
from src.apps.legislation.relations_api import can_view_pending_relations
from src.apps.legislation.source_urls import canonical_norma_url, canonical_sapl_url
from src.clients.sapl.sapl_types import resolve_norma_type_display
from src.processing.collection_evidence import (
    collection_evidence_impact,
    save_collection_evidence,
)
from src.processing.device_revision import legacy_device_identity_map
from src.processing.document_search import search_archive_documents
from src.processing.foundation_check import (
    FoundationCheckCancelled,
    check_foundation,
)
from src.processing.foundation_reference_parser import parse_foundation_references
from src.processing.normative_reference import (
    canonical_type,
    normalize_number,
    parse_normative_references,
)
from src.processing.rag_service import RAGService

from .models import (
    ChatMessage,
    ChatSession,
    Collection,
    CollectionEvidenceVersion,
    Dispositivo,
    EventoAlteracao,
    Norma,
    NormaTopic,
    Topic,
)
from .norma_queries import consolidated_normas_for_product

logger = logging.getLogger(__name__)

FOUNDATION_JOB_TTL_SECONDS = 900
PGM_LC258_SAPL_CATALOG_CHECKED_ON = "2026-10-13"
PGM_LC258_SAPL_RECORDS = {
    ("1894", 1969): ((3666, "lei"),),
    ("4885", 1997): ((6817, "lei"),),
    ("562", 2018): ((9202, "lei_promulgada"), (254, "lei_promulgada")),
    ("198", 2021): ((925, "lei_complementar"),),
}


def _pgm_lc258_sapl_registry_evidence(number: str, year: int | None, expected_type: str) -> dict:
    """Return only the dated, exact-identity SAPL candidates verified for this QA case."""
    catalog_types = {
        "lei": "Lei Ordinária",
        "lei_complementar": "Lei Complementar",
        "lei_promulgada": "Lei Promulgada",
    }
    raw_records = PGM_LC258_SAPL_RECORDS.get((number, year), ()) if year else ()
    records = [
        {
            "sapl_id": sapl_id,
            "number": number,
            "year": year,
            "type_key": type_key,
            "type_display": catalog_types[type_key],
            "url": canonical_sapl_url(sapl_id=sapl_id),
        }
        for sapl_id, type_key in raw_records
    ]
    if not records:
        status = "not_checked"
    elif len(records) > 1:
        status = "ambiguous"
    elif records[0]["type_key"] == expected_type:
        status = "exact_identity_candidate"
    else:
        status = "species_conflict"
    return {
        "status": status,
        "checked_on": PGM_LC258_SAPL_CATALOG_CHECKED_ON,
        "records": records,
    }


def _foundation_job_key(job_id):
    return f"jurix:foundation-check:{job_id}"


@require_http_methods(["GET", "POST"])
def workspace_login_view(request):
    """Sign in administrator-provisioned accounts without enabling open signup."""
    requested_next = (
        request.POST.get("next") if request.method == "POST" else request.GET.get("next", "")
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
    source_sync_reports = []
    if request.user.is_authenticated and request.user.is_staff:
        from src.apps.ingestion.source_sync_health import get_source_sync_health

        status_labels = {
            "current": "Ciclo recente registrado",
            "stale": "Atualização vencida",
            "degraded": "Atualização incompleta ou com falha",
            "running": "Sincronização em andamento",
            "unavailable": "Sem execução bem-sucedida",
            "not_configured": "Nenhuma sincronização registrada",
        }
        sources = (
            ("sapl", "SAPL · legislação municipal"),
            ("dom_natal", "Diário Oficial do Município"),
        )
        for source, label in sources:
            try:
                report = get_source_sync_health(source)
            except Exception:
                logger.warning("Unable to read normative source freshness for %s", source)
                report = {"status": "unavailable", "last_success_at": None}
            source_sync_reports.append(
                {
                    "label": label,
                    "status": report["status"],
                    "status_label": status_labels.get(report["status"], "Estado desconhecido"),
                    "last_success_at": report.get("last_success_at"),
                }
            )
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
            "source_sync_reports": source_sync_reports,
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

    candidates = (
        consolidated_normas_for_product()
        .filter(status="consolidated", ano=reference.year, numero__in=number_forms)
        .order_by("pk")
    )
    norms = [
        norma
        for norma in candidates
        if canonical_type(norma.get_tipo_display_name()) == reference.type_key
    ]
    if not norms:
        return []

    if reference.article:
        article_number = normalize_number(reference.article)
        devices = (
            Dispositivo.objects.filter(
                norma_id__in=[norma.pk for norma in norms], tipo="artigo", is_active=True
            )
            .select_related("norma")
            .order_by("ordem", "pk")
        )
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
    archive_type = request.GET.get("arquivo_tipo", "").strip()[:64]
    archive_year_raw = request.GET.get("arquivo_ano", "").strip()
    archive_review_status = request.GET.get("arquivo_revisao", "").strip()
    archive_extraction_status = request.GET.get("arquivo_extracao", "").strip()
    archive_page_number = request.GET.get("arquivo_pagina", "1").strip()

    try:
        year = int(year_raw) if year_raw else None
    except ValueError:
        year = None

    try:
        archive_year = int(archive_year_raw) if archive_year_raw else None
        if archive_year is not None and not 1000 <= archive_year <= 9999:
            archive_year = None
    except ValueError:
        archive_year = None

    try:
        min_similarity = max(0.0, min(float(min_similarity_raw), 1.0))
    except ValueError:
        min_similarity = 0.0

    results = []
    search_mode = "semantic"
    search_error = ""
    exact_reference_not_found = False
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
                exact_reference_not_found = True
                empty_state_title = "Nenhuma correspondência exata localizada"
                empty_state_description = (
                    "Não encontrei essa referência entre os resultados consolidados ou os PDFs de revisão "
                    "pesquisáveis nesta instância. Isso não prova que a norma inexista: arquivos ainda não "
                    "importados ou indexados podem não ter sido consultados. Confira o tipo, o número e o ano "
                    "ou pesquise por um assunto relacionado."
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

    topic_options = list(
        Topic.objects.filter(active=True).order_by("label").values("code", "label")
    )
    topic_label = ""
    if topic_code:
        topic = Topic.objects.filter(code=topic_code, active=True).first()
        confirmed_norma_ids = set(
            NormaTopic.objects.filter(
                topic__code=topic_code,
                topic__active=True,
                status=NormaTopic.Status.CONFIRMED,
            ).values_list("norma_id", flat=True)
        )
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
                result
                for result in results
                if (
                    norma := (
                        result.get("norma") or getattr(result.get("dispositivo"), "norma", None)
                    )
                )
                and norma.pk in confirmed_norma_ids
            ]

    results = _exclude_synthetic_search_results(results)

    from src.apps.legislation.document_views import _staff_can_view_candidate

    archive_search_available = bool(
        getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        and (
            (
                getattr(settings, "DEBUG", False)
                and getattr(settings, "NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED", False)
            )
            or _staff_can_view_candidate(request)
        )
    )
    archive_search = {
        "results": [],
        "count": 0,
        "page": None,
        "expanded": False,
        "groups": (),
        "types": [],
        "years": [],
        "total_candidates": 0,
    }
    archive_search_submitted = bool(
        query or archive_type or archive_year or archive_review_status or archive_extraction_status
    )
    if archive_search_available:
        try:
            archive_search = search_archive_documents(
                query,
                page=archive_page_number,
                document_type=archive_type,
                year=archive_year,
                review_status=archive_review_status,
                extraction_status=archive_extraction_status,
                include_results=archive_search_submitted,
            )
        except ValueError as exc:
            search_error = str(exc)
            search_mode = "não executada"
    if exact_reference_not_found:
        if archive_search["count"]:
            candidate_count = archive_search["count"]
            empty_state_title = "Referência ainda não consolidada"
            empty_state_description = (
                f"A busca encontrou {candidate_count} "
                f"{'PDF candidato' if candidate_count == 1 else 'PDFs candidatos'} no acervo histórico, "
                "exibidos abaixo. Esses documentos seguem pendentes de revisão e não equivalem a normas consolidadas."
            )
        else:
            empty_state_title = "Nenhum texto pesquisável localizado para esta referência"
            empty_state_description = (
                "A referência não aparece entre as normas consolidadas nem nos PDFs em revisão pesquisáveis "
                "desta instância. Isso não prova que a norma inexista: consulte o catálogo oficial SAPL pelo "
                "acervo normativo; uma entrada do catálogo pode conter somente metadados, sem o texto integral. "
                "A busca também não examina arquivos fora do staging. Confira o tipo, o número e o ano."
            )
    elif query and not results and archive_search["count"] and not topic_code:
        candidate_count = archive_search["count"]
        empty_state_title = "Nenhuma norma consolidada para esta consulta"
        empty_state_description = (
            f"A busca encontrou {candidate_count} "
            f"{'PDF candidato' if candidate_count == 1 else 'PDFs candidatos'} no acervo histórico, "
            "exibidos abaixo. Eles permanecem pendentes de revisão e não equivalem a normas consolidadas. "
            "Confira o documento original antes de usar a informação."
        )
    if archive_search_available and archive_search_submitted:
        for result in archive_search["results"]:
            document = result["document"]
            identity = result["identity"]
            type_label = _tipo_label(str(identity.get("type") or ""))
            number = str(identity.get("number") or "").strip()
            year_value = identity.get("year")
            number_label = f"nº {number}" if number else ""
            if number_label and year_value:
                number_label = f"{number_label}/{year_value}"
            result["label"] = (
                " ".join(
                    part
                    for part in (
                        type_label,
                        number_label or (str(year_value) if year_value else ""),
                    )
                    if part
                )
                or document.original_filename
                or "PDF do acervo local"
            )
            result["filename"] = document.original_filename or document.entry_name
            result["evidence_url"] = reverse(
                "legislation:document_evidence", args=[document.public_id]
            )
            result["highlighted_text"] = _highlight_search_text(result["excerpt"], query)

    archive_assistant_available = (
        archive_search_available
        and archive_search["total_candidates"] > 0
        and getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
    )
    archive_types = archive_search.get("types", [])
    archive_years = archive_search.get("years", [])
    archive_type_options = [
        {"value": value, "label": _tipo_label(value)} for value in archive_types
    ]
    archive_active_filters = []
    if archive_type:
        archive_active_filters.append(f"Espécie: {_tipo_label(archive_type)}")
    if archive_year is not None:
        archive_active_filters.append(f"Ano: {archive_year}")
    archive_review_labels = {
        DocumentoNormativo.ReviewStatus.PENDING: "Pendente",
        DocumentoNormativo.ReviewStatus.IN_REVIEW: "Em revisão",
    }
    if archive_review_status in archive_review_labels:
        archive_active_filters.append(f"Revisão: {archive_review_labels[archive_review_status]}")
    archive_extraction_labels = {
        "none": "Sem extração",
        ExtracaoDocumento.Status.COMPLETE: "Extração completa (não revisada)",
        ExtracaoDocumento.Status.PARTIAL: "Extração parcial",
        ExtracaoDocumento.Status.UNREADABLE: "Extração ilegível",
    }
    if archive_extraction_status in archive_extraction_labels:
        archive_active_filters.append(
            f"Texto: {archive_extraction_labels[archive_extraction_status]}"
        )
    archive_page = archive_search.get("page")
    archive_prev_query = archive_next_query = ""
    if archive_page:
        previous_params = request.GET.copy()
        next_params = request.GET.copy()
        if archive_page.has_previous():
            previous_params["arquivo_pagina"] = archive_page.previous_page_number()
            archive_prev_query = previous_params.urlencode()
        if archive_page.has_next():
            next_params["arquivo_pagina"] = archive_page.next_page_number()
            archive_next_query = next_params.urlencode()
    archive_assistant_available = archive_search_available and getattr(
        settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False
    )

    types = (
        consolidated_normas_for_product().values_list("tipo", flat=True).distinct().order_by("tipo")
    )
    years = (
        consolidated_normas_for_product().values_list("ano", flat=True).distinct().order_by("-ano")
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
            "archive_results": archive_search["results"],
            "archive_result_count": archive_search["count"],
            "archive_search_submitted": archive_search_submitted,
            "archive_page": archive_page,
            "archive_prev_query": archive_prev_query,
            "archive_next_query": archive_next_query,
            "archive_query_expanded": archive_search["expanded"],
            "archive_type": archive_type,
            "archive_year": archive_year,
            "archive_review_status": archive_review_status,
            "archive_extraction_status": archive_extraction_status,
            "archive_active_filters": archive_active_filters,
            "archive_type_options": archive_type_options,
            "archive_year_options": archive_years,
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
            "exact_reference_not_found": exact_reference_not_found,
            "empty_state_title": empty_state_title,
            "empty_state_description": empty_state_description,
            "types": type_options,
            "years": years,
            "active_nav": "search",
        },
    )


@login_required(login_url="workspace:login")
@require_http_methods(["GET", "POST"])
def foundation_check_view(request):
    """Compare explicitly cited devices without persisting the pasted document."""
    context = {
        "active_nav": "foundation_check",
        "job_id": uuid.uuid4(),
        "today": date.today().isoformat(),
        "text": "",
        "from_date": "",
        "to_date": "",
        "references": [],
        "result": None,
        "error": "",
    }
    if request.method == "GET":
        return render(request, "legislation/workspace/foundation_check.html", context)

    text = request.POST.get("text", "")
    context.update(
        text=text,
        from_date=request.POST.get("from_date", "").strip(),
        to_date=request.POST.get("to_date", "").strip(),
    )
    if len(text) > 50_000:
        context["error"] = "O texto excede o limite de 50.000 caracteres."
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)
    if not text.strip():
        context["error"] = "Cole a fundamentação ou os trechos que deseja conferir."
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)
    try:
        context["references"] = [ref.as_dict() for ref in parse_foundation_references(text)]
    except (TypeError, ValueError) as exc:
        context["error"] = str(exc)
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)

    action = request.POST.get("action", "review")
    if action == "review":
        if not context["references"]:
            context["error"] = (
                "Não identifiquei citações normativas explícitas. Revise o texto ou informe lei, número, ano e artigo."
            )
        return render(request, "legislation/workspace/foundation_check.html", context)

    if action != "compare":
        context["error"] = "Ação de conferência inválida."
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)

    from_date = parse_date(context["from_date"])
    to_date = parse_date(context["to_date"])
    if not from_date or not to_date or from_date >= to_date:
        context["error"] = "Informe duas datas válidas; a data inicial deve ser anterior à final."
        context["references"] = [ref.as_dict() for ref in parse_foundation_references(text)]
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)

    try:
        job_id = uuid.UUID(request.POST.get("job_id", ""))
    except (TypeError, ValueError, AttributeError):
        context["error"] = "A sessão de conferência expirou. Reenvie a solicitação."
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)
    context["job_id"] = job_id
    job_key = _foundation_job_key(job_id)
    job_state = {
        "owner_id": request.user.pk,
        "status": "running",
        "completed": 0,
        "total": 0,
    }
    try:
        created = cache.add(job_key, job_state, timeout=FOUNDATION_JOB_TTL_SECONDS)
    except Exception:
        logger.warning("Foundation check cache unavailable", exc_info=True)
        created = False
        context["error"] = (
            "A conferência está temporariamente indisponível. Tente novamente em instantes."
        )
        return render(request, "legislation/workspace/foundation_check.html", context, status=503)
    if not created:
        context["error"] = "Esta conferência já foi enviada ou expirou. Inicie uma nova tentativa."
        context["job_id"] = uuid.uuid4()
        return render(request, "legislation/workspace/foundation_check.html", context, status=409)

    def should_cancel():
        state = cache.get(job_key) or {}
        return state.get("owner_id") == request.user.pk and state.get("status") == "cancelling"

    def on_progress(completed, total):
        state = cache.get(job_key) or {}
        if state.get("owner_id") != request.user.pk:
            return
        state.update(completed=completed, total=total)
        if state.get("status") != "cancelling":
            state["status"] = "running"
        job_state.update(completed=completed, total=total)
        cache.set(job_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)

    try:
        result = check_foundation(
            text,
            from_date=from_date,
            to_date=to_date,
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
    except FoundationCheckCancelled:
        job_state.update(status="cancelled")
        cache.set(job_key, job_state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        context["cancelled"] = True
        context["job_id"] = uuid.uuid4()
        return render(request, "legislation/workspace/foundation_check.html", context, status=409)
    except (TypeError, ValueError) as exc:
        job_state.update(status="failed")
        cache.set(job_key, job_state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        context["error"] = str(exc)
        context["references"] = [ref.as_dict() for ref in parse_foundation_references(text)]
        context["job_id"] = uuid.uuid4()
        return render(request, "legislation/workspace/foundation_check.html", context, status=400)
    except Exception:
        logger.warning("Foundation check failed", exc_info=True)
        job_state.update(status="failed")
        cache.set(job_key, job_state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        context["error"] = (
            "Não foi possível concluir a conferência. O texto foi preservado; tente novamente."
        )
        context["job_id"] = uuid.uuid4()
        return render(request, "legislation/workspace/foundation_check.html", context, status=503)

    all_source_event_ids = {
        evidence.get("source_event_id")
        for reference in result["references"]
        for moment in ("before", "after")
        for evidence in reference["evidence"][moment]
        if evidence.get("source_event_id") is not None
    }
    source_events_by_id = {}
    if all_source_event_ids:
        events = EventoAlteracao.objects.filter(
            pk__in=all_source_event_ids,
            is_active=True,
            dispositivo_fonte__norma__status="consolidated",
        ).select_related("review_revision", "dispositivo_fonte__norma")
        for event in events:
            source_norma = event.dispositivo_fonte.norma
            identity = (
                source_norma.identity_json if isinstance(source_norma.identity_json, dict) else {}
            )
            if event_review_status(event) != "confirmed" or identity.get("synthetic_fixture"):
                continue
            source_events_by_id[event.pk] = {
                "event_id": event.pk,
                "action": event.get_acao_display(),
                "effective_on": event.effective_on.isoformat() if event.effective_on else None,
                "source_norma": str(source_norma),
                "source_device": event.dispositivo_fonte.get_caminho_completo(),
                "target_text": event.target_text,
                "norma_url": reverse("legislation:norma_detail", args=(source_norma.pk,)),
                "official_url": canonical_norma_url(source_norma),
            }

    for reference in result["references"]:
        source_event_ids = dict.fromkeys(
            evidence.get("source_event_id")
            for moment in ("before", "after")
            for evidence in reference["evidence"][moment]
            if evidence.get("source_event_id") is not None
        )
        reference["source_events"] = [
            source_events_by_id[event_id]
            for event_id in source_event_ids
            if event_id in source_events_by_id
        ]
        for moment in ("before", "after"):
            for evidence in reference["evidence"][moment]:
                evidence["pdf_url"] = reverse(
                    "legislation:document_pdf", args=(evidence["document_id"],)
                )
                if evidence["page"]:
                    evidence["pdf_url"] += f"#page={evidence['page']}"
    job_state.update(status="completed", completed=job_state["total"], total=job_state["total"])
    cache.set(job_key, job_state, timeout=FOUNDATION_JOB_TTL_SECONDS)
    context.update(result=result, job_id=uuid.uuid4())
    return render(request, "legislation/workspace/foundation_check.html", context)


@login_required(login_url="workspace:login")
def foundation_check_status_view(request, job_id):
    state = cache.get(_foundation_job_key(job_id))
    if not state or state.get("owner_id") != request.user.pk:
        return JsonResponse({"error": "Conferência não encontrada."}, status=404)
    return JsonResponse({key: value for key, value in state.items() if key != "owner_id"})


@login_required(login_url="workspace:login")
@require_POST
def foundation_check_cancel_view(request, job_id):
    key = _foundation_job_key(job_id)
    state = cache.get(key)
    if not state or state.get("owner_id") != request.user.pk:
        return JsonResponse({"error": "Conferência não encontrada."}, status=404)
    if state.get("status") == "running":
        state["status"] = "cancelling"
        cache.set(key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)
    return JsonResponse({"status": state.get("status")})


def explore_normative_graph_view(request):
    """Browse reviewed norms and open their bounded, evidence-backed relations."""
    requested_scope = request.GET.get("escopo", "revisadas").strip().lower()
    if requested_scope not in {"revisadas", "candidatas"}:
        requested_scope = "revisadas"
    can_view_candidates = bool(
        getattr(settings, "NORMATIVE_GRAPH_ENABLED", False)
        and can_view_pending_relations(request.user)
    )
    if requested_scope == "candidatas" and not can_view_candidates:
        return HttpResponseForbidden("Permissão insuficiente para consultar relações candidatas.")
    include_pending_relations = requested_scope == "candidatas"
    query = request.GET.get("q", "").strip()[:160]
    topic_code = request.GET.get("tema", "").strip()[:64]
    norma_type = request.GET.get("tipo", "").strip()[:100]
    year_raw = request.GET.get("ano", "").strip()
    from_raw = request.GET.get("de", "").strip()
    to_raw = request.GET.get("ate", "").strip()
    error = ""

    try:
        year = int(year_raw) if year_raw else None
        if year is not None and not 1000 <= year <= 9999:
            raise ValueError
    except ValueError:
        year = None
        error = "Informe um ano entre 1000 e 9999."

    date_from = parse_date(from_raw) if from_raw else None
    date_to = parse_date(to_raw) if to_raw else None
    if (from_raw and date_from is None) or (to_raw and date_to is None):
        error = "Informe as datas no formato válido."
    elif date_from and date_to and date_from > date_to:
        error = "A data inicial não pode ser posterior à data final."

    norms = (
        Norma.objects.filter(
            documento_base__isnull=False,
            dispositivos__alteracoes_causadas__is_active=True,
        ).distinct()
        if include_pending_relations
        else consolidated_normas_for_product()
    ).select_related("documento_base")
    has_available_norms = norms.exists()
    scope_norms = norms
    if norma_type:
        norms = norms.filter(tipo=norma_type)
    if year:
        norms = norms.filter(ano=year)
    if date_from:
        norms = norms.filter(data_publicacao__gte=date_from)
    if date_to:
        norms = norms.filter(data_publicacao__lte=date_to)
    if query:
        references = parse_normative_references(query)
        exact_reference = references[0] if len(references) == 1 else None
        if exact_reference and exact_reference.year:
            digits = normalize_number(exact_reference.number)
            first_group_size = len(digits) % 3 or 3
            number_forms = (
                {
                    digits,
                    ".".join(
                        [
                            digits[:first_group_size],
                            *(
                                digits[index : index + 3]
                                for index in range(first_group_size, len(digits), 3)
                            ),
                        ]
                    ),
                }
                if digits
                else set()
            )
            exact_candidates = norms.filter(ano=exact_reference.year, numero__in=number_forms)[:50]
            exact_ids = [
                item.pk
                for item in exact_candidates
                if canonical_type(_tipo_label(item.tipo)) == exact_reference.type_key
            ]
            norms = norms.filter(pk__in=exact_ids)
        else:
            for token in query.split()[:8]:
                norms = norms.filter(
                    Q(numero__icontains=token)
                    | Q(tipo__icontains=token)
                    | Q(ementa__icontains=token)
                )

    confirmed_topics = (
        Topic.objects.filter(
            active=True,
            norm_links__status=NormaTopic.Status.CONFIRMED,
            norm_links__norma__in=norms,
        )
        .distinct()
        .order_by("label")
    )
    topics = list(confirmed_topics.values("code", "label"))
    selected_topic = next((item for item in topics if item["code"] == topic_code), None)
    if topic_code:
        if selected_topic:
            norms = norms.filter(
                topic_links__topic__code=topic_code,
                topic_links__status=NormaTopic.Status.CONFIRMED,
            )
        else:
            norms = norms.none()

    if error:
        norms = norms.none()

    type_options = list(scope_norms.values_list("tipo", flat=True).distinct().order_by("tipo"))
    years = list(scope_norms.values_list("ano", flat=True).distinct().order_by("-ano"))
    norms = norms.order_by("-ano", "tipo", "numero", "pk").distinct()
    selected_norma = None
    raw_selected_id = request.GET.get("norma", "").strip()
    if raw_selected_id.isdigit() and getattr(settings, "NORMATIVE_GRAPH_ENABLED", False):
        selected_norma = norms.filter(pk=int(raw_selected_id)).first()

    paginator = Paginator(norms, 20)
    page = paginator.get_page(request.GET.get("page", "1"))

    query_params = request.GET.copy()
    for key in ("page", "norma"):
        query_params.pop(key, None)
    return render(
        request,
        "legislation/workspace/explore.html",
        {
            "query": query,
            "topic_code": topic_code,
            "selected_topic": selected_topic,
            "topics": topics,
            "norma_type": norma_type,
            "type_options": type_options,
            "year": year,
            "years": years,
            "date_from_raw": from_raw,
            "date_to_raw": to_raw,
            "error": error,
            "page": page,
            "result_count": paginator.count,
            "has_available_norms": has_available_norms,
            "selected_norma": selected_norma,
            "include_pending_relations": include_pending_relations,
            "can_view_candidates": can_view_candidates,
            "normative_graph_enabled": getattr(settings, "NORMATIVE_GRAPH_ENABLED", False),
            "pgm_consolidation_demo_enabled": bool(
                getattr(settings, "DEBUG", False)
                and getattr(settings, "PGM_CONSOLIDATION_DEMO_ENABLED", False)
            ),
            "query_string": query_params.urlencode(),
            "active_nav": "explore",
        },
    )


def _parse_repeal_candidates(legal_text):
    article_match = re.search(
        r"\bArt\.\s*260\.\s*Ficam revogados:(.*?)(?=\bArt\.\s*261\b)",
        legal_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if article_match is None:
        return None, []
    item_pattern = (
        r"(?m)^\s*(VII|VI|V|IV|III|II|I)\s*-\s*(.*?)(?="
        r"^\s*(?:VII|VI|V|IV|III|II|I)\s*-|\Z)"
    )
    items = [
        (match.group(1), re.sub(r"\s+", " ", match.group(2)).strip().rstrip(";."))
        for match in re.finditer(item_pattern, article_match.group(1), flags=re.DOTALL)
    ]
    return article_match, items


def pgm_consolidation_demo_view(request):
    """Show a read-only, QA-only graph of every act named by LC 258/2024 Art. 260."""
    if not (
        getattr(settings, "DEBUG", False)
        and getattr(settings, "PGM_CONSOLIDATION_DEMO_ENABLED", False)
    ):
        raise Http404("Prévia disponível somente no ambiente QA autorizado.")

    from src.apps.legislation.document_models import ExtracaoDocumento

    source_document = DocumentoNormativo.objects.filter(
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        original_filename="LeiComplementar_20241227_258_.pdf",
        metadata_json__identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|258|2024",
    ).first()
    if source_document is None or source_document.review_status == DocumentoNormativo.ReviewStatus.APPROVED:
        raise Http404("O documento candidato desta demonstração não está disponível.")
    extraction = source_document.extracoes.filter(status=ExtracaoDocumento.Status.COMPLETE).order_by(
        "-created_at", "-pk"
    ).first()
    if extraction is None:
        raise Http404("A extração completa necessária para a demonstração não está disponível.")

    source_match, parsed_items = _parse_repeal_candidates(extraction.legal_text)
    if source_match is None:
        raise Http404("O Art. 260 não foi encontrado na extração arquivada.")
    if len(parsed_items) != 7:
        raise Http404("A lista do Art. 260 não pôde ser segmentada integralmente.")

    source_quote = re.sub(r"\s+", " ", source_match.group(0)).strip()
    source_page = next(
        (
            span.get("page")
            for span in extraction.page_map_json
            if span.get("start", 0) <= source_match.start() < span.get("end", 0)
        ),
        None,
    )
    source_pdf_url = reverse("legislation:document_pdf", args=(source_document.public_id,))
    if source_page:
        source_pdf_url = f"{source_pdf_url}#page={source_page}"

    references = []
    for roman, citation in parsed_items:
        number_match = re.search(r"n[ºo.]?\s*([\d.]+)", citation, flags=re.IGNORECASE)
        year_match = re.search(r"\b(?:19|20)\d{2}\b", citation)
        normalized_number = (
            re.sub(r"\D", "", number_match.group(1)).lstrip("0") or "0"
            if number_match
            else ""
        )
        year = int(year_match.group(0)) if year_match else None
        if "lei complementar" in citation.casefold():
            expected_type = "lei_complementar"
        elif "lei promulgada" in citation.casefold():
            expected_type = "lei_promulgada"
        else:
            expected_type = "lei"
        possible_documents = list(
            DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                metadata_json__identity_candidate__number=normalized_number,
                metadata_json__identity_candidate__year=year,
            )[:8]
        ) if normalized_number and year else []
        exact_document = next(
            (
                document
                for document in possible_documents
                if (document.metadata_json or {}).get("identity_candidate", {}).get("type")
                == expected_type
            ),
            None,
        )
        conflicting_documents = [
            document
            for document in possible_documents
            if document.pk != getattr(exact_document, "pk", None)
        ]
        target_pdf_url = None
        target_page = None
        if exact_document and exact_document.review_status != DocumentoNormativo.ReviewStatus.APPROVED:
            target_pdf_url = reverse("legislation:document_pdf", args=(exact_document.public_id,))
            target_extraction = exact_document.extracoes.filter(
                status=ExtracaoDocumento.Status.COMPLETE
            ).order_by("-created_at", "-pk").first()
            article_match = re.match(r"Art\.\s*(\d+)", citation, flags=re.IGNORECASE)
            if target_extraction and article_match:
                device_match = re.search(
                    rf"\bArt\.\s*{article_match.group(1)}\b",
                    target_extraction.legal_text,
                    flags=re.IGNORECASE,
                )
                if device_match:
                    target_page = next(
                        (
                            span.get("page")
                            for span in target_extraction.page_map_json
                            if span.get("start", 0) <= device_match.start() < span.get("end", 0)
                        ),
                        None,
                    )
            if target_page:
                target_pdf_url = f"{target_pdf_url}#page={target_page}"

        conflicts = []
        for document in conflicting_documents:
            candidate_type = (document.metadata_json or {}).get("identity_candidate", {}).get(
                "type", "indeterminada"
            )
            candidate_type_display = {
                "lei": "Lei",
                "lei_complementar": "Lei Complementar",
                "lei_promulgada": "Lei Promulgada",
            }.get(candidate_type, "espécie indeterminada")
            conflicts.append(
                {
                    "document": document,
                    "candidate_type": candidate_type_display,
                    "pdf_url": reverse(
                        "legislation:document_pdf", args=(document.public_id,)
                    ),
                }
            )
        references.append(
            {
                "roman": roman,
                "citation": citation,
                "expected_type": expected_type,
                "sapl_registry": _pgm_lc258_sapl_registry_evidence(
                    normalized_number, year, expected_type
                ),
                "expected_type_display": {
                    "lei": "Lei",
                    "lei_complementar": "Lei Complementar",
                    "lei_promulgada": "Lei Promulgada",
                }[expected_type],
                "document": exact_document,
                "pdf_url": target_pdf_url,
                "page": target_page,
                "conflicts": conflicts,
                "state": "candidate" if exact_document else "identity_conflict" if conflicts else "not_found",
            }
        )

    if not any(item["roman"] == "IV" and item["document"] for item in references):
        raise Http404("O PDF candidato da LC 55/2004 não foi localizado para conferência.")

    source_segmentation_count = extraction.dispositivos_documentais.count()
    target_count = sum(item["state"] == "candidate" for item in references)
    conflict_count = sum(item["state"] == "identity_conflict" for item in references)
    missing_count = sum(item["state"] == "not_found" for item in references)

    return render(
        request,
        "legislation/workspace/pgm_consolidation_demo.html",
        {
            "source_document": source_document,
            "source_extraction": extraction,
            "source_quote": source_quote,
            "source_page": source_page,
            "source_pdf_url": source_pdf_url,
            "source_segmentation_count": source_segmentation_count,
            "references": references,
            "target_count": target_count,
            "conflict_count": conflict_count,
            "missing_count": missing_count,
            "active_nav": "explore",
        },
    )


def collections_view(request):
    """List and create authenticated collections without fake client-only state."""
    archive_review_count = _archive_review_count()
    archive_assistant_enabled = archive_review_count > 0 and getattr(
        settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False
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
    device_labels = {}
    for norma in collection.normas.all():
        devices = list(norma.dispositivos.select_related("dispositivo_pai").order_by("ordem", "pk"))
        try:
            key_to_id = legacy_device_identity_map(devices)
            key_by_id = {device_id: key for key, device_id in key_to_id.items()}
        except ValueError:
            key_to_id = {}
            key_by_id = {}
        options = [
            {"key": key_by_id[device.pk], "label": device.get_caminho_completo()}
            for device in devices
            if device.pk in key_by_id
        ]
        norma.evidence_device_options = options
        device_labels[norma.pk] = {option["key"]: option["label"] for option in options}
        norma.evidence_device_ids = key_to_id

    def render_collection_form_error(error, *, norma=None, as_of=None, device_key=""):
        if norma is not None:
            display_norma = next(
                (item for item in collection.normas.all() if item.pk == norma.pk), norma
            )
            display_norma.evidence_form_as_of = parse_date(as_of or "")
            display_norma.evidence_form_device_key = device_key
        return render(
            request,
            "legislation/workspace/collection_detail.html",
            {
                "collection": collection,
                "active_nav": "collections",
                "today": timezone.localdate(),
                "collection_form_error": error,
            },
            status=400,
        )

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
        elif action == "save_evidence":
            norma = Norma.objects.filter(pk=parsed_norma_id, status="consolidated").first()
        else:
            norma = None

        if norma is None or action not in {"add", "remove", "save_evidence"}:
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
        elif action == "remove":
            if not collection.normas.filter(pk=norma.pk).exists():
                messages.info(request, "Esta norma já não está nesta coleção.")
            else:
                collection.normas.remove(norma)
                messages.success(request, "Norma removida da coleção.")
        else:
            as_of = parse_date(request.POST.get("as_of", "").strip())
            device_key = request.POST.get("device_key", "").strip()
            if len(device_key) > 160:
                return render_collection_form_error(
                    "O identificador do dispositivo é inválido.",
                    norma=norma,
                    as_of=request.POST.get("as_of", ""),
                )
            if as_of is None:
                return render_collection_form_error(
                    "Informe uma data válida para congelar a referência.",
                    norma=norma,
                    device_key=device_key,
                )
            if as_of > timezone.localdate():
                return render_collection_form_error(
                    "A data da versão não pode estar no futuro.",
                    norma=norma,
                    as_of=as_of.isoformat(),
                    device_key=device_key,
                )
            try:
                saved = save_collection_evidence(
                    collection=collection,
                    owner_id=request.user.pk,
                    norma=norma,
                    as_of=as_of,
                    device_key=device_key,
                )
            except (PermissionError, ValueError) as exc:
                return render_collection_form_error(
                    str(exc),
                    norma=norma,
                    as_of=as_of.isoformat(),
                    device_key=device_key,
                )
            messages.success(
                request,
                f"Versão {saved.version} salva como {saved.get_result_display().lower()}.",
            )
        return redirect("workspace:collection_detail", pk=collection.pk)
    evidence_impacts = collection_evidence_impact(collection, current_date=timezone.localdate())
    evidence_versions = list(
        CollectionEvidenceVersion.objects.filter(collection=collection, owner=request.user)
        .select_related("norma", "snapshot")
        .order_by("-created_at")[:100]
    )
    for version in evidence_versions:
        version.device_label = device_labels.get(version.norma_id, {}).get(
            version.device_key, "Dispositivo específico" if version.device_key else "Norma inteira"
        )
        version.device_id = next(
            (
                norma.evidence_device_ids.get(version.device_key)
                for norma in collection.normas.all()
                if norma.pk == version.norma_id
            ),
            None,
        )
    for impact in evidence_impacts:
        if not impact.get("truncated"):
            impact["device_label"] = device_labels.get(impact["saved"].norma_id, {}).get(
                impact["device_key"],
                "Dispositivo específico" if impact["device_key"] else "Norma inteira",
            )
            impact["device_id"] = next(
                (
                    norma.evidence_device_ids.get(impact["device_key"])
                    for norma in collection.normas.all()
                    if norma.pk == impact["saved"].norma_id
                ),
                None,
            )
    return render(
        request,
        "legislation/workspace/collection_detail.html",
        {
            "collection": collection,
            "active_nav": "collections",
            "today": timezone.localdate(),
            "evidence_impacts": evidence_impacts,
            "evidence_versions": evidence_versions,
        },
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
