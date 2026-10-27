"""Product-workspace views: assistant, search, collections, history and settings."""

import hashlib
import json
import logging
import math
import re
import uuid
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery
from django.http import Http404, HttpResponseForbidden, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.utils.html import conditional_escape, mark_safe
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_http_methods, require_POST

from src.apps.legislation.document_models import (
    AIPilotAdoption,
    DocumentoNormativo,
    ExtracaoDocumento,
)
from src.apps.legislation.event_review import event_review_status
from src.apps.legislation.foundation_jobs import (
    FOUNDATION_JOB_TTL_SECONDS,
    foundation_job_key,
    foundation_payload_key,
    foundation_result_key,
)
from src.apps.legislation.relations_api import can_view_pending_relations
from src.apps.legislation.source_urls import canonical_norma_url, canonical_sapl_url
from src.clients.sapl.sapl_types import resolve_norma_type_display
from src.processing.candidate_relation_service import (
    build_candidate_relation_evidence,
    classify_identity_candidates,
)
from src.processing.collection_evidence import (
    collection_evidence_impact,
    save_collection_evidence,
)
from src.processing.device_revision import legacy_device_identity_map
from src.processing.document_search import search_archive_documents
from src.processing.foundation_reference_parser import parse_foundation_references
from src.processing.normative_reference import (
    canonical_type,
    normalize_number,
    parse_normative_references,
)
from src.processing.official_urls import safe_official_url
from src.processing.rag_service import RAGService

from .document_views import local_pdf_available
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

PGM_LC258_SAPL_CATALOG_CHECKED_ON = "2026-10-15"
PGM_LC271_DOM_PUBLICATION = {
    "date": date(2025, 12, 16),
    "issue": "Diário Oficial do Município nº 5935 · edição extra",
    "url": (
        "https://natal.rn.gov.br/storage/app/media/DOM/anexos/"
        "dom_20251216_extra_f56130954932a6ec421028e3224ffc68.pdf"
    ),
    "issue_quote": "ANO XXV - Nº. 5935 - NATAL/RN, TERÇA-FEIRA, 16 DE DEZEMBRO DE 2025-EDIÇÃO EXTRA",
    "effective_clause": "Art. 6º Esta Lei entra em vigor na data de sua publicação.",
}
PGM_LC55_ORIGINAL_OFFICIAL_PDF = (
    "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_complementar_n_055.pdf"
)
PGM_LC258_SAPL_RECORDS = {
    ("1894", 1969): ((3666, "lei", "1969-12-25"),),
    # SAPL finds the same number as an ordinary law in 1994, not the
    # 1992 instrument named by LC 258/2024, Art. 260, item II.
    ("4566", 1992): ((6491, "lei", "1994-08-27", 1994),),
    ("4885", 1997): ((6817, "lei", "1997-10-07"),),
    # The number exists in SAPL as a complementary law of 2026, not as the
    # promulgated law of 2009 named by LC 258/2024, Art. 260, item V.
    ("275", 2009): ((9050, "lei_complementar", "2026-02-03", 2026),),
    ("562", 2018): (
        (9202, "lei_promulgada", "2018-09-18"),
        (254, "lei_promulgada", "2018-09-14"),
    ),
    ("198", 2021): ((925, "lei_complementar", "2021-11-12"),),
}
PGM_LC258_OFFICIAL_SOURCES = {
    ("1894", 1969): (
        {
            "source": "Biblioteca Virtual do Natal / SEMURB",
            "title": "Lei nº 1.894, de 31 de dezembro de 1969 — Código de Obras antigo",
            "url": "https://www2.natal.rn.gov.br/bvn/detalheBVN.php?valorRegistro=1890",
            "document_url": "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_n_1.894_69.pdf",
            "date_display": "31/12/1969 · ano indicado no título do documento",
            "note": (
                "A fonte municipal identifica o ato como Lei nº 1.894/1969, enquanto "
                "o Art. 260 da LC 258/2024 o denomina Lei Complementar. A espécie "
                "diverge; não associar nem tratar como revogação integral validada "
                "sem revisar a publicação e o regime histórico do ato."
            ),
        },
    ),
    ("4885", 1997): (
        {
            "source": "Biblioteca Virtual do Natal (BVN)",
            "title": "Lei nº 4.885, de 07 de outubro de 1997 — RITUR",
            "url": "https://www2.natal.rn.gov.br/bvn/detalheBVN.php?valorRegistro=1912",
            "document_url": "https://www2.natal.rn.gov.br/bvn/publicacoes/ritur_relatorio_de_impacto_sobre_trafego_urbano.pdf",
            "date_display": "07/10/1997 · assinatura e publicação na ficha BVN",
            "note": (
                "O PDF contém a Lei nº 4.885/1997 nas páginas iniciais e, a partir "
                "da página 3, um Decreto nº 8.227/2007 separado. Trate-os como atos "
                "distintos; o arquivo compilado não prova, sozinho, a redação vigente "
                "da lei nem a relação de revogação da LC 258/2024."
            ),
        },
    ),
    ("198", 2021): (
        {
            "source": "SAPL Natal · ficha oficial e texto original",
            "title": "Lei Complementar nº 198, de 12 de novembro de 2021",
            "url": "https://sapl.natal.rn.leg.br/norma/925",
            "document_url": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2021/925/plc_006.21-convertido.pdf",
            "date_display": "ficha: 12/11/2021; publicação cadastrada: 20/12/2021",
            "note": (
                "O cadastro SAPL identifica este ato como Lei Complementar, embora "
                "o Art. 260 da LC 258/2024 cite ‘Lei nº 198’. O PDF ligado como texto "
                "original deixa número/data do cabeçalho em branco e traz data final "
                "de 06/10/2021; conferir a publicação no DOM antes de consolidar. "
                "Se confirmado como LC 198, seus Arts. 1º, 2º e 4º fazem referência "
                "à LC 55/2004, mas não substituem por si sós a redação desses artigos."
            ),
        },
    ),
    ("4566", 1992): (
        {
            "source": "Biblioteca Virtual do Natal (BVN)",
            "title": "Lei nº 4.566, de 19 de maio de 1992 — ficha bibliográfica",
            "url": "https://www2.natal.rn.gov.br/bvn/detalheBVN.php?valorRegistro=1871",
            "document_url": "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf",
            "date_display": "19/05/1992 (assinatura e publicação na ficha)",
            "identity_conflict": True,
            "note": (
                "Conflito documental de identidade: a ficha BVN cataloga Lei Ordinária, "
                "mas o PDF traz ‘DECRETA’ no preâmbulo e chama o ato de ‘presente Decreto’ "
                "no Art. 2º e ‘este decreto’ no Art. 7º. A nota do PDF informa publicação "
                "no DOE em 21/05/1992. Não classificar nem vincular como lei/decreto sem "
                "conferência jurídica da publicação oficial."
            ),
        },
    ),
    ("562", 2018): (
        {
            "source": "SAPL Natal · ficha e texto original",
            "title": "Lei Promulgada nº 562, de 14 de setembro de 2018",
            "url": "https://sapl.natal.rn.leg.br/norma/254",
            "document_url": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2018/254/lp_562.18.pdf",
            "date_display": "promulgada em 14/09/2018; publicação cadastrada em 18/09/2018",
            "note": (
                "A ficha oficial e o PDF identificam Lei Promulgada nº 562/2018; "
                "o Art. 13 prevê vigência na data da publicação e revoga disposições "
                "em contrário. O Art. 260, VI, da LC 258/2024 cita este ato "
                "expressamente, mas esta referência não certifica a data de eficácia "
                "da revogação nem substitui a conferência do DOM e do caso concreto."
            ),
        },
    ),
    ("275", 2009): (
        {
            "source": "Diário Oficial do Município de Natal",
            "title": "DOM nº 1.538, de 17 de março de 2009 — Lei Promulgada nº 0275/2009",
            "url": "https://natal.rn.gov.br/storage/app/media/DOM/anexos/dom_20090317.pdf",
            "document_url": "https://natal.rn.gov.br/storage/app/media/DOM/anexos/dom_20090317.pdf",
            "date_display": "publicado em 17/03/2009; texto datado de 12/03/2009",
            "note": (
                "O DOM reproduz a Lei Promulgada nº 0275/2009, incluindo o Art. 21 "
                "(PDF, páginas 7–9). É fonte do texto promulgado, não prova por si "
                "só a vigência atual ou os efeitos da revogação mencionada em 2024."
            ),
        },
    ),
}
PGM_LC261_SAPL_REGISTRY_RECORDS = {
    # Independently fetched from the official SAPL API on 2026-10-16. The
    # repeal text calls these "Lei Municipal", while the catalog identifies
    # the same number/year as complementary laws. Keep this as a visible
    # identity conflict; it is not an automatic legal relation.
    ("208", 2022): (1160, "lei_complementar", "08/03/2022"),
    ("221", 2022): (1176, "lei_complementar", "28/12/2022"),
    ("222", 2022): (1595, "lei_complementar", "28/12/2022"),
    ("223", 2022): (1596, "lei_complementar", "28/12/2022"),
}


_PGM_PORTUGUESE_MONTHS = {
    "janeiro": 1,
    "fevereiro": 2,
    "março": 3,
    "marco": 3,
    "abril": 4,
    "maio": 5,
    "junho": 6,
    "julho": 7,
    "agosto": 8,
    "setembro": 9,
    "outubro": 10,
    "novembro": 11,
    "dezembro": 12,
}


def _pgm_citation_date(citation: str) -> date | None:
    match = re.search(
        r"\b(\d{1,2})\s+de\s+(janeiro|fevereiro|março|marco|abril|maio|junho|julho|"
        r"agosto|setembro|outubro|novembro|dezembro)\s+de\s+(\d{4})\b",
        citation,
        re.IGNORECASE,
    )
    if not match:
        return None
    try:
        return date(
            int(match.group(3)),
            _PGM_PORTUGUESE_MONTHS[match.group(2).lower()],
            int(match.group(1)),
        )
    except ValueError:
        return None


def _pgm_lc258_sapl_registry_evidence(
    number: str, year: int | None, expected_type: str, reference_date: date | None = None
) -> dict:
    """Return only the dated, exact-identity SAPL candidates verified for this QA case."""
    catalog_types = {
        "lei": "Lei Ordinária",
        "lei_complementar": "Lei Complementar",
        "lei_promulgada": "Lei Promulgada",
    }
    raw_records = PGM_LC258_SAPL_RECORDS.get((number, year), ()) if year else ()
    records = []
    for raw_record in raw_records:
        sapl_id, type_key, record_date = raw_record[:3]
        record_year = raw_record[3] if len(raw_record) > 3 else year
        parsed_record_date = date.fromisoformat(record_date)
        records.append(
            {
                "sapl_id": sapl_id,
                "number": number,
                "year": record_year,
                "year_match": record_year == year,
                "type_key": type_key,
                "type_display": catalog_types[type_key],
                "date": record_date,
                "date_display": parsed_record_date.strftime("%d/%m/%Y"),
                "reference_date_match": reference_date is not None
                and parsed_record_date == reference_date,
                "url": canonical_sapl_url(sapl_id=sapl_id),
            }
        )
    records.sort(key=lambda record: (not record["reference_date_match"], record["sapl_id"]))
    if not records:
        status = "not_checked"
    elif not any(record["year_match"] for record in records):
        status = (
            "identity_conflict"
            if any(record["type_key"] != expected_type for record in records)
            else "year_conflict"
        )
    elif len(records) > 1 and reference_date is not None:
        matching_records = [record for record in records if record["reference_date_match"]]
        if len(matching_records) == 1 and matching_records[0]["type_key"] == expected_type:
            status = "date_matched_candidate"
        elif len(matching_records) == 1:
            status = "species_conflict"
        else:
            status = "ambiguous"
    elif len(records) > 1:
        status = "ambiguous"
    elif records[0]["type_key"] != expected_type:
        status = "species_conflict"
    elif reference_date is not None and not records[0]["reference_date_match"]:
        status = "date_conflict"
    else:
        status = "exact_identity_candidate"
    official_sources = [
        {
            **source,
            "url": safe_official_url(source.get("url")),
            "document_url": safe_official_url(source.get("document_url")),
        }
        for source in PGM_LC258_OFFICIAL_SOURCES.get((number, year), ())
    ]
    return {
        "status": status,
        "checked_on": PGM_LC258_SAPL_CATALOG_CHECKED_ON,
        "reference_year": year,
        "reference_date": reference_date.isoformat() if reference_date else None,
        "reference_date_display": reference_date.strftime("%d/%m/%Y") if reference_date else None,
        "records": records,
        "official_sources": official_sources,
    }


def _foundation_job_key(job_id):
    return foundation_job_key(job_id)


@require_http_methods(["GET", "POST"])
def workspace_login_view(request):
    """Sign in administrator-provisioned accounts without enabling open signup."""
    requested_next = (
        request.POST.get("next") if request.method == "POST" else request.GET.get("next", "")
    )
    foundation_check_requested = (
        (requested_next or "").split("?", 1)[0] == reverse("workspace:foundation_check")
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
        {
            "form": form,
            "next": requested_next,
            "foundation_check_requested": foundation_check_requested,
        },
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
                    "scope_count": report.get("scope_count", 0),
                    "full_sweep_scope_count": report.get("full_sweep_scope_count", 0),
                    "partial_scope_count": report.get("partial_scope_count", 0),
                    "uninitialized_scope_count": report.get("uninitialized_scope_count", 0),
                    "failed_scope_count": report.get("failed_scope_count", 0),
                    "stale_scope_count": report.get("stale_scope_count", 0),
                    "stale_incremental_scope_count": report.get(
                        "stale_incremental_scope_count", 0
                    ),
                    "stale_full_sweep_scope_count": report.get(
                        "stale_full_sweep_scope_count", 0
                    ),
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
    from src.apps.legislation.pilot_catalog import pilot_catalog_context

    pilot_context = pilot_catalog_context(request)
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

    if query and len(query) <= 200 and pilot_context["selected_scope"] in {"todos", "revisadas"} and not pilot_context.get("pilot_reference_exact"):
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
        "record_count": 0,
        "page": None,
        "expanded": False,
        "groups": (),
        "types": [],
        "years": [],
        "total_candidates": 0,
    }
    archive_recent_browse = request.GET.get("arquivo_recentes") == "1"
    archive_search_submitted = bool(
        query
        or archive_type
        or archive_year
        or archive_review_status
        or archive_extraction_status
        or archive_recent_browse
    )
    if archive_search_available and pilot_context["selected_scope"] in {"todos", "documentos"}:
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
            candidate_count = archive_search.get("record_count", archive_search["count"])
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
        candidate_count = archive_search.get("record_count", archive_search["count"])
        empty_state_title = "Nenhuma norma consolidada para esta consulta"
        empty_state_description = (
            f"A busca encontrou {candidate_count} "
            f"{'PDF candidato' if candidate_count == 1 else 'PDFs candidatos'} no acervo histórico, "
            "exibidos abaixo. Eles permanecem pendentes de revisão e não equivalem a normas consolidadas. "
            "Confira o documento original antes de usar a informação."
        )
    if archive_search_available and archive_search_submitted:
        first_archive_excerpt_by_digest = {}
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
            result["excerpt_duplicate_of"] = ""
            excerpt = str(result.get("excerpt") or "").strip()
            if result.get("excerpt_matched") and excerpt:
                excerpt_digest = hashlib.sha256(excerpt.encode("utf-8")).hexdigest()
                result["excerpt_duplicate_of"] = first_archive_excerpt_by_digest.get(
                    excerpt_digest, ""
                )
                first_archive_excerpt_by_digest.setdefault(
                    excerpt_digest,
                    f"{result['label']} · {result['filename']}",
                )
            for identical_source in result.get("identical_sources", (document,)):
                identical_metadata = (
                    identical_source.metadata_json
                    if isinstance(identical_source.metadata_json, dict)
                    else {}
                )
                identical_identity = identical_metadata.get("identity_candidate") or {}
                identical_type_label = _tipo_label(str(identical_identity.get("type") or ""))
                identical_number = str(identical_identity.get("number") or "").strip()
                identical_year = identical_identity.get("year")
                identical_number_label = f"nº {identical_number}" if identical_number else ""
                if identical_number_label and identical_year:
                    identical_number_label = f"{identical_number_label}/{identical_year}"
                identical_source.archive_label = (
                    " ".join(
                        part
                        for part in (identical_type_label, identical_number_label)
                        if part
                    )
                    or identical_source.original_filename
                    or "PDF do acervo local"
                )
                identical_source.evidence_url = reverse(
                    "legislation:document_evidence", args=[identical_source.public_id]
                )

    archive_assistant_available = (
        archive_search_available
        and archive_search["total_candidates"] > 0
        and getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
    )
    requested_archive_types = archive_search.get("requested_types", ())
    archive_requested_type_label = (
        _tipo_label(requested_archive_types[0])
        if len(requested_archive_types) == 1
        else ""
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
            **pilot_context,
            "query": query,
            "has_search": bool(query or topic_code),
            "archive_search_available": archive_search_available,
            "archive_assistant_available": archive_assistant_available,
            "archive_results": archive_search["results"],
            "archive_result_count": archive_search["count"],
            "archive_record_count": archive_search.get("record_count", archive_search["count"]),
            "archive_search_submitted": archive_search_submitted,
            "archive_recent_browse": archive_recent_browse,
            "archive_page": archive_page,
            "archive_prev_query": archive_prev_query,
            "archive_next_query": archive_next_query,
            "archive_query_expanded": archive_search["expanded"],
            "archive_requested_type_label": archive_requested_type_label,
            "archive_requested_type_found": archive_search.get("requested_type_found"),
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
        if request.GET.get("action") == "result":
            try:
                job_id = uuid.UUID(request.GET.get("job_id", ""))
            except (TypeError, ValueError, AttributeError):
                raise Http404 from None
            state = cache.get(_foundation_job_key(job_id)) or {}
            if state.get("owner_id") != request.user.pk:
                raise Http404
            if state.get("status") != "completed":
                if state.get("status") == "cancelled":
                    context["cancelled"] = True
                elif state.get("status") == "failed":
                    context["error"] = "Não foi possível concluir a conferência. O texto permanece no campo; tente novamente."
                else:
                    raise Http404
            else:
                result = cache.get(foundation_result_key(job_id))
                if not isinstance(result, dict):
                    context["error"] = "O resultado expirou. Reenvie a conferência."
                else:
                    context["result"] = result
                    context["references"] = [
                        {
                            "type_key": item.get("identity", {}).get("type"),
                            "number": item.get("identity", {}).get("number"),
                            "year": item.get("identity", {}).get("year"),
                            "article": item.get("identity", {}).get("article"),
                            "paragraph": item.get("identity", {}).get("paragraph"),
                            "item": item.get("identity", {}).get("item"),
                            "alinea": item.get("identity", {}).get("alinea"),
                            "text": item.get("text", ""),
                            "requires_confirmation": item.get("status") == "confirmation_required",
                            "ambiguity_reason": item.get("reason"),
                        }
                        for item in result.get("references", [])
                    ]
                    context["from_date"] = result.get("comparison", {}).get("from", "")
                    context["to_date"] = result.get("comparison", {}).get("to", "")
                    _enrich_foundation_result(result, user=request.user)
            context["job_id"] = uuid.uuid4()
            return render(request, "legislation/workspace/foundation_check.html", context)
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
        "status": "queued",
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
    payload = {
        "owner_id": request.user.pk,
        "from_date": from_date.isoformat(),
        "to_date": to_date.isoformat(),
        "references": context["references"],
    }
    cache.set(foundation_payload_key(job_id), payload, timeout=FOUNDATION_JOB_TTL_SECONDS)
    try:
        from .tasks import check_foundation_task

        check_foundation_task.apply_async(args=[str(job_id)])
    except Exception:
        logger.warning("Foundation check could not be queued", exc_info=True)
        job_state.update(status="failed", error_code="queue_unavailable")
        cache.set(job_key, job_state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        cache.delete(foundation_payload_key(job_id))
        context["error"] = "A fila de conferência está indisponível. O texto permanece no campo; tente novamente."
        context["job_id"] = uuid.uuid4()
        return render(request, "legislation/workspace/foundation_check.html", context, status=503)
    context.update(job_status="queued", result_url=reverse("workspace:foundation_check_result", args=(job_id,)))
    return render(request, "legislation/workspace/foundation_check.html", context)


def _enrich_foundation_result(result, *, user=None):
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
        identity = reference.get("identity") or {}
        if identity.get("type") and identity.get("number") and identity.get("year"):
            try:
                reference["documentary_relation_candidates"] = _foundation_relation_candidates(
                    identity, user=user
                )
            except Exception:
                # Documentary candidates are supplemental clues. Their absence must
                # never prevent the version comparison from being displayed.
                logger.warning("Foundation relation-candidate lookup failed", exc_info=True)
        if (
            reference.get("status") == "inconclusive"
            and reference.get("reason") == "norma não localizada entre as normas consolidadas"
            and reference.get("identity", {}).get("type")
            and reference.get("identity", {}).get("number")
            and reference.get("identity", {}).get("year")
        ):
            try:
                archive_result = search_archive_documents(
                    reference["text"], page=1, include_results=True
                )
                candidates = []
                for candidate in archive_result["results"]:
                    document = candidate["document"]
                    if not local_pdf_available(document):
                        continue
                    identity = candidate.get("identity", {})
                    type_label = _tipo_label(str(identity.get("type") or ""))
                    number_label = str(identity.get("number") or "").strip()
                    year_value = identity.get("year")
                    if number_label:
                        number_label = f"nº {number_label}"
                    if number_label and year_value:
                        number_label = f"{number_label}/{year_value}"
                    pdf_url = reverse(
                        "legislation:document_pdf", args=(document.public_id,)
                    )
                    if candidate.get("excerpt_page"):
                        pdf_url += f"#page={candidate['excerpt_page']}"
                    candidates.append(
                        {
                            "label": " ".join(
                                part for part in (type_label, number_label) if part
                            ) or document.original_filename or "PDF do acervo local",
                            "filename": document.original_filename or document.entry_name,
                            "pdf_url": pdf_url,
                            "excerpt": candidate.get("excerpt", ""),
                            "extraction_status": candidate.get("extraction_status", "unknown"),
                        }
                    )
                    if len(candidates) == 3:
                        break
                if candidates:
                    reference["archive_candidates"] = candidates
                    reference["archive_candidate_count"] = archive_result.get(
                        "record_count", archive_result["count"]
                    )
            except Exception:
                # Archive discovery is supplemental: an unavailable archive search
                # must not turn a valid temporal-check result into an HTTP failure.
                logger.warning("Foundation archive candidate lookup failed", exc_info=True)
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
    return result


def _dedupe_foundation_relation_candidates(candidates):
    """Collapse exact document copies while retaining edition/device differences."""
    unique = []
    indexes = {}
    for candidate in candidates:
        key = candidate.get("_dedupe_key")
        if key not in indexes:
            indexes[key] = len(unique)
            unique.append(candidate)
            continue
        existing_index = indexes[key]
        if (
            str(candidate.get("_source_kind") or "").casefold() == "sapl"
            and str(unique[existing_index].get("_source_kind") or "").casefold() != "sapl"
        ):
            unique[existing_index] = candidate
    for candidate in unique:
        candidate.pop("_dedupe_key", None)
        candidate.pop("_source_kind", None)
    return unique


def _foundation_relation_candidates(identity, *, user=None):
    """Return exact-text, explicitly unreviewed relation clues for one cited act.

    This is not a legal-status resolver: a pending extraction candidate never
    becomes an operative event here. Only enacted normative types are eligible.
    """
    from src.apps.legislation.document_models import EventoNormativoCandidato
    from src.processing.document_metadata import is_natal_municipal_jurisdiction

    expected_type = canonical_type(str(identity.get("type") or ""))
    enacted_types = {
        "lei", "lei_complementar", "lei_organica", "lei_promulgada",
        "decreto", "decreto_legislativo", "decreto_lei", "resolucao",
        "portaria", "emenda", "emenda_constitucional",
    }
    if expected_type not in enacted_types:
        return []
    expected_number = normalize_number(str(identity.get("number") or "")).lstrip("0") or "0"
    try:
        expected_year = int(identity.get("year"))
    except (TypeError, ValueError):
        return []
    if not expected_number or not 1 <= expected_year <= 9999:
        return []

    number_aliases = {expected_number}
    for prefix_length in range(1, 4):
        number_aliases.add(("0" * prefix_length) + expected_number)
    if len(expected_number) > 3:
        number_aliases.add(
            f"{expected_number[:-3]}.{expected_number[-3:]}"
        )

    sapl_target_records = []
    seen_sapl_target_types = set()
    sapl_targets = (
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            metadata_json__identity_candidate__year=expected_year,
            metadata_json__identity_candidate__number__in=sorted(number_aliases),
        )
        .exclude(review_status=DocumentoNormativo.ReviewStatus.REJECTED)
        .only("public_id", "official_url", "metadata_json", "review_status")
    )
    for target_document in sapl_targets:
        target_metadata = (
            target_document.metadata_json
            if isinstance(target_document.metadata_json, dict)
            else {}
        )
        target_identity = target_metadata.get("identity_candidate") or {}
        target_number = (
            normalize_number(str(target_identity.get("number") or "")).lstrip("0") or "0"
        )
        target_type = canonical_type(str(target_identity.get("type") or ""))
        if (
            target_type in enacted_types
            and target_number == expected_number
            and str(target_identity.get("year") or "") == str(expected_year)
            and is_natal_municipal_jurisdiction(target_identity.get("jurisdiction"))
            and target_metadata.get("synthetic") is not True
            and target_metadata.get("synthetic_fixture") is not True
        ):
            if target_type not in seen_sapl_target_types:
                sapl_target_records.append((target_document, target_identity, target_type))
                seen_sapl_target_types.add(target_type)

    rows = (
        EventoNormativoCandidato.objects.filter(
            action__in=("REVOGA", "ALTERA", "SUBSTITUI", "ADICIONA"),
            target_reference_json__year_candidate=str(expected_year),
            target_reference_json__number_candidate__in=sorted(number_aliases),
        )
        .filter(
            Q(extracao_id=F("extracao__documento__accepted_extraction_id"))
            | Q(
                extracao__documento__accepted_extraction__isnull=True,
                extracao_id=Subquery(
                    ExtracaoDocumento.objects.filter(
                        documento_id=OuterRef("extracao__documento_id")
                    )
                    .order_by("-created_at", "-pk")
                    .values("pk")[:1]
                ),
            )
        )
        .select_related("extracao__documento")
        .prefetch_related("revisoes")
        .order_by("-created_at", "pk")[:500]
    )
    candidates = []
    for candidate in rows:
        target = candidate.target_reference_json or {}
        candidate_target_type = canonical_type(str(target.get("type_candidate") or ""))
        candidate_number = (
            normalize_number(str(target.get("number_candidate") or "")).lstrip("0") or "0"
        )
        if candidate_number != expected_number:
            continue
        document = candidate.extracao.documento
        document_metadata = (
            document.metadata_json if isinstance(document.metadata_json, dict) else {}
        )
        source_identity = document_metadata.get("identity_candidate") or {}
        source_type = canonical_type(str(source_identity.get("type") or ""))
        if (
            document.source_kind
            not in {
                DocumentoNormativo.SourceKind.SAPL,
                DocumentoNormativo.SourceKind.ARCHIVE,
            }
            or source_type not in enacted_types
            or document_metadata.get("synthetic") is True
            or document_metadata.get("synthetic_fixture") is True
            or source_identity.get("synthetic") is True
            or source_identity.get("synthetic_fixture") is True
            or not is_natal_municipal_jurisdiction(source_identity.get("jurisdiction"))
            or document.review_status == DocumentoNormativo.ReviewStatus.REJECTED
        ):
            continue
        try:
            source_year = int(source_identity.get("year"))
        except (TypeError, ValueError):
            continue
        source_number = normalize_number(str(source_identity.get("number") or ""))
        if not source_number or not source_year:
            continue

        latest_review = candidate.revisoes.order_by("-created_at", "-pk").first()
        if latest_review and latest_review.decision == "reject":
            continue
        evidence = candidate.evidence_json or {}
        exact_target_quote = evidence.get("target_quote") or candidate.target_text
        exact_action_quote = evidence.get("action_quote") or candidate.action_quote
        page = evidence.get("target_page") or evidence.get("action_page")
        source_pdf_url = _pgm_document_pdf_url(document, page, user=user)
        source_type_label = _tipo_label(str(source_identity.get("type") or ""))
        source_label = f"{source_type_label} nº {source_identity.get('number')}/{source_year}"
        article = target.get("structural_article_number")
        identity_conflict = bool(sapl_target_records) and (
            candidate_target_type != expected_type
            or any(
                catalog_type != expected_type or catalog_type != candidate_target_type
                for _document, _identity, catalog_type in sapl_target_records
            )
        )
        if candidate_target_type != expected_type and not identity_conflict:
            continue
        target_catalog_records = []
        for target_document, target_identity, _catalog_type in sapl_target_records:
            target_catalog_records.append(
                {
                    "label": (
                        f"{_tipo_label(str(target_identity.get('type') or ''))} nº "
                        f"{target_identity.get('number')}/{target_identity.get('year')}"
                    ),
                    "pdf_url": _pgm_document_pdf_url(target_document, user=user),
                }
            )
        registry_evidence = _pgm_lc258_sapl_registry_evidence(
            expected_number, expected_year, candidate_target_type
        )
        known_year_conflicts = [
            record
            for record in registry_evidence["records"]
            if not record["year_match"]
        ]
        for record in known_year_conflicts:
            label = f"{record['type_display']} nº {expected_number}/{record['year']}"
            if not any(existing["label"] == label for existing in target_catalog_records):
                target_catalog_records.append(
                    {
                        "label": label,
                        "pdf_url": record["url"],
                        "year_conflict": True,
                    }
                )
        target_official_sources = registry_evidence["official_sources"]
        target_identity_conflict = any(
            source.get("identity_conflict") for source in target_official_sources
        )
        target_catalog_label = "; ".join(
            dict.fromkeys(record["label"] for record in target_catalog_records)
        ) or None
        candidate_view = {
            "action": candidate.action,
            "source_label": source_label,
            "source_device": candidate.source_device_label,
            "target_scope": "article" if article else "act",
            "target_device": (
                f"{target.get('structural_type')} {target.get('structural_number')}"
                if target.get("structural_type") and target.get("structural_number")
                else None
            ),
            "target_text": exact_target_quote,
            "action_quote": exact_action_quote,
            "status": "identity_conflict" if identity_conflict else "candidate_unreviewed",
            "identity_conflict": identity_conflict,
            "target_identity_conflict": target_identity_conflict,
            "target_catalog_label": target_catalog_label,
            "target_catalog_records": target_catalog_records,
            "target_official_sources": target_official_sources,
            "review_url": _pgm_document_review_url(document, user),
            "pdf_url": source_pdf_url or safe_official_url(document.official_url),
            "page": page,
            "review_decision": latest_review.decision if latest_review else None,
            "_source_kind": document.source_kind,
            "_dedupe_key": (
                source_label.casefold(),
                str(candidate.action or "").casefold(),
                str(candidate.source_device_label or "").casefold(),
                "article" if article else "act",
                str(target.get("structural_type") or "").casefold(),
                str(target.get("structural_number") or "").casefold(),
                re.sub(r"\s+", " ", str(exact_action_quote or "")).casefold(),
                re.sub(r"\s+", " ", str(exact_target_quote or "")).casefold(),
                re.sub(
                    r"\s+",
                    " ",
                    str(
                        document_metadata.get("edition_label")
                        or document_metadata.get("edition")
                        or document_metadata.get("version_label")
                        or ""
                    ),
                ).casefold(),
            ),
            "_candidate_model": candidate,
        }
        candidates.append(candidate_view)
    candidates = _dedupe_foundation_relation_candidates(candidates)
    for candidate_view in candidates:
        candidate_model = candidate_view.pop("_candidate_model", None)
        if candidate_model and candidate_model.action in {"ALTERA", "SUBSTITUI"}:
            candidate_view["amendment_comparison"] = _foundation_amendment_comparison(
                candidate_model, user=user
            )
    return candidates[:5]


def _foundation_amendment_comparison(candidate, *, user=None):
    """Build a non-operative before/after preview only from exact municipal acts."""
    from src.apps.legislation.document_relation_review import candidate_target_documents

    target = candidate.target_reference_json or {}
    article_number = str(
        target.get("structural_article_number")
        or (target.get("structural_number") if target.get("structural_type") == "artigo" else "")
        or ""
    ).strip()
    device_type = str(target.get("structural_type") or "").casefold()
    device_number = str(target.get("structural_number") or "").strip()
    if not article_number or device_type not in {"artigo", "paragrafo"}:
        return None

    source_article_match = re.search(r"(?i)artigo\s+(\d+)", candidate.source_device_label or "")
    if not source_article_match:
        return None
    source_extraction = candidate.extracao
    source_article_number = source_article_match.group(1)
    amendment_quote = (
        _pgm_replacement_article_evidence(
            source_extraction, source_article_number, article_number
        )
        if device_type == "artigo"
        else _pgm_replacement_paragraph_evidence(
            source_extraction,
            source_article_number,
            article_number,
            device_number,
        )
    )
    if not amendment_quote:
        return None

    target_documents = []
    for item in candidate_target_documents(candidate):
        document = item["document"]
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        identity = metadata.get("identity_candidate")
        if not isinstance(identity, dict):
            continue
        if (
            not item["type_matches"]
            or document.source_kind != DocumentoNormativo.SourceKind.SAPL
            or document.review_status == DocumentoNormativo.ReviewStatus.REJECTED
            or metadata.get("synthetic") is True
            or metadata.get("synthetic_fixture") is True
            or identity.get("synthetic") is True
            or identity.get("synthetic_fixture") is True
        ):
            continue
        target_documents.append(document)
    if len(target_documents) != 1:
        return None
    target_document = target_documents[0]
    target_extraction = target_document.extracoes.filter(
        status=ExtracaoDocumento.Status.COMPLETE
    ).order_by("-created_at", "-pk").first()
    if target_extraction is None:
        return None
    original_quote = (
        _pgm_article_evidence(target_extraction, article_number)
        if device_type == "artigo"
        else _pgm_paragraph_evidence(target_extraction, article_number, device_number)
    )
    if not original_quote:
        return None
    original_pdf_url = _pgm_document_pdf_url(
        target_document, original_quote.get("page"), user=user
    )
    amendment_pdf_url = _pgm_document_pdf_url(
        source_extraction.documento, amendment_quote.get("page"), user=user
    )
    if not original_pdf_url or not amendment_pdf_url:
        return None
    original_identity = (
        (target_document.metadata_json or {}).get("identity_candidate") or {}
    )
    amendment_identity = (
        (source_extraction.documento.metadata_json or {}).get("identity_candidate") or {}
    )
    device_label = (
        f"Art. {article_number}"
        if device_type == "artigo"
        else f"Art. {article_number}, § {device_number}"
    )
    return {
        "device_label": device_label,
        "original_text": original_quote["quote"],
        "original_label": (
            f"{_tipo_label(str(original_identity.get('type') or 'Ato'))} nº "
            f"{original_identity.get('number')}/{original_identity.get('year')} · {device_label}"
        ),
        "original_pdf_url": original_pdf_url,
        "amended_text": amendment_quote["quote"],
        "amended_label": (
            f"{_tipo_label(str(amendment_identity.get('type') or 'Ato'))} nº "
            f"{amendment_identity.get('number')}/{amendment_identity.get('year')} · "
            f"{candidate.source_device_label}"
        ),
        "amended_pdf_url": amendment_pdf_url,
        "status": "candidate_unreviewed",
    }


@login_required(login_url="workspace:login")
def foundation_check_status_view(request, job_id):
    state = cache.get(_foundation_job_key(job_id))
    if not state or state.get("owner_id") != request.user.pk:
        return JsonResponse({"error": "Conferência não encontrada."}, status=404)
    return JsonResponse({key: value for key, value in state.items() if key != "owner_id"})


@login_required(login_url="workspace:login")
def foundation_check_result_view(request, job_id):
    state = cache.get(_foundation_job_key(job_id))
    if not state or state.get("owner_id") != request.user.pk or state.get("status") != "completed":
        raise Http404
    if not cache.get(foundation_result_key(job_id)):
        raise Http404
    url = reverse("workspace:foundation_check")
    return redirect(f"{url}?action=result&job_id={job_id}")


@login_required(login_url="workspace:login")
@require_POST
def foundation_check_cancel_view(request, job_id):
    key = _foundation_job_key(job_id)
    state = cache.get(key)
    if not state or state.get("owner_id") != request.user.pk:
        return JsonResponse({"error": "Conferência não encontrada."}, status=404)
    if state.get("status") in {"queued", "running"}:
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
            Q(
                documento_base__isnull=False,
                dispositivos__alteracoes_causadas__is_active=True,
            )
            | Q(
                documentos_normativos__review_status__in={
                    DocumentoNormativo.ReviewStatus.PENDING,
                    DocumentoNormativo.ReviewStatus.IN_REVIEW,
                },
                documentos_normativos__accepted_extraction__isnull=True,
                documentos_normativos__extracoes__eventos_normativos_candidatos__isnull=False,
            )
        ).distinct()
        if include_pending_relations
        else consolidated_normas_for_product()
    ).select_related("documento_base")
    if include_pending_relations:
        candidate_document = DocumentoNormativo.objects.filter(
            norma_id=OuterRef("pk"),
            review_status__in={
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            },
            accepted_extraction__isnull=True,
            extracoes__eventos_normativos_candidatos__isnull=False,
        ).order_by("-created_at", "-pk")
        norms = norms.annotate(
            candidate_document_public_id=Subquery(
                candidate_document.values("public_id")[:1]
            )
        )
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

    selected_candidate_document = None
    raw_candidate_document_id = request.GET.get("documento", "").strip()
    if raw_candidate_document_id:
        if not include_pending_relations or not can_view_candidates:
            return HttpResponseForbidden("Permissão insuficiente para consultar relações candidatas.")
        try:
            candidate_public_id = uuid.UUID(raw_candidate_document_id)
        except (TypeError, ValueError, AttributeError):
            raise Http404 from None
        selected_candidate_document = DocumentoNormativo.objects.filter(
            public_id=candidate_public_id,
            source_kind__in={
                DocumentoNormativo.SourceKind.ARCHIVE,
                DocumentoNormativo.SourceKind.SAPL,
            },
            review_status__in={
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            },
            accepted_extraction__isnull=True,
        ).first()
        if selected_candidate_document is None:
            raise Http404
        candidate_metadata = (
            selected_candidate_document.metadata_json
            if isinstance(selected_candidate_document.metadata_json, dict)
            else {}
        )
        candidate_identity = candidate_metadata.get("identity_candidate")
        candidate_identity = candidate_identity if isinstance(candidate_identity, dict) else {}
        if any(
            candidate_metadata.get(key) is True or candidate_identity.get(key) is True
            for key in ("synthetic", "synthetic_fixture")
        ):
            raise Http404

    candidate_documents_page = None
    candidate_document_count = 0
    if include_pending_relations:
        latest_document_extraction = ExtracaoDocumento.objects.filter(
            documento_id=OuterRef("pk")
        ).order_by("-created_at", "-pk")
        candidate_documents = (
            DocumentoNormativo.objects.filter(
                norma__isnull=True,
                source_kind__in={
                    DocumentoNormativo.SourceKind.ARCHIVE,
                    DocumentoNormativo.SourceKind.SAPL,
                },
                review_status__in={
                    DocumentoNormativo.ReviewStatus.PENDING,
                    DocumentoNormativo.ReviewStatus.IN_REVIEW,
                },
                accepted_extraction__isnull=True,
            )
            .filter(
                (Q(metadata_json__synthetic__isnull=True) | Q(metadata_json__synthetic=False))
                & (
                    Q(metadata_json__synthetic_fixture__isnull=True)
                    | Q(metadata_json__synthetic_fixture=False)
                )
                & (
                    Q(metadata_json__identity_candidate__synthetic__isnull=True)
                    | Q(metadata_json__identity_candidate__synthetic=False)
                )
                & (
                    Q(metadata_json__identity_candidate__synthetic_fixture__isnull=True)
                    | Q(metadata_json__identity_candidate__synthetic_fixture=False)
                )
            )
            .annotate(
                latest_extraction_id=Subquery(
                    latest_document_extraction.values("pk")[:1]
                ),
                latest_extraction_status=Subquery(
                    latest_document_extraction.values("status")[:1]
                ),
            )
            .filter(
                latest_extraction_status=ExtracaoDocumento.Status.COMPLETE,
                extracoes__pk=F("latest_extraction_id"),
                extracoes__eventos_normativos_candidatos__isnull=False,
            )
            .annotate(
                pending_relation_count=Count(
                    "extracoes__eventos_normativos_candidatos",
                    filter=Q(
                        extracoes__eventos_normativos_candidatos__revisoes__isnull=True
                    ),
                    distinct=True,
                )
            )
            .filter(pending_relation_count__gt=0)
        )
        if query:
            candidate_documents = candidate_documents.filter(
                Q(original_filename__icontains=query)
                | Q(source_ref__icontains=query)
                | Q(metadata_json__identity_candidate__number__icontains=query)
            )
        if norma_type:
            candidate_documents = candidate_documents.filter(
                metadata_json__identity_candidate__type__icontains=norma_type
            )
        if year:
            candidate_documents = candidate_documents.filter(
                Q(metadata_json__identity_candidate__year=str(year))
                | Q(metadata_json__identity_candidate__year=year)
            )
        candidate_documents = candidate_documents.order_by("-created_at", "pk")
        candidate_document_paginator = Paginator(candidate_documents, 20)
        candidate_document_count = candidate_document_paginator.count
        candidate_documents_page = candidate_document_paginator.get_page(
            request.GET.get("documentos_page", "1")
        )

    paginator = Paginator(norms, 20)
    page = paginator.get_page(request.GET.get("page", "1"))

    query_params = request.GET.copy()
    for key in ("page", "norma", "documentos_page", "documento"):
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
            "selected_candidate_document": selected_candidate_document,
            "candidate_documents_page": candidate_documents_page,
            "candidate_document_count": candidate_document_count,
            "include_pending_relations": include_pending_relations,
            "can_view_candidates": can_view_candidates,
            "normative_graph_enabled": getattr(settings, "NORMATIVE_GRAPH_ENABLED", False),
            "normative_history_enabled": getattr(settings, "NORMATIVE_HISTORY_ENABLED", False),
            "pgm_consolidation_demo_enabled": bool(
                getattr(settings, "DEBUG", False)
                and getattr(settings, "PGM_CONSOLIDATION_DEMO_ENABLED", False)
            ),
            "query_string": query_params.urlencode(),
            "active_nav": "explore",
        },
    )


def normative_casefile_view(request, pk: int):
    """Show a reviewed, date-scoped dossier using shared projection/graph/evidence services."""
    if not getattr(settings, "NORMATIVE_HISTORY_ENABLED", False):
        raise Http404("A ficha temporal não está habilitada nesta instalação.")
    norma = (
        consolidated_normas_for_product()
        .select_related("documento_base__accepted_extraction")
        .filter(pk=pk)
        .first()
    )
    if norma is None:
        raise Http404("Norma consolidada não encontrada.")

    from src.processing.normative_casefile import build_normative_casefile
    from src.processing.temporal_scope import build_norma_timeline

    as_of_raw = request.GET.get("as_of", "").strip()[:10]
    as_of = parse_date(as_of_raw) if as_of_raw else timezone.localdate()
    error = ""
    casefile = None
    timeline = []
    if as_of is None:
        error = "Informe a data no formato AAAA-MM-DD."
    elif as_of > timezone.localdate():
        error = "A data de referência não pode estar no futuro."
    else:
        casefile = build_normative_casefile(norma, as_of=as_of)
        timeline = build_norma_timeline(norma, as_of=as_of)

    projection_status_labels = {
        "complete": "Projeção completa dentro do escopo revisado",
        "partial": "Projeção parcial — há eventos ou dispositivos pendentes",
        "not_reconstructable": "Não foi possível reconstruir esta data com segurança",
    }
    return render(
        request,
        "legislation/workspace/normative_casefile.html",
        {
            "norma": norma,
            "casefile": casefile,
            "as_of": as_of.isoformat() if as_of else as_of_raw,
            "error": error,
            "timeline": timeline,
            "projection_status_label": (
                projection_status_labels.get(casefile["projection"].status, "Estado desconhecido")
                if casefile
                else ""
            ),
            "normative_graph_enabled": getattr(settings, "NORMATIVE_GRAPH_ENABLED", False),
            "active_nav": "explore",
        },
    )


def pgm_project_gold_view(request):
    """Browse the frozen AI-adjudicated benchmark without promoting QA documents."""
    if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
        raise Http404("A coleção de avaliação não está habilitada nesta instalação.")

    reference_root = (
        Path(__file__).resolve().parents[3]
        / "benchmarks"
        / "corpus"
        / "municipal_natal"
        / "ai-adjudicated-20261018-v1"
        / "reference"
    )
    try:
        origins = [
            json.loads(line)
            for line in (reference_root / "source-origins.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        annotations = {
            row["annotation"]["annotation_id"].split(":")[1]: row["annotation"]
            for row in (
                json.loads(line)
                for line in (reference_root / "annotations.ai-adjudicated.jsonl")
                .read_text(encoding="utf-8")
                .splitlines()
                if line.strip()
            )
        }
        queries = [
            json.loads(line)
            for line in (reference_root / "queries.ai.jsonl").read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.exception("Unable to load the versioned PGM project gold package")
        raise Http404("A coleção de avaliação está indisponível.") from exc

    hashes = {
        row.get("document_key", "").removeprefix("sha256:")
        for row in origins
        if isinstance(row.get("document_key"), str)
    }
    documents = {
        document.content_sha256: document
        for document in DocumentoNormativo.objects.filter(content_sha256__in=hashes)
    }
    type_labels = {
        "lei": "Lei",
        "lei_complementar": "Lei Complementar",
        "lei_ordinaria": "Lei Ordinária",
        "lei_promulgada": "Lei Promulgada",
        "decreto": "Decreto",
        "decreto_legislativo": "Decreto Legislativo",
    }
    device_labels = {
        "art": "Art.",
        "artigo": "Art.",
        "par": "§",
        "paragrafo": "§",
        "inciso": "inciso",
        "alinea": "alínea",
        "item": "item",
    }
    cases = []
    for origin in origins:
        key_parts = str(origin.get("norma_key", "")).split("|")
        if len(key_parts) != 4:
            continue
        _, type_key, number, year = key_parts
        unit_id = str(origin.get("unit_id", ""))
        annotation = annotations.get(unit_id, {})
        annotation_events = annotation.get("events", [])
        spans = annotation.get("spans", [])
        devices = []
        for span in spans:
            device_key = str(span.get("device_key", ""))
            device_type, separator, device_number = device_key.partition(":")
            if not separator:
                continue
            label = device_labels.get(device_type.casefold(), device_type.capitalize())
            devices.append(f"{label} {device_number}".strip())
        document = documents.get(str(origin.get("document_key", "")).removeprefix("sha256:"))
        public_sapl_candidate = bool(
            document
            and document.source_kind == DocumentoNormativo.SourceKind.SAPL
            and document.review_status != DocumentoNormativo.ReviewStatus.APPROVED
            and document.official_url
        )
        queries_for_case = [row for row in queries if unit_id in row.get("expected_unit_ids", [])]
        formatted_number = f"{int(number):,}".replace(",", ".") if number.isdigit() else number
        cases.append(
            {
                "unit_id": unit_id,
                "label": f"{type_labels.get(type_key, 'Norma')} nº {formatted_number}/{year}",
                "norma_key": origin.get("norma_key", ""),
                "devices": devices,
                "event_count": len(annotation_events),
                "query_count": len(queries_for_case),
                "document": document,
                "evidence_url": (
                    document.official_url
                    if public_sapl_candidate
                    else reverse("legislation:document_evidence", kwargs={"document_id": document.public_id})
                    if document
                    else ""
                ),
                "external_source": public_sapl_candidate,
                "source_label": (
                    "PDF oficial SAPL · candidato não revisado"
                    if public_sapl_candidate
                    else f"PDF correspondente no QA · {document.get_review_status_display()}"
                    if document
                    else "PDF não disponível no QA"
                ),
                "review_status": document.get_review_status_display() if document else "PDF não disponível no QA",
                "is_unresolved_case": any(
                    query.get("expected_abstain") for query in queries_for_case
                ),
            }
        )

    return render(
        request,
        "legislation/workspace/pgm_project_gold.html",
        {
            "cases": cases,
            "gold_id": "jurix-pgm-gold-v1",
            "active_nav": "explore",
        },
    )


def ai_pilot_adoptions_view(request):
    """Show explicitly adopted AI-review scopes as a separate pilot evidence graph."""
    adoptions = list(
        AIPilotAdoption.objects.filter(decision="adopted_for_pilot")
        .select_related("norma")
        .order_by("case_key", "revision")
    )
    public_ids = {
        source.get("document_id")
        for adoption in adoptions
        for source in adoption.evidence_json.get("sources", [])
        if source.get("document_id")
    }
    documents = {
        str(document.public_id): document
        for document in DocumentoNormativo.objects.filter(public_id__in=public_ids)
    }
    case_labels = dict(AIPilotAdoption.Case.choices)
    cases = []
    for adoption in adoptions:
        payload = adoption.evidence_json
        source_by_id = {row.get("source_id"): row for row in payload.get("sources", [])}
        events = []
        for event in payload.get("events", []):
            evidence = event.get("evidence") or {}
            source = source_by_id.get(evidence.get("source_id"), {})
            target = event.get("target")
            if isinstance(target, dict):
                target_label = target.get("confirmed_identity") or target.get("literal_target") or str(target)
            else:
                target_label = str(target or "Alvo não especificado")
            source_label = source.get("title") or f"Fonte {evidence.get('source_id', '')}"
            source_href = safe_official_url(source.get("url"))
            local_document = documents.get(str(source.get("document_id") or ""))
            local_href = (
                reverse("legislation:document_pdf", args=(local_document.public_id,))
                if local_document
                else ""
            )
            events.append(
                {
                    "key": event.get("relation_key"),
                    "action": event.get("action"),
                    "article": evidence.get("article"),
                    "target": target_label,
                    "resolution": event.get("target_resolution"),
                    "assessment": event.get("documentary_assessment", ""),
                    "quote": evidence.get("quote", ""),
                    "pages": evidence.get("pages", []),
                    "source_label": source_label,
                    "source_href": source_href,
                    "local_href": local_href,
                    "pdf_sha256": source.get("pdf_sha256", ""),
                }
            )
        cases.append(
            {
                "key": adoption.case_key,
                "label": case_labels.get(adoption.case_key, adoption.case_key),
                "revision": adoption.revision,
                "adopted_on": adoption.adopted_on,
                "norma": adoption.norma,
                "review_draft_sha256": adoption.review_draft_sha256,
                "report_sha256": adoption.review_report_sha256,
                "events": events,
                "limitations": adoption.limitations_json,
                "conflict_case": adoption.case_key == AIPilotAdoption.Case.LC55_CONFLICT,
            }
        )
    return render(
        request,
        "legislation/workspace/ai_pilot_adoptions.html",
        {"cases": cases, "active_nav": "explore"},
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


def _pgm_article_evidence(extraction, article_number: str) -> dict | None:
    """Return an exact-source article excerpt and PDF page without promoting it."""
    if extraction is None:
        return None
    matches = list(
        re.finditer(
            rf"(?im)^[ \t]*Art\.?[ \t]*{re.escape(str(article_number))}"
            r"[ºª°]?(?![\w-])[ \t]*[.–-]?[ \t]*",
            extraction.legal_text or "",
        )
    )
    if not matches:
        return None
    match = matches[0]
    next_article = re.compile(
        r"(?im)^[ \t]*Art\.?[ \t]*\d+(?:-[A-Z])?[ºª°]?[ \t]*[.–-]?[ \t]*",
    ).search(extraction.legal_text or "", match.end())
    end = next_article.start() if next_article else len(extraction.legal_text or "")
    closing_note = re.search(
        r"\bPal[áa]cio\s+Felipe\s+Camar[aã]o\s*,\s+em\s+Natal\s*,|"
        r"\b(?:Sala\s+das\s+Sessões\s*,|"
        r"Publicada\s+no\s+Diário\s+Oficial(?:\s+do\s+Município)?\s*(?:em)?\s*:|"
        r"Autoria\s*:)(?=\s|$)|"
        r"^[ \t]*ANEXO(?:S)?[ \t]+[A-Z0-9IVXLCDM]+\b",
        (extraction.legal_text or "")[match.end() : end],
        flags=re.IGNORECASE | re.MULTILINE,
    )
    if closing_note:
        end = min(end, match.end() + closing_note.start())
    raw_excerpt = (extraction.legal_text or "")[match.start():end].strip()
    from src.processing.legal_parser import LegalTextParser

    cleaned_excerpt = LegalTextParser.strip_page_artifacts(raw_excerpt)
    cleaned_excerpt = re.sub(
        r"(?im)^[ \t]*(?:PAL[AÁ]CIO\s+FELIPE\s+CAMAR[AÃ]O|"
        r"RUA\s+ULISSES\s+CALDAS,?\s*81,?\s*CENTRO,?\s*59025-090|"
        r"\(?84\)?\s*3232[.]8845,?\s*www[.]natal[.]rn[.]gov[.]br)[ \t]*$",
        "",
        cleaned_excerpt,
    )
    quote = re.sub(r"\s+", " ", cleaned_excerpt).strip()
    page = next(
        (
            span.get("page")
            for span in extraction.page_map_json or []
            if isinstance(span, dict)
            and span.get("start", 0) <= match.start() < span.get("end", 0)
        ),
        None,
    )
    return {"quote": quote, "page": page if isinstance(page, int) else None}


def _pgm_clean_extracted_legal_quote(quote: str) -> str:
    """Normalize obvious PDF page-number/ordinal artifacts in display-only excerpts."""
    cleaned = re.sub(r";\s*\d{1,4}\s+(?=II\s*[–—-])", "; ", quote or "")
    cleaned = re.sub(r"§\s*(\d+)\s*o\b", r"§ \1º", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(§\s*\d+º)\s*[-–—.]+\s*", r"\1 — ", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


def _pgm_lc55_original_article_context(candidate, *, user):
    """Return only an Art. 34 quote actually present in the extracted source."""
    evidence = candidate.get("evidence") if isinstance(candidate, dict) else None
    quote = evidence.get("quote") if isinstance(evidence, dict) else None
    if not isinstance(quote, str) or not quote.strip():
        return None

    document = candidate.get("document")
    extraction = candidate.get("extraction")
    page = evidence.get("page")
    return {
        "quote": _pgm_clean_extracted_legal_quote(quote),
        "page": page if isinstance(page, int) and page > 0 else None,
        "source_label": "Texto original promulgado · Biblioteca Virtual do Natal",
        "pdf_url": _pgm_document_pdf_url(document, page, user=user)
        or PGM_LC55_ORIGINAL_OFFICIAL_PDF,
        "official_pdf_url": PGM_LC55_ORIGINAL_OFFICIAL_PDF,
        "document": document,
        "review_status": document.get_review_status_display() if document else None,
        "extraction_status": extraction.status if extraction else None,
    }


def _pgm_source_page_for_quote(extraction, quote: str, *, after_article: str | None = None):
    """Locate the page where quoted replacement wording starts in the source text."""
    source_text = extraction.legal_text or ""
    search_start = 0
    if after_article is not None:
        article_match = re.search(
            rf"(?im)^[ \t]*Art\.?[ \t]*{re.escape(str(after_article))}"
            r"[ºª°]?(?![\w-])[ \t]*[.–-]?[ \t]*",
            source_text,
        )
        if article_match is None:
            return None
        search_start = article_match.start()

    tokens = str(quote or "").split()
    if not tokens:
        return None
    quote_pattern = re.compile(r"\s+".join(re.escape(token) for token in tokens), re.IGNORECASE)
    quote_match = quote_pattern.search(source_text, search_start)
    if quote_match is None:
        return None
    for span in extraction.page_map_json or []:
        if (
            isinstance(span, dict)
            and span.get("start", 0) <= quote_match.start() < span.get("end", 0)
        ):
            page = span.get("page")
            return page if isinstance(page, int) else None
    return None


def _pgm_replacement_article_evidence(
    extraction, amendment_article_number: str, replaced_article_number: str
) -> dict | None:
    """Extract the quoted replacement wording without treating it as approved law."""
    if extraction is None:
        return None
    source_text = extraction.legal_text or ""
    amendment_match = re.search(
        rf"(?im)^[ \t]*Art\.?[ \t]*{re.escape(str(amendment_article_number))}"
        r"[ºª°]?(?![\w-])[ \t]*[.–-]?[ \t]*",
        source_text,
    )
    if amendment_match is None:
        return None

    # The article being amended (e.g. Art. 20) may itself be printed at the
    # start of a line inside the amending article's quotation. Find the next
    # external article boundary only after the closing quote of that block.
    amendment_number = re.fullmatch(r"\s*(\d+)[ºª°]?\s*", str(amendment_article_number))
    amendment_end = None
    if amendment_number:
        next_number = str(int(amendment_number.group(1)) + 1)
        outer_candidates = re.finditer(
            rf"(?im)^[ \t]*Art\.?[ \t]*{re.escape(next_number)}"
            r"[ºª°]?(?![\w-])[ \t]*[.–-]?[ \t]*",
            source_text[amendment_match.end() :],
        )
        for outer in outer_candidates:
            boundary = amendment_match.end() + outer.start()
            prefix = source_text[amendment_match.start() : boundary]
            closing_quotes = [prefix.rfind(char) for char in "\"”»’'"]
            last_closing_quote = max(closing_quotes)
            tail = prefix[last_closing_quote + 1 :] if last_closing_quote >= 0 else prefix
            if last_closing_quote >= 0 and re.fullmatch(r"[\s.\u2026\uFFFD]*", tail):
                amendment_end = boundary
                break

    if amendment_end is not None:
        amendment_quote = re.sub(
            r"\s+", " ", source_text[amendment_match.start() : amendment_end]
        ).strip()
    else:
        amendment = _pgm_article_evidence(extraction, amendment_article_number)
        if amendment is None:
            return None
        amendment_quote = amendment["quote"]
    match = re.search(
        rf"(?i)(?:[\"“«]\s*|\.(?:\s*\.){{5,}}[\uFFFD…]*\s*|…{{2,}}\s*)"
        rf"(Art\.?\s*{re.escape(str(replaced_article_number))}"
        rf"\b[ºª°]?\s*\.?)",
        amendment_quote,
    )
    if match is None:
        return None
    replacement = amendment_quote[match.start(1) :].strip()
    replacement = re.sub(r"^[\"'“‘«]+", "", replacement)
    replacement = re.sub(r"[\"'”’»]+$", "", replacement).strip()
    # In amendment acts, dotted leaders often separate one replaced article
    # from the next (e.g. Art. 20 ... Art. 23). They are not part of the first
    # article and must not make later replacements look like its text.
    next_replacement = re.search(
        r"(?:\.(?:\s*\.){5,}[\uFFFD…]*|…{2,})\s*"
        r"(?=Art\.?\s*\d+(?:-[A-Z])?[ºª°]?\b)",
        replacement,
        flags=re.IGNORECASE,
    )
    if next_replacement:
        boundary_start = next_replacement.start()
        # The PDF extractor may join the final sentence period with the dotted
        # leader. Keep that punctuation while dropping only the separator.
        if (
            replacement[boundary_start : boundary_start + 1] == "."
            and replacement[boundary_start + 1 : boundary_start + 2].isspace()
        ):
            boundary_start += 1
        replacement = replacement[:boundary_start].rstrip()

    trailing_omission = re.search(
        r"(?:\.(?:\s*\.){5,}[\uFFFD…]*|…{2,})\s*$", replacement
    )
    omitted_following_text = bool(trailing_omission)
    if trailing_omission:
        replacement = replacement[: trailing_omission.start()].rstrip()

    # A dotted leader inside the extracted article means the amending act
    # omitted part of that device; keep that incompleteness explicit. The
    # separator removed above is deliberately excluded from this test.
    heading_end = re.match(r"(?is)^Art\.?\s*\d+(?:-[A-Z])?[ºª°]?\s*[.–-]?", replacement)
    body = replacement[heading_end.end() :] if heading_end else replacement
    omitted_following_text = omitted_following_text or bool(
        re.search(r"\.(?:\s*\.){5,}[\uFFFD…]*|…{2,}", body)
    )
    if not replacement or not re.match(
        rf"(?i)^Art\.?\s*{re.escape(str(replaced_article_number))}\b", replacement
    ):
        return None
    page = _pgm_source_page_for_quote(
        extraction, replacement, after_article=amendment_article_number
    )
    return {
        "quote": replacement,
        "page": page or amendment["page"],
        "omitted_following_text": omitted_following_text,
    }


def _pgm_ctm_art20_candidate_timeline(*, user=None) -> dict:
    """Build a read-only, source-linked comparison of CTM Art. 20 candidates."""
    editions = (
        ("snapshot_2021", "Consolidação municipal · exercício 2021", 2021),
        ("snapshot_2022", "Consolidação municipal · exercício 2022", 2022),
        ("snapshot_2024", "Consolidação municipal · exercício 2024", 2024),
    )
    rows = []
    for key, label, edition_year in editions:
        documents = list(
            DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                review_status=DocumentoNormativo.ReviewStatus.PENDING,
                accepted_extraction__isnull=True,
                metadata_json__identity_key="BR-RN-NATAL|lei|municipal_lo|3882|1989",
                metadata_json__edition_candidate__kind="official_consolidated_text",
                metadata_json__edition_candidate__declared_value_year=edition_year,
            ).order_by("pk")[:2]
        )
        if len(documents) != 1:
            rows.append({"key": key, "label": label, "state": "ambiguous" if documents else "missing"})
            continue
        document = documents[0]
        extraction = document.extracoes.filter(
            status=ExtracaoDocumento.Status.COMPLETE
        ).order_by("-created_at", "-pk").first()
        evidence = _pgm_article_evidence(extraction, "20")
        if evidence:
            evidence["quote"] = re.sub(
                r"\s+(?:T[IÍ]TULO|CAP[IÍ]TULO|SE[CÇ][AÃ]O|SUBSE[CÇ][AÃ]O)\s+"
                r"(?:[IVXLCDM]+|\d+)\b.*$",
                "",
                evidence["quote"],
                flags=re.IGNORECASE,
            ).strip()
        rows.append({
            "key": key,
            "label": label,
            "state": "candidate" if evidence else "text_not_found",
            "document": document,
            "extraction": extraction,
            "evidence": evidence,
            "pdf_url": _pgm_document_pdf_url(
                document, evidence["page"] if evidence else None, user=user
            ),
            "official_pdf_url": safe_official_url(document.official_url),
        })

    amendment_documents = list(
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
            metadata_json__identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|271|2025",
        ).order_by("pk")[:2]
    )
    if len(amendment_documents) != 1:
        rows.append({
            "key": "amendment_2025",
            "label": "LC nº 271/2025 · Art. 1º",
            "state": "ambiguous" if amendment_documents else "missing",
        })
    else:
        document = amendment_documents[0]
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        edition = metadata.get("edition_candidate")
        edition = edition if isinstance(edition, dict) else {}
        extraction = document.extracoes.filter(
            status=ExtracaoDocumento.Status.COMPLETE
        ).order_by("-created_at", "-pk").first()
        evidence = _pgm_replacement_article_evidence(extraction, "1", "20")
        relation_evidence = _pgm_ctm_art20_relation_candidate(document, user=user)
        sapl_publication_date = edition.get("sapl_record_publication_date")
        pdf_publication_date = edition.get("pdf_colophon_publication_date")
        dom_publication = PGM_LC271_DOM_PUBLICATION
        rows.append({
            "key": "amendment_2025",
            "label": "LC nº 271/2025 · Art. 1º (redação substitutiva do Art. 20)",
            "state": "candidate" if evidence else "text_not_found",
            "document": document,
            "extraction": extraction,
            "evidence": evidence,
            "relation_evidence": relation_evidence,
            "publication_evidence": {
                **dom_publication,
                "sapl_record_date": sapl_publication_date,
                "sapl_date_matches_dom": sapl_publication_date == dom_publication["date"].isoformat(),
                "pdf_colophon_date": pdf_publication_date,
                "pdf_colophon_differs": pdf_publication_date != dom_publication["date"].isoformat(),
                # Art. 6 expressly makes the initial effective date the publication date.
                # This does not certify that no later act changed the affected devices.
                "initial_effective_date": dom_publication["date"],
                "initial_effective_date_basis": "Art. 6º: vigência na data da publicação",
            },
            "official_record_url": safe_official_url(edition.get("sapl_record_url")),
            "pdf_url": _pgm_document_pdf_url(
                document, evidence["page"] if evidence else None, user=user
            ),
            "official_pdf_url": safe_official_url(document.official_url),
        })

    available = [row for row in rows if row.get("state") == "candidate"]
    def normalized_quote(row):
        quote = (row.get("evidence") or {}).get("quote", "")
        quote = re.sub(
            r"^Art\.?\s*20\s*[ºª°]?\.?\s*[.–—-]?\s*",
            "",
            quote,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", quote).strip().casefold()

    snapshot_rows = [row for row in rows if row.get("key", "").startswith("snapshot_")]
    snapshots_match = (
        len(snapshot_rows) == len(editions)
        and all(row.get("state") == "candidate" for row in snapshot_rows)
        and len({normalized_quote(row) for row in snapshot_rows}) == 1
    )
    textual_diff = []
    if len(available) == len(editions) + 1:
        from difflib import SequenceMatcher

        def display_quote(row):
            quote = (row.get("evidence") or {}).get("quote", "")
            quote = re.sub(
                r"^Art\.?\s*20\s*[ºª°]?\s*[.–—-]?\s*",
                "",
                quote,
                flags=re.IGNORECASE,
            )
            return re.sub(r"\s+", " ", quote).strip()

        before = re.findall(r"\s+|[^\s]+", display_quote(available[-2]))
        after = re.findall(r"\s+|[^\s]+", display_quote(available[-1]))
        matcher = SequenceMatcher(a=before, b=after, autojunk=False)
        for operation, before_start, before_end, after_start, after_end in matcher.get_opcodes():
            if operation == "equal":
                textual_diff.append({"kind": "same", "text": "".join(before[before_start:before_end])})
            elif operation in {"delete", "replace"}:
                textual_diff.append({
                    "kind": "removed",
                    "text": "".join(before[before_start:before_end]),
                })
            if operation in {"insert", "replace"}:
                textual_diff.append({
                    "kind": "added",
                    "text": "".join(after[after_start:after_end]),
                })
        if (available[-1].get("evidence") or {}).get("omitted_following_text"):
            textual_diff.append({
                "kind": "omitted",
                "text": " [trechos seguintes do Art. 20 não reproduzidos no ato]",
            })
    return {
        "rows": rows,
        "complete": len(available) == len(editions) + 1,
        "snapshot_texts_match": snapshots_match,
        "textual_diff": textual_diff,
        "amendment_differs_from_2024": (
            len(available) == len(editions) + 1
            and normalized_quote(available[-2]) != normalized_quote(available[-1])
        ),
    }


def _pgm_ctm_lc271_change_set(*, user=None) -> dict:
    """Compare the twelve CTM devices expressly reworded by LC 271/2025.

    This is an evidence-only QA view: it does not accept either extraction or
    infer the current wording when the amending PDF contains omissions.
    """
    target_articles = ("20", "23", "25", "41", "61", "64", "66", "68", "103", "104", "150", "158")

    def unique_document(identity_key: str, *, edition_year: int | None = None):
        documents = DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
            metadata_json__identity_key=identity_key,
        )
        if edition_year is not None:
            documents = documents.filter(
                metadata_json__edition_candidate__kind="official_consolidated_text",
                metadata_json__edition_candidate__declared_value_year=edition_year,
            )
        rows = list(documents.order_by("pk")[:2])
        return rows[0] if len(rows) == 1 else None

    base_document = unique_document(
        "BR-RN-NATAL|lei|municipal_lo|3882|1989", edition_year=2024
    )
    amendment_document = DocumentoNormativo.objects.filter(
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        accepted_extraction__isnull=True,
        metadata_json__identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|271|2025",
    ).order_by("pk")
    amendment_rows = list(amendment_document[:2])
    amendment_document = amendment_rows[0] if len(amendment_rows) == 1 else None

    def complete_extraction(document):
        if document is None:
            return None
        return document.extracoes.filter(
            status=ExtracaoDocumento.Status.COMPLETE
        ).order_by("-created_at", "-pk").first()

    base_extraction = complete_extraction(base_document)
    amendment_extraction = complete_extraction(amendment_document)
    changes = []
    from difflib import SequenceMatcher

    def comparable_quote(evidence, article_number):
        quote = (evidence or {}).get("quote", "")
        quote = re.sub(
            rf"^Art\.?\s*{re.escape(article_number)}\s*[ºª°]?\.?\s*[.–—-]?\s*",
            "",
            quote,
            flags=re.IGNORECASE,
        )
        return re.sub(r"\s+", " ", quote).strip()

    for article_number in target_articles:
        previous = _pgm_article_evidence(base_extraction, article_number)
        if previous:
            previous["quote"] = re.sub(
                r"\s+(?:T[IÍ]TULO|CAP[IÍ]TULO|SE[CÇ][AÃ]O|SUBSE[CÇ][AÃ]O)\s+"
                r"(?:[IVXLCDM]+|\d+)\b.*$",
                "",
                previous["quote"],
                flags=re.IGNORECASE,
            ).strip()
        replacement = _pgm_replacement_article_evidence(
            amendment_extraction, "1", article_number
        )
        before = comparable_quote(previous, article_number)
        after = comparable_quote(replacement, article_number)
        diff = []
        full_text_diff_available = bool(
            before and after and not (replacement or {}).get("omitted_following_text")
        )
        if full_text_diff_available:
            left = re.findall(r"\s+|[^\s]+", before)
            right = re.findall(r"\s+|[^\s]+", after)
            matcher = SequenceMatcher(a=left, b=right, autojunk=False)
            for operation, left_start, left_end, right_start, right_end in matcher.get_opcodes():
                if operation == "equal":
                    diff.append({"kind": "same", "text": "".join(left[left_start:left_end])})
                elif operation in {"delete", "replace"}:
                    diff.append({"kind": "removed", "text": "".join(left[left_start:left_end])})
                if operation in {"insert", "replace"}:
                    diff.append({"kind": "added", "text": "".join(right[right_start:right_end])})
            if replacement.get("omitted_following_text"):
                diff.append({
                    "kind": "omitted",
                    "text": "Trecho omitido/abreviado no PDF da LC 271/2025; cotejo incompleto.",
                })
        changes.append({
            "article_number": article_number,
            "before": previous,
            "after": replacement,
            "diff": diff,
            "full_text_diff_available": full_text_diff_available,
            "state": "sources_found" if previous and replacement else "incomplete",
            "before_pdf_url": _pgm_document_pdf_url(
                base_document, previous["page"] if previous else None, user=user
            ) if base_document else "",
            "after_pdf_url": _pgm_document_pdf_url(
                amendment_document, replacement["page"] if replacement else None, user=user
            ) if amendment_document else "",
            "before_official_pdf_url": safe_official_url(base_document.official_url) if base_document else "",
            "after_official_pdf_url": safe_official_url(amendment_document.official_url) if amendment_document else "",
        })

    source_pair_count = sum(item["state"] == "sources_found" for item in changes)
    complete_pair_count = sum(item["full_text_diff_available"] for item in changes)
    from src.processing.normative_consolidation_preview import (
        build_lc271_consolidation_previews,
        extract_lc271_added_articles,
        lc271_effects_summary,
    )

    return {
        "changes": changes,
        "target_count": len(target_articles),
        "source_pair_count": source_pair_count,
        "complete_pair_count": complete_pair_count,
        "all_source_pairs_found": source_pair_count == len(target_articles),
        "consolidation_previews": build_lc271_consolidation_previews(changes),
        "added_articles": extract_lc271_added_articles(
            amendment_extraction.legal_text if amendment_extraction else ""
        ),
        "added_articles_official_pdf_url": (
            safe_official_url(amendment_document.official_url) if amendment_document else ""
        ),
        "express_effects": lc271_effects_summary(),
        "review_pending": True,
    }


def _pgm_ctm_art20_relation_candidate(document, *, user=None) -> dict | None:
    """Find the exact pending Art. 20 relation only within the amendment PDF."""
    from src.apps.legislation.document_models import EventoNormativoCandidato

    candidates = (
        EventoNormativoCandidato.objects.filter(extracao__documento=document)
        .select_related("extracao", "extracao__documento")
        .prefetch_related("revisoes")
        .order_by("pk")
    )
    for candidate in candidates:
        target = candidate.target_reference_json
        target = target if isinstance(target, dict) else {}
        try:
            year = int(target.get("year_candidate"))
        except (TypeError, ValueError):
            continue
        if (
            normalize_number(str(target.get("number_candidate") or "")) != "3882"
            or year != 1989
            or canonical_type(str(target.get("type_candidate") or "")) != "lei"
            or str(target.get("structural_article_number") or "") != "20"
        ):
            continue
        revisions = list(candidate.revisoes.all())
        latest_review = max(revisions, key=lambda item: (item.created_at, item.pk), default=None)
        if latest_review and latest_review.decision == "reject":
            continue
        evidence = candidate.evidence_json
        evidence = evidence if isinstance(evidence, dict) else {}
        page = evidence.get("target_page") or evidence.get("action_page")
        return {
            "action": candidate.action,
            "source_label": "Lei Complementar nº 271/2025",
            "source_device": candidate.source_device_label,
            "target_scope": "article",
            "target_device": "Artigo 20",
            "action_quote": evidence.get("action_quote") or candidate.action_quote,
            "target_text": evidence.get("target_quote") or candidate.target_text,
            "review_state": "revisão jurídica registrada" if latest_review else "revisão jurídica pendente",
            "page": page,
            "pdf_url": _pgm_document_pdf_url(document, page, user=user)
            or safe_official_url(document.official_url),
        }
    return None


def _pgm_paragraph_evidence(extraction, article_number: str, paragraph_number: str) -> dict | None:
    """Extract one numbered paragraph from a device, keeping its page provenance."""
    article = _pgm_article_evidence(extraction, article_number)
    if article is None:
        return None
    match = re.search(
        rf"(?i)(§\s*{re.escape(str(paragraph_number))}\s*[ºª°]?)\s*",
        article["quote"],
    )
    if match is None:
        return None
    following = re.search(
        r"(?i)§\s*(?:\d+\s*[ºª°]?|único)(?=\s)",
        article["quote"][match.end():],
    )
    end = match.end() + following.start() if following else len(article["quote"])
    quote = article["quote"][match.start():end].strip()
    if not quote:
        return None
    page = _pgm_source_page_for_quote(
        extraction, quote, after_article=article_number
    )
    return {"quote": quote, "page": page or article["page"]}


def _pgm_compare_paragraph_evidence(left: dict | None, right: dict | None) -> str:
    """Compare operative wording conservatively; missing text is never a match."""
    if not left or not right:
        return "insufficient"

    def normalize(quote: str) -> str:
        value = str(quote or "").strip()
        value = re.sub(r"^§\s*\d+\s*[ºª°]?\s*[-–.]?\s*", "", value)
        value = re.sub(
            r"\s*\((?:reda[cç][aã]o dada|acrescido|inclu[ií]do).*?\)\s*$",
            "",
            value,
            flags=re.IGNORECASE | re.DOTALL,
        )
        return re.sub(r"\s+", " ", value).strip().casefold()

    return "match" if normalize(left.get("quote")) == normalize(right.get("quote")) else "mismatch"


def _pgm_replacement_paragraph_evidence(
    extraction,
    amendment_article_number: str,
    target_article_number: str,
    paragraph_number: str,
) -> dict | None:
    """Extract replacement wording for a specifically named paragraph."""
    amendment = _pgm_article_evidence(extraction, amendment_article_number)
    if amendment is None:
        return None
    pattern = re.compile(
        rf"(?is)(§\s*{re.escape(str(paragraph_number))}\s*[ºª°]?\s*do\s*"
        rf"Art\.?\s*{re.escape(str(target_article_number))}\b.*?)"
        rf"passa\s+a\s+vigorar\s+com\s+a\s+seguinte\s+reda[cç][aã]o\s*:\s*[\"“«]"
        rf"(.+?)[\"”»]"
    )
    match = pattern.search(amendment["quote"])
    if match is None:
        return None
    quote = re.sub(r"\s+", " ", match.group(2)).strip()
    page = _pgm_source_page_for_quote(
        extraction, quote, after_article=amendment_article_number
    )
    return {
        "target": re.sub(r"\s+", " ", match.group(1)).strip(),
        "quote": quote,
        "page": page or amendment["page"],
    }


def _pgm_reference_scope(citation: str) -> dict[str, str]:
    """Describe only the granularity of a quoted repeal target, not its legal effect."""
    article_match = re.match(r"Art\.\s*(\d+)", citation, flags=re.IGNORECASE)
    if article_match:
        return {
            "kind": "device",
            "label": "Dispositivo citado",
            "note": (
                f"A cláusula nomeia o Art. {article_match.group(1)}; o trecho, por si só, "
                "não valida o alcance nem os efeitos temporais."
            ),
        }
    return {
        "kind": "act",
        "label": "Ato citado",
        "note": (
            "A cláusula cita a norma sem indicar artigo específico; não se deve inferir "
            "revogação integral apenas desta menção textual."
        ),
    }


def _pgm_document_pdf_url(document, page=None, *, user=None):
    """Link pending SAPL candidates to the public PDF and archive evidence to QA storage."""
    if document is None:
        return None
    if document.source_kind == DocumentoNormativo.SourceKind.SAPL:
        url = safe_official_url(document.official_url)
        if not url and document.norma_id:
            url = safe_official_url(document.norma.pdf_url)
    else:
        reviewer_can_view = bool(
            getattr(user, "is_authenticated", False)
            and getattr(user, "is_active", False)
            and getattr(user, "is_staff", False)
            and user.has_perm("legislation.view_documentonormativo")
        )
        qa_archive_review = bool(
            getattr(settings, "DEBUG", False)
            and getattr(settings, "NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED", False)
            and document.source_kind == DocumentoNormativo.SourceKind.ARCHIVE
            and document.review_status in {
                DocumentoNormativo.ReviewStatus.PENDING,
                DocumentoNormativo.ReviewStatus.IN_REVIEW,
            }
        )
        url = (
            reverse("legislation:document_pdf", args=(document.public_id,))
            if (reviewer_can_view or qa_archive_review) and local_pdf_available(document)
            else None
        )
    if url and page:
        url += f"#page={page}"
    return url


def _pgm_document_review_url(document, user):
    """Expose the internal candidate review route only to authorized reviewers."""
    if (
        document is None
        or not getattr(user, "is_authenticated", False)
        or not getattr(user, "is_active", False)
        or not getattr(user, "is_staff", False)
        or not user.has_perm("legislation.view_documentonormativo")
    ):
        return None
    return reverse("legislation:document_evidence", args=(document.public_id,))


def _pgm_lc55_chain_candidate(
    identity_key: str,
    article_number: str,
    source_label: str,
    *,
    role: str | None = None,
    user=None,
):
    """Build read-only evidence for one exact local act without asserting legal effect."""
    from src.apps.legislation.document_models import ExtracaoDocumento

    candidate_query = DocumentoNormativo.objects.filter(
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        metadata_json__identity_key=identity_key,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        accepted_extraction__isnull=True,
    )
    if role is not None:
        candidate_query = candidate_query.filter(role=role)
    candidates = list(candidate_query.order_by("created_at", "pk")[:2])
    result = {
        "source_label": source_label,
        "state": "missing" if not candidates else "ambiguous",
        "document": None,
        "evidence": None,
        "pdf_url": None,
    }
    if len(candidates) != 1:
        return result

    document = candidates[0]
    extraction = document.extracoes.filter(
        status=ExtracaoDocumento.Status.COMPLETE
    ).order_by("-created_at", "-pk").first()
    evidence = _pgm_article_evidence(extraction, article_number)
    result.update(
        {
            "state": "candidate" if evidence else "text_not_found",
            "document": document,
            "evidence": evidence,
            "pdf_url": _pgm_document_pdf_url(
                document, evidence["page"] if evidence else None, user=user
            ),
            "extraction": extraction,
        }
    )
    return result


def pgm_consolidation_demo_view(request):
    """Show a read-only, QA-only graph of every act named by LC 258/2024 Art. 260."""
    if not (
        getattr(settings, "DEBUG", False)
        and getattr(settings, "PGM_CONSOLIDATION_DEMO_ENABLED", False)
    ):
        raise Http404("Prévia disponível somente no ambiente QA autorizado.")

    from src.apps.legislation.pilot_catalog import operational_pilot

    if operational_pilot():
        return redirect("workspace:pilot_casefile")

    from src.apps.legislation.document_models import ExtracaoDocumento

    source_document = (
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            norma__sapl_id=4052,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .select_related("norma")
        .order_by("created_at", "pk")
        .first()
    )
    if source_document is None:
        source_document = DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            original_filename="LeiComplementar_20241227_258_.pdf",
            metadata_json__identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|258|2024",
        ).first()
    if source_document is None or source_document.review_status == DocumentoNormativo.ReviewStatus.APPROVED:
        raise Http404("O documento candidato desta demonstração não está disponível.")
    extraction = source_document.extracoes.filter(
        status__in=(ExtracaoDocumento.Status.COMPLETE, ExtracaoDocumento.Status.PARTIAL)
    ).order_by("-created_at", "-pk").first()
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
    source_pdf_url = _pgm_document_pdf_url(source_document, source_page, user=request.user)

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
        candidate_documents = list(
            DocumentoNormativo.objects.filter(
                source_kind__in=(
                    DocumentoNormativo.SourceKind.ARCHIVE,
                    DocumentoNormativo.SourceKind.SAPL,
                ),
                metadata_json__identity_candidate__number=normalized_number,
                metadata_json__identity_candidate__year=year,
            ).order_by("created_at", "pk")[:9]
        ) if normalized_number and year else []
        candidate_list_truncated = len(candidate_documents) > 8
        possible_documents = candidate_documents[:8]
        classification = classify_identity_candidates(
            possible_documents,
            expected_type,
            truncated=candidate_list_truncated,
        )
        exact_document = classification["document"]
        conflicting_documents = classification["conflicts"]
        target_pdf_url = None
        target_page = None
        if exact_document and exact_document.review_status != DocumentoNormativo.ReviewStatus.APPROVED:
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
            target_pdf_url = _pgm_document_pdf_url(exact_document, target_page, user=request.user)

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
                    "pdf_url": _pgm_document_pdf_url(document, user=request.user),
                }
            )
        references.append(
            {
                "roman": roman,
                "citation": citation,
                "reference_scope": _pgm_reference_scope(citation),
                "expected_type": expected_type,
                "sapl_registry": _pgm_lc258_sapl_registry_evidence(
                    normalized_number, year, expected_type, _pgm_citation_date(citation)
                ),
                "expected_type_display": {
                    "lei": "Lei",
                    "lei_complementar": "Lei Complementar",
                    "lei_promulgada": "Lei Promulgada",
                }[expected_type],
                "document": exact_document,
                "ambiguous_candidates": [
                    {
                        "document": document,
                        "candidate_type": {
                            "lei": "Lei",
                            "lei_complementar": "Lei Complementar",
                            "lei_promulgada": "Lei Promulgada",
                        }.get(
                            (document.metadata_json or {}).get("identity_candidate", {}).get(
                                "type"
                            ),
                            "espécie indeterminada",
                        ),
                        "pdf_url": _pgm_document_pdf_url(document, user=request.user),
                    }
                    for document in classification["ambiguous_candidates"]
                ],
                "candidate_list_truncated": classification["candidate_list_truncated"],
                "pdf_url": target_pdf_url,
                "review_url": _pgm_document_review_url(exact_document, request.user),
                "page": target_page,
                "conflicts": conflicts,
                "state": classification["state"],
            }
        )

    lc55_reference = next(item for item in references if item["roman"] == "IV")
    lc55_original_source = _pgm_lc55_chain_candidate(
        "BR-RN-NATAL|lei_complementar|municipal_lc|55|2004",
        "21",
        "LC nº 55/2004 · Art. 21 no texto original",
        role=DocumentoNormativo.Role.ORIGINAL,
        user=request.user,
    )
    lc55_evidence_document = lc55_reference["document"] or lc55_original_source["document"]
    lc55_evidence_extraction = lc55_evidence_document.extracoes.filter(
        status=ExtracaoDocumento.Status.COMPLETE
    ).order_by("-created_at", "-pk").first() if lc55_evidence_document else None
    old_article_21 = _pgm_article_evidence(lc55_evidence_extraction, "21")
    lc55_snapshot_candidate = _pgm_lc55_chain_candidate(
        "BR-RN-NATAL|lei_complementar|municipal_lc|55|2004",
        "34",
        "Compilação municipal de julho/2019 · Art. 34",
        role=DocumentoNormativo.Role.UNDETERMINED,
        user=request.user,
    )
    lc55_extraction = lc55_snapshot_candidate.get("extraction")
    lc208_identity_key = "BR-RN-NATAL|lei_complementar|municipal_lc|208|2022"
    lc208_existing_norma_identity_conflict = Norma.objects.filter(sapl_id=1160).exclude(
        identity_key=lc208_identity_key
    ).exists()
    lc208_document = (
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .filter(
            Q(norma__sapl_id=1160, norma__identity_key=lc208_identity_key)
            | Q(
                norma__isnull=True,
                metadata_json__sapl_id=1160,
                metadata_json__identity_status="candidate",
                metadata_json__identity_key=lc208_identity_key,
                metadata_json__identity_key_candidate=lc208_identity_key,
                metadata_json__source_provenance__kind="sapl_norma_pdf",
                metadata_json__association_status="identity_conflict_unlinked",
            )
        )
        .select_related("norma")
        .order_by("created_at", "pk")
        .first()
    )
    lc208_extraction = (
        lc208_document.extracoes.filter(status=ExtracaoDocumento.Status.COMPLETE)
        .order_by("-created_at", "-pk")
        .first()
        if lc208_document
        else None
    )
    lc208_article_14 = _pgm_article_evidence(lc208_extraction, "14")
    lc258_article_261 = _pgm_article_evidence(extraction, "261")
    lc258_new_article_14 = _pgm_replacement_article_evidence(extraction, "261", "14")
    lc261_document = (
        DocumentoNormativo.objects.filter(
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            accepted_extraction__isnull=True,
        )
        .filter(
            Q(norma__sapl_id=8823, norma__identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|261|2025")
            | Q(
                norma__isnull=True,
                metadata_json__sapl_id=8823,
                metadata_json__identity_status="candidate",
                metadata_json__identity_key="BR-RN-NATAL|lei_complementar|municipal_lc|261|2025",
                metadata_json__identity_key_candidate="BR-RN-NATAL|lei_complementar|municipal_lc|261|2025",
                metadata_json__source_provenance__kind="sapl_norma_pdf",
                metadata_json__association_status="identity_conflict_unlinked",
            )
        )
        .select_related("norma")
        .order_by("created_at", "pk")
        .first()
    )
    lc261_extraction = (
        lc261_document.extracoes.filter(status=ExtracaoDocumento.Status.COMPLETE)
        .order_by("-created_at", "-pk")
        .first()
        if lc261_document
        else None
    )
    lc261_article_117 = _pgm_article_evidence(lc261_extraction, "117")
    lc261_article_118 = _pgm_article_evidence(lc261_extraction, "118")
    lc208_article_18_paragraph_2 = _pgm_paragraph_evidence(lc208_extraction, "18", "2")
    lc261_replacement_article_18_paragraph_2 = _pgm_replacement_paragraph_evidence(
        lc261_extraction, "118", "18", "2"
    )
    lc208_article_21 = _pgm_article_evidence(lc208_extraction, "21")
    lc261_pdf_url = _pgm_document_pdf_url(
        lc261_document,
        lc261_article_117["page"] if lc261_article_117 else None,
        user=request.user,
    )
    lc261_repeal_targets = build_candidate_relation_evidence(
        lc261_extraction,
        source_pdf_url=lc261_pdf_url or "",
        document_pdf_url=lambda document: _pgm_document_pdf_url(document, user=request.user),
        pdf_access_required=local_pdf_available,
        sapl_registry_records=PGM_LC261_SAPL_REGISTRY_RECORDS,
    )
    lc261_article_118_pdf_url = _pgm_document_pdf_url(
        lc261_document,
        (
            lc261_replacement_article_18_paragraph_2["page"]
            if lc261_replacement_article_18_paragraph_2
            else lc261_article_118["page"] if lc261_article_118 else None
        ),
        user=request.user,
    )
    lc208_pdf_url = _pgm_document_pdf_url(
        lc208_document,
        lc208_article_14["page"] if lc208_article_14 else None,
        user=request.user,
    )
    lc208_article_18_pdf_url = _pgm_document_pdf_url(
        lc208_document,
        lc208_article_18_paragraph_2["page"] if lc208_article_18_paragraph_2 else None,
        user=request.user,
    )
    lc208_article_21_pdf_url = _pgm_document_pdf_url(
        lc208_document,
        lc208_article_21["page"] if lc208_article_21 else None,
        user=request.user,
    )
    lc258_article_261_pdf_url = _pgm_document_pdf_url(
        source_document,
        (
            lc258_new_article_14["page"]
            if lc258_new_article_14
            else lc258_article_261["page"] if lc258_article_261 else None
        ),
        user=request.user,
    )
    transition_articles = {
        number: _pgm_article_evidence(extraction, number)
        for number in ("260", "262", "266")
    }
    for number, evidence in transition_articles.items():
        if evidence is not None:
            evidence["pdf_url"] = _pgm_document_pdf_url(
                source_document, evidence["page"], user=request.user
            )
            evidence["article"] = number
    lc55_history_2017 = _pgm_lc55_chain_candidate(
        "BR-RN-NATAL|lei_complementar|municipal_lc|173|2017",
        "2",
        "LC nº 173/2017 · Art. 2º",
        user=request.user,
    )
    lc55_history_2017["official_pdf_url"] = (
        "https://natal.rn.gov.br/storage/app/media/legislacao/anexos/"
        "LeiComplementar_20171229_173_.pdf"
    )
    lc55_history_2017["official_hash_match"] = bool(
        lc55_history_2017.get("document")
        and lc55_history_2017["document"].content_sha256
        == "aeb6e6b137382df8094822d4aff92c4b9dbecccb442eaeae2c3b6008722de137"
    )
    lc55_paragraph_3_2017 = _pgm_paragraph_evidence(
        lc55_history_2017.get("extraction"), "2", "3"
    )
    lc55_paragraph_4_2017 = _pgm_paragraph_evidence(
        lc55_history_2017.get("extraction"), "2", "4"
    )
    lc55_history_185 = _pgm_lc55_chain_candidate(
        "BR-RN-NATAL|lei_complementar|municipal_lc|185|2019",
        "87",
        "LC nº 185/2019 · Art. 87",
        user=request.user,
    )
    lc55_history_185["official_pdf_url"] = (
        "https://natal.rn.gov.br/storage/app/media/legislacao/anexos/"
        "LeiComplementar_20190718_185_.pdf"
    )
    lc55_history_185["official_hash_match"] = bool(
        lc55_history_185.get("document")
        and lc55_history_185["document"].content_sha256
        == "7b4562db8cb0b47146a2466014d02e34f026a023f93d2b870282f6f56eade6e2"
    )
    lc55_replacement_article_34_2019 = _pgm_replacement_article_evidence(
        lc55_history_185.get("extraction"), "87", "34"
    )
    lc55_paragraph_3_185 = _pgm_paragraph_evidence(
        lc55_history_185.get("extraction"), "87", "3"
    )
    if lc55_replacement_article_34_2019:
        lc55_replacement_article_34_2019["pdf_url"] = _pgm_document_pdf_url(
            lc55_history_185["document"],
            lc55_replacement_article_34_2019["page"],
            user=request.user,
        )
        lc55_replacement_article_34_2019["official_pdf_url"] = (
            lc55_history_185["official_pdf_url"]
        )
    lc55_paragraph_3_2019 = _pgm_paragraph_evidence(
        lc55_extraction, "34", "3"
    )
    lc55_paragraph_4_2019 = _pgm_paragraph_evidence(
        lc55_extraction, "34", "4"
    )
    lc55_paragraph_5_2019 = _pgm_paragraph_evidence(
        lc55_extraction, "34", "5"
    )
    lc55_paragraph_3_comparison = _pgm_compare_paragraph_evidence(
        lc55_paragraph_3_185, lc55_paragraph_3_2019
    )
    lc55_history_2019_evidence = [
        item
        for item in (
            lc55_paragraph_3_2019,
            lc55_paragraph_4_2019,
            lc55_paragraph_5_2019,
        )
        if item
    ]
    lc55_article_34_2019_snapshot = _pgm_article_evidence(lc55_extraction, "34")
    lc55_history_2019 = {
        "source_label": "Compilação oficial municipal · julho/2019 (snapshot, não ato)",
        "state": "snapshot" if lc55_history_2019_evidence else "text_not_found",
        "document": None,
        "evidence": lc55_article_34_2019_snapshot,
        "pdf_url": (
            "https://www.natal.rn.gov.br/storage/app/media/semurb/legislacao/"
            "35_Codigo_Obras_Atualizado_Julho_2019.pdf"
        ),
    }
    lc55_history_2024 = {
        "source_label": "LC nº 258/2024 · Art. 260, IV",
        "state": "candidate",
        "document": source_document,
        "evidence": {
            "quote": (
                "Art. 260, IV — "
                + next(item[1] for item in parsed_items if item[0] == "IV")
            ),
            "page": source_page,
        },
        "pdf_url": source_pdf_url,
    }
    # The official DOM extra edition 5615 contains LC 258 on 27/12/2024;
    # Art. 266 sets a 90-day vacatio. Under LC 95/1998, Art. 8º, § 1º,
    # including publication and the last day, effect starts the following day.
    lc258_publication_date = date(2024, 12, 27)
    lc258_effective_date = lc258_publication_date + timedelta(days=90)
    lc55_history = [
        lc55_history_2017,
        lc55_history_185,
        lc55_history_2019,
        lc55_history_2024,
    ]
    lc55_original_candidate = _pgm_lc55_chain_candidate(
        "BR-RN-NATAL|lei_complementar|municipal_lc|55|2004",
        "34",
        "LC nº 55/2004 · texto original",
        role=DocumentoNormativo.Role.ORIGINAL,
        user=request.user,
    )
    lc55_article_34_original = _pgm_lc55_original_article_context(
        lc55_original_candidate, user=request.user
    )
    lc55_original_official_pdf_url = PGM_LC55_ORIGINAL_OFFICIAL_PDF
    lc55_pdf_url = _pgm_document_pdf_url(
        lc55_evidence_document,
        old_article_21["page"] if old_article_21 else None,
        user=request.user,
    )
    ctm_art20_candidate_timeline = _pgm_ctm_art20_candidate_timeline(user=request.user)
    ctm_lc271_change_set = _pgm_ctm_lc271_change_set(user=request.user)

    source_segmentation_count = extraction.dispositivos_documentais.count()
    target_count = sum(item["state"] == "candidate" for item in references)
    conflict_count = sum(item["state"] == "identity_conflict" for item in references)
    ambiguous_count = sum(item["state"] == "ambiguous" for item in references)
    missing_count = sum(item["state"] == "not_found" for item in references)

    return render(
        request,
        "legislation/workspace/pgm_consolidation_demo.html",
        {
            "source_document": source_document,
            "source_extraction": extraction,
            "source_extraction_status": extraction.status,
            "source_extraction_unreadable_pages": len(
                (extraction.quality_json or {}).get("unreadable_pages", [])
            ),
            "source_is_official_sapl": (
                source_document.source_kind == DocumentoNormativo.SourceKind.SAPL
            ),
            "source_quote": source_quote,
            "source_page": source_page,
            "source_pdf_url": source_pdf_url,
            "source_segmentation_count": source_segmentation_count,
            "old_article_21": old_article_21,
            "lc55_evidence_document": lc55_evidence_document,
            "old_article_21_pdf_url": lc55_pdf_url,
            "lc208_document": lc208_document,
            "lc208_existing_norma_identity_conflict": lc208_existing_norma_identity_conflict,
            "lc208_article_14": lc208_article_14,
            "lc208_article_14_pdf_url": lc208_pdf_url,
            "lc258_new_article_14": lc258_new_article_14,
            "lc258_article_261_pdf_url": lc258_article_261_pdf_url,
            "lc261_document": lc261_document,
            "lc261_article_117": lc261_article_117,
            "lc261_article_118": lc261_article_118,
            "lc261_repeal_targets": lc261_repeal_targets,
            "lc261_pdf_url": lc261_pdf_url,
            "lc261_article_118_pdf_url": lc261_article_118_pdf_url,
            "lc208_article_21": lc208_article_21,
            "lc208_article_21_pdf_url": lc208_article_21_pdf_url,
            "lc208_article_18_paragraph_2": lc208_article_18_paragraph_2,
            "lc208_article_18_pdf_url": lc208_article_18_pdf_url,
            "lc261_replacement_article_18_paragraph_2": lc261_replacement_article_18_paragraph_2,
            "lc208_official_pdf_url": (
                safe_official_url(lc208_document.official_url) if lc208_document else ""
            ),
            "lc261_official_pdf_url": (
                safe_official_url(lc261_document.official_url) if lc261_document else ""
            ),
            "lc258_official_pdf_url": (
                "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/"
                "2024/4052/lei_complementar_no_258_2024.pdf"
            ),
            "lc258_dom_issue_url": (
                "https://www2.natal.rn.gov.br/_anexos/publicacao/dom/"
                "dom_20241227_extra_0aaf5ad445c342a04c28c91e2275c838.pdf"
            ),
            "old_code_document": lc55_reference["document"],
            "lc55_repeal_reference": lc55_reference,
            "lc55_history": lc55_history,
            "lc55_history_185": lc55_history_185,
            "lc55_replacement_article_34_2019": lc55_replacement_article_34_2019,
            "lc55_paragraph_3_185": lc55_paragraph_3_185,
            "lc55_article_34_2019_snapshot": lc55_article_34_2019_snapshot,
            "lc258_publication_date": lc258_publication_date,
            "lc258_effective_date": lc258_effective_date,
            "lc55_article_34_original": lc55_article_34_original,
            "lc55_paragraph_3_2017": lc55_paragraph_3_2017,
            "lc55_paragraph_4_2017": lc55_paragraph_4_2017,
            "lc55_paragraph_3_2019": lc55_paragraph_3_2019,
            "lc55_paragraph_4_2019": lc55_paragraph_4_2019,
            "lc55_paragraph_5_2019": lc55_paragraph_5_2019,
            "lc55_paragraph_3_comparison": lc55_paragraph_3_comparison,
            "lc55_baseline_pdf_url": (
                lc55_article_34_original["pdf_url"]
                if lc55_article_34_original
                else lc55_original_official_pdf_url
            ),
            "lc55_original_official_pdf_url": lc55_original_official_pdf_url,
            "transition_articles": transition_articles,
            "ctm_art20_candidate_timeline": ctm_art20_candidate_timeline,
            "ctm_lc271_change_set": ctm_lc271_change_set,
            "transition_source_published": source_document.metadata_json.get(
                "publication_date_candidate", "27/12/2024"
            ),
            "pending_proposal_watch": {
                "title": "PLC nº 12/2025 — alteração proposta ao Art. 59 da LC 258/2024",
                "matter_url": "https://sapl.natal.rn.leg.br/materia/48759",
                "opinion_url": "https://sapl.natal.rn.leg.br/materia/56868",
                "checked_on": "15/10/2026",
                "status": "Em tramitação no SAPL",
                "latest_event": (
                    "Parecer nº 993/2026, apresentado em 03/08/2026; o cadastro consultado "
                    "mantém a proposição em tramitação."
                ),
            },
            "references": references,
            "target_count": target_count,
            "conflict_count": conflict_count,
            "ambiguous_count": ambiguous_count,
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
