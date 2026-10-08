"""
Views for the legislation app.

Provides web interfaces for viewing consolidated legal texts and
comparing versions.
"""

import json
import logging
import re
import uuid
from collections import defaultdict
from typing import Any

from django.conf import settings
from django.db.models import Prefetch, Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import DetailView, ListView

from src.clients.sapl.sapl_types import resolve_norma_type_display
from src.observability.safe_logging import log_exception_safely
from src.processing.corpus_identity import get_corpus_revision
from src.processing.legal_diff import build_legal_diff, build_version_diff
from src.processing.normative_reference import (
    NormativeReference,
    canonical_type,
    normalize_number,
    parse_normative_reference_query,
)
from src.processing.rag_service import RAGService
from src.processing.temporal_scope import (
    build_norma_timeline,
    deduplicate_event_revisions,
    parse_iso_date,
    temporal_status,
)

from .api_limits import InvalidLLMParams, parse_llm_request, rate_limit_response
from .document_models import DocumentoDispositivo, DocumentoNormativo, ExtracaoDocumento
from .models import ChatMessage, ChatSession, Dispositivo, EventoAlteracao, Norma
from .norma_ordering import order_normas_by_publication
from .norma_pdf import build_consolidated_norma_pdf
from .norma_queries import consolidated_normas_for_product
from .serializers import (
    serialize_dispositivo_source,
)
from .source_urls import canonical_norma_url

logger = logging.getLogger(__name__)

MAX_NORMA_SEARCH_LENGTH = 160
NORMA_COMPARE_MAX_LINES = 1_000
NORMA_COMPARE_MAX_CHARS = 120_000


def _presentation_consolidated_text(norma: Norma) -> str:
    """Normalize legacy generated headers without mutating the legal corpus."""
    text = norma.texto_consolidado or ""
    raw_type = str(norma.tipo or "").strip()
    label = norma.get_tipo_display_name()
    # Old generated rows used the SAPL numeric type as the header even when
    # the current model stores the human label.  Accept both representations.
    candidates = {raw_type} if raw_type.isdigit() else set()
    candidates.update({"1", "2", "3", "4", "5", "6"})
    prefix = "|".join(re.escape(value) for value in sorted(candidates, key=len, reverse=True))
    text = re.sub(
        rf"(?m)^(\s*)(?:{prefix})\s+(?:Nº|nº|N°)\s+",
        rf"\1{label} nº ",
        text,
        count=1,
    )
    return text


def _norma_tipo_label(value: object) -> str:
    return resolve_norma_type_display(value)


def _normalize_norma_query(value: object) -> str:
    return str(value or "").strip()[:MAX_NORMA_SEARCH_LENGTH]


def _norma_list_facets() -> tuple[list[str], list[int]]:
    queryset = consolidated_normas_for_product()
    types = list(queryset.values_list("tipo", flat=True).distinct().order_by("tipo"))
    years = list(queryset.values_list("ano", flat=True).distinct().order_by("-ano"))
    return types, years


def _group_normative_number(number: str) -> str:
    """Return the SAPL thousands-separated variant without changing digits."""
    return re.sub(r"(?<=\d)(?=(?:\d{3})+$)", ".", number)


def _exact_norma_query(
    queryset, search_query: str, *, selected_type: str = "", selected_year: str = "", forced: bool = False
):
    reference = parse_normative_reference_query(search_query)
    if reference is None and forced and selected_year.isdigit() and len(selected_year) == 4:
        digits = normalize_number(search_query)
        if digits:
            reference = NormativeReference(
                type_key=canonical_type(_norma_tipo_label(selected_type)) if selected_type else "",
                number=digits,
                year=int(selected_year),
            )
    if reference is None:
        return None

    number_values = {reference.number, _group_normative_number(reference.number)}
    exact = queryset.filter(numero__in=number_values, ano=reference.year)
    type_values = {
        "lei": ("Lei", "Lei Ordinária", "1"),
        "lei_complementar": ("Lei Complementar", "2"),
        "lei_ordinaria": ("Lei Ordinária", "1"),
        "lei_organica": ("Lei Orgânica",),
        "decreto": ("Decreto", "3"),
        "decreto_lei": ("Decreto-Lei",),
        "decreto_legislativo": ("Decreto Legislativo",),
        "resolucao": ("Resolução", "4"),
        "portaria": ("Portaria", "6"),
        "emenda_constitucional": ("Emenda Constitucional",),
    }
    if reference.type_key:
        choices = type_values.get(reference.type_key)
        if choices is None:
            return exact.none()
        exact = exact.filter(Q(tipo__in=choices) | Q(tipo__iexact=choices[0]))
    return exact


class NormaListView(ListView):
    """Responsive, filterable list of consolidated municipal norms."""

    model = Norma
    template_name = "legislation/norma_list.html"
    context_object_name = "normas"
    paginate_by = 18

    def get_queryset(self):
        queryset = consolidated_normas_for_product()
        search_query = _normalize_norma_query(self.request.GET.get("q"))
        if search_query:
            selected_type = _normalize_norma_query(self.request.GET.get("tipo"))
            selected_year = self.request.GET.get("ano", "").strip()
            exact_query = _exact_norma_query(
                queryset,
                search_query,
                selected_type=selected_type,
                selected_year=selected_year,
                forced=self.request.GET.get("referencia_exata") == "1",
            )
            queryset = exact_query if exact_query is not None else queryset.filter(
                Q(ementa__icontains=search_query)
                | Q(numero__icontains=search_query)
                | Q(tipo__icontains=search_query)
            )

        selected_type = _normalize_norma_query(self.request.GET.get("tipo"))
        if selected_type:
            queryset = queryset.filter(tipo=selected_type)

        selected_year = self.request.GET.get("ano", "").strip()
        if selected_year.isdigit() and len(selected_year) <= 4:
            queryset = queryset.filter(ano=int(selected_year))

        ordering = self.request.GET.get("ordenar", "recentes")
        if ordering == "antigas":
            queryset = order_normas_by_publication(queryset, descending=False)
        else:
            queryset = order_normas_by_publication(queryset)
        return queryset.only(
            "id",
            "tipo",
            "numero",
            "ano",
            "ementa",
            "status",
            "data_publicacao",
            "data_vigencia",
            "sapl_id",
            "sapl_url",
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["active_nav"] = "normas"
        for norma in context.get("normas", []):
            norma.sapl_url = canonical_norma_url(norma)
        context["search_query"] = _normalize_norma_query(self.request.GET.get("q"))
        context["archive_candidate_query"] = _normalize_norma_query(
            self.request.GET.get("arquivo_q", context["search_query"])
        )
        context["selected_type"] = _normalize_norma_query(self.request.GET.get("tipo"))
        selected_year = self.request.GET.get("ano", "").strip()
        context["selected_year"] = selected_year if selected_year.isdigit() else ""
        context["ordering"] = self.request.GET.get("ordenar", "recentes")

        available_types, available_years = _norma_list_facets()
        context["available_types"] = available_types
        type_options = []
        seen_type_labels = set()
        for tipo in available_types:
            label = _norma_tipo_label(tipo)
            if label in seen_type_labels:
                continue
            seen_type_labels.add(label)
            type_options.append({"value": tipo, "label": label})
        context["available_type_options"] = type_options
        context["available_years"] = available_years
        # This count is displayed as a corpus-wide integrity signal. Caching
        # it independently from the corpus-version bump can show a stale
        # value after ingestion (for example, "1" beside 356 results). The
        # count is a cheap indexed query and must reflect the same database
        # state as the list itself.
        context["total_consolidated"] = consolidated_normas_for_product().count()

        # Keep unreviewed archive imports out of the consolidated corpus/RAG.
        # The isolated QA app gets a separate, clearly labelled view so real
        # PDFs are visible for inspection without presenting them as official.
        context["archive_candidates"] = []
        if getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
            candidates = DocumentoNormativo.objects.filter(
                source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
                norma__isnull=True,
                review_status__in=(
                    DocumentoNormativo.ReviewStatus.PENDING,
                    DocumentoNormativo.ReviewStatus.IN_REVIEW,
                ),
            ).prefetch_related(
                Prefetch(
                    "extracoes",
                    queryset=ExtracaoDocumento.objects.only(
                        "pk", "documento_id", "created_at", "status", "page_count"
                    ).order_by("-created_at", "-pk").prefetch_related(
                        Prefetch(
                            "dispositivos_documentais",
                            queryset=DocumentoDispositivo.objects.only("pk", "extracao_id"),
                            to_attr="qa_candidate_devices",
                        )
                    ),
                    to_attr="qa_candidate_extractions",
                )
            ).order_by("entry_index", "pk")[:40]
            type_labels = {
                "lei": "Lei Ordinária",
                "lei_ordinaria": "Lei Ordinária",
                "lei_complementar": "Lei Complementar",
                "decreto": "Decreto",
                "lei_promulgada": "Lei Promulgada",
            }
            for document in candidates:
                metadata = document.metadata_json or {}
                identity = metadata.get("identity_candidate") or {}
                extraction = (document.qa_candidate_extractions or [None])[0]
                number, year = identity.get("number"), identity.get("year")
                display_number = _group_normative_number(str(number)) if number else ""
                draft_device_count = len(extraction.qa_candidate_devices) if extraction else 0
                if extraction and draft_device_count:
                    page_label = "página" if extraction.page_count == 1 else "páginas"
                    device_label = "dispositivo identificado" if draft_device_count == 1 else "dispositivos identificados"
                    extraction_summary = (
                        f"Extração {extraction.get_status_display().lower()} · "
                        f"{extraction.page_count} {page_label} · "
                        f"{draft_device_count} {device_label} no rascunho"
                    )
                elif extraction:
                    page_label = "página" if extraction.page_count == 1 else "páginas"
                    extraction_summary = (
                        f"Extração {extraction.get_status_display().lower()} · "
                        f"{extraction.page_count} {page_label} · segmentação de dispositivos pendente"
                    )
                else:
                    extraction_summary = "Nenhuma extração de texto disponível"
                label = (
                    f"{type_labels.get(identity.get('type'), 'Norma')} nº {display_number}/{year}"
                    if number and year
                    else document.original_filename
                )
                context["archive_candidates"].append({
                    "label": label,
                    "filename": document.original_filename,
                    "evidence_url": reverse(
                        "legislation:document_evidence", kwargs={"document_id": document.public_id}
                    ),
                    "entry_index": document.entry_index,
                    "identity_resolved": bool(metadata.get("identity_key")),
                    "review_status": document.get_review_status_display(),
                    "review_status_key": document.review_status,
                    "extraction_status": extraction.status if extraction else "none",
                    "extraction_summary": extraction_summary,
                })
        context["archive_candidate_count"] = len(context["archive_candidates"])
        context["archive_assistant_enabled"] = getattr(
            settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False
        )

        page_obj = context.get("page_obj")
        context["filtered_count"] = (
            page_obj.paginator.count if page_obj is not None else self.object_list.count()
        )
        return context


class NormaDetailView(DetailView):
    """
    Detail view for a single norma.

    Displays the consolidated text and all alteration events affecting
    this norma.
    """

    model = Norma
    template_name = "legislation/norma_detail.html"
    context_object_name = "norma"

    def get_context_data(self, **kwargs) -> dict[str, Any]:
        """
        Add alteration events and dispositivos to context.
        """
        context = super().get_context_data(**kwargs)
        norma = self.object

        # Get all alteration events affecting this norma
        eventos_recebidos = (
            EventoAlteracao.objects.filter(norma_alvo=norma, is_active=True)
            .select_related(
                "dispositivo_fonte",
                "dispositivo_fonte__norma",
                "dispositivo_alvo",
                "review_revision",
            )
            .order_by("created_at")
        )
        from src.apps.legislation.event_review import event_review_status

        eventos_recebidos = deduplicate_event_revisions(eventos_recebidos)
        for evento in eventos_recebidos:
            evento.review_status = event_review_status(evento)
            evento.review_status_label = {
                "confirmed": "Relação revisada",
                "rejected": "Candidato rejeitado",
                "pending": "Extração pendente de revisão",
            }.get(evento.review_status, "Estado de revisão desconhecido")
            evento.extraction_signal_display = (
                f"{evento.extraction_confidence:.0%} — sinal do extrator"
                if evento.extraction_confidence and evento.extraction_confidence > 0
                else "Não calibrado"
            )

        # Get all dispositivos for this norma
        dispositivos = (
            Dispositivo.objects.filter(norma=norma, is_active=True)
            .select_related("dispositivo_pai")
            .order_by("ordem")
        )

        # Get root dispositivos (for hierarchical display)
        root_dispositivos = dispositivos.filter(dispositivo_pai__isnull=True)

        # Statistics
        stats = {
            "total_dispositivos": dispositivos.count(),
            "total_eventos": len(eventos_recebidos),
            "total_chars": len(norma.texto_consolidado) if norma.texto_consolidado else 0,
            "has_original": bool(norma.texto_original),
            "has_consolidated": bool(norma.texto_consolidado),
        }

        if self.request.user.is_authenticated:
            from .models import Collection

            context["user_collections"] = Collection.objects.filter(
                user=self.request.user
            ).prefetch_related("normas")
        corpus_revision = get_corpus_revision() or {}
        context.update(
            {
                "active_nav": "normas",
                "synthetic_fixture": bool(
                    norma.documento_base_id
                    and isinstance(norma.documento_base.metadata_json, dict)
                    and norma.documento_base.metadata_json.get("synthetic") is True
                ),
                "eventos_recebidos": eventos_recebidos,
                "official_source_url": canonical_norma_url(norma),
                "dispositivos": dispositivos,
                "root_dispositivos": root_dispositivos,
                "stats": stats,
                "consolidated_text": _presentation_consolidated_text(norma),
                "timeline": build_norma_timeline(norma),
                "temporal_status": temporal_status(norma),
                "temporal_status_verified": corpus_revision.get("completeness") == "complete",
                "normative_graph_enabled": getattr(settings, "NORMATIVE_GRAPH_ENABLED", False),
            }
        )

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

    # Historical comparison is explicit and separate from the legacy OCR-vs-
    # consolidation view below. Never substitute today's text for a missing
    # historical projection.
    precedent_mode = request.GET.get("mode") == "precedent"
    historical_mode = (
        "from_as_of" in request.GET
        or "to_as_of" in request.GET
        or request.GET.get("history") == "1"
        or precedent_mode
    )
    dates_submitted = "from_as_of" in request.GET or (
        "to_as_of" in request.GET and not precedent_mode
    )
    today = timezone.localdate().isoformat()
    selected_device = None
    selected_device_id = request.GET.get("device_id", "")[:20]
    if precedent_mode and selected_device_id.isdecimal():
        selected_device = norma.dispositivos.filter(pk=int(selected_device_id)).first()
    historical_context = {
        "historical_mode": historical_mode,
        "precedent_mode": precedent_mode,
        "history_enabled": getattr(settings, "NORMATIVE_HISTORY_ENABLED", False),
        "synthetic_fixture": bool(
            norma.documento_base_id
            and isinstance(norma.documento_base.metadata_json, dict)
            and norma.documento_base.metadata_json.get("synthetic") is True
        ),
        "from_as_of": request.GET.get("from_as_of", "")[:10],
        "to_as_of": request.GET.get("to_as_of", today if precedent_mode else "")[:10],
        "selected_device": selected_device,
        "historical_errors": [],
        "historical_rows": [],
        "historical_timeline": [],
        "historical_available": False,
        "historical_notice": "",
        "before_projection": None,
        "after_projection": None,
    }
    if historical_mode:
        if not historical_context["history_enabled"]:
            historical_context["historical_notice"] = (
                "A comparação histórica está indisponível nesta instalação. "
                "Nenhuma versão atual foi apresentada como se fosse histórica."
            )
        elif dates_submitted:
            try:
                before_date = parse_iso_date(request.GET.get("from_as_of"), "Data inicial")
                after_date = parse_iso_date(request.GET.get("to_as_of"), "Data final")
                if before_date is None or after_date is None:
                    raise ValueError("Informe as duas datas para comparar as versões.")
                if before_date > after_date:
                    raise ValueError("A data inicial deve ser anterior ou igual à data final.")
                if after_date > timezone.localdate():
                    raise ValueError("A data final não pode estar no futuro.")
                if precedent_mode and selected_device_id and selected_device is None:
                    raise ValueError("O dispositivo selecionado não pertence a esta norma.")
            except ValueError as exc:
                historical_context["historical_errors"].append(str(exc))
            else:
                from src.apps.legislation.document_models import (
                    DocumentoNormativo,
                    NormativeSnapshot,
                )
                from src.processing.normative_projection import project_norma_as_of

                before = project_norma_as_of(norma, before_date)
                after = project_norma_as_of(norma, after_date)
                historical_context["before_projection"] = before
                historical_context["after_projection"] = after
                terminal_status = NormativeSnapshot.Status.NOT_RECONSTRUCTABLE
                if before.status == terminal_status or after.status == terminal_status:
                    historical_context["historical_notice"] = (
                        "Não foi possível reconstruir com segurança uma das datas solicitadas. "
                        "O texto consolidado atual não será usado como substituto."
                    )
                else:
                    is_complete = NormativeSnapshot.Status.COMPLETE
                    historical_context["historical_rows"] = build_version_diff(
                        before.devices,
                        after.devices,
                        before_complete=before.status == is_complete,
                        after_complete=after.status == is_complete,
                    )
                    if selected_device is not None:
                        historical_context["historical_rows"] = [
                            row
                            for row in historical_context["historical_rows"]
                            if row["structural_key"] == selected_device.structural_key
                        ]
                        if not historical_context["historical_rows"]:
                            historical_context["historical_notice"] = (
                                f"{selected_device.get_full_identifier()} não está presente nas "
                                "projeções desta comparação. Isso não confirma revogação nem ausência jurídica."
                            )
                    status_labels = {
                        NormativeSnapshot.Status.COMPLETE: "completa",
                        NormativeSnapshot.Status.PARTIAL: "parcial",
                        NormativeSnapshot.Status.NOT_RECONSTRUCTABLE: "não reconstruível",
                    }
                    historical_context["before_status_label"] = status_labels.get(
                        before.status, "desconhecida"
                    )
                    historical_context["after_status_label"] = status_labels.get(
                        after.status, "desconhecida"
                    )
                    device_status_labels = {
                        "in_force": "vigente na projeção",
                        "revoked": "revogado na projeção",
                        "vetoed": "vetado na projeção",
                        "unknown": "situação desconhecida",
                    }
                    for row in historical_context["historical_rows"]:
                        row["before_status_label"] = device_status_labels.get(
                            row["before_status"], "não disponível"
                        )
                        row["after_status_label"] = device_status_labels.get(
                            row["after_status"], "não disponível"
                        )
                    historical_context["historical_available"] = True
                    timeline_order = {"publication": 0, "effective": 1, "event": 2}
                    historical_context["historical_timeline"] = sorted(
                        build_norma_timeline(norma, as_of=after_date),
                        key=lambda item: (
                            item.get("date") or item.get("availability_date") or "9999-99-99",
                            timeline_order.get(item.get("kind"), 3),
                            item.get("title", ""),
                        ),
                    )
                    republications = DocumentoNormativo.objects.filter(
                        norma=norma,
                        role=DocumentoNormativo.Role.REPUBLICATION,
                        review_status=DocumentoNormativo.ReviewStatus.APPROVED,
                    ).order_by("created_at", "pk")
                    historical_context["republication_count"] = republications.count()
                    historical_context["coverage_note"] = (
                        "As redações abaixo são uma consolidação histórica do Jurix, "
                        "projetada a partir de documentos revisados e eventos disponíveis no corpus; "
                        "não substituem publicação oficial."
                    )

    # Bound synchronous structural matching; no partial comparison is exposed
    # when an OCR document exceeds the configured resource budget.
    original_text = norma.texto_original or ""
    consolidated_text = _presentation_consolidated_text(norma)
    diff_rows = []
    original_lines = []
    consolidated_lines = []
    original_length = original_text.count("\n") + (1 if original_text else 0)
    consolidated_length = consolidated_text.count("\n") + (1 if consolidated_text else 0)
    comparison_available = (
        max(original_length, consolidated_length) <= NORMA_COMPARE_MAX_LINES
        and max(len(original_text), len(consolidated_text)) <= NORMA_COMPARE_MAX_CHARS
    )

    if comparison_available:
        original_lines = original_text.split("\n") if original_text else []
        consolidated_lines = consolidated_text.split("\n") if consolidated_text else []
        diff_rows = build_legal_diff(original_text, consolidated_text)

    # Get alteration events
    eventos = (
        EventoAlteracao.objects.filter(
            Q(norma_alvo=norma) | Q(dispositivo_fonte__norma=norma), is_active=True
        )
        .select_related(
            "dispositivo_fonte", "dispositivo_fonte__norma", "dispositivo_alvo", "norma_alvo"
        )
        .order_by("created_at")
    )

    context = {
        "active_nav": "normas",
        "norma": norma,
        "original_lines": original_lines,
        "consolidated_lines": consolidated_lines,
        "consolidated_text": consolidated_text,
        "eventos": eventos,
        "original_length": original_length,
        "consolidated_length": consolidated_length,
        "comparison_available": comparison_available,
        "comparison_max_lines": NORMA_COMPARE_MAX_LINES,
        "comparison_max_chars": NORMA_COMPARE_MAX_CHARS,
        "diff_rows": diff_rows,
        "comparison_label": "Diferenças textuais estruturais",
        "legal_changes_validated": False,
    }
    context.update(historical_context)

    return render(request, "legislation/norma_compare.html", context)


def norma_pdf_export_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate a paginated, print-ready PDF of the consolidated norm."""
    norma = get_object_or_404(Norma, pk=pk)
    title = f"{norma.get_tipo_display_name()} nº {norma.numero}/{norma.ano}"
    body = _presentation_consolidated_text(norma) or "Texto consolidado não disponível."
    payload = build_consolidated_norma_pdf(title, body)
    response = HttpResponse(payload, content_type="application/pdf")
    filename = f"jurix-{norma.tipo}-{norma.numero}-{norma.ano}.pdf"
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


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
    dispositivos = (
        Dispositivo.objects.filter(norma=norma, is_active=True)
        .select_related("dispositivo_pai")
        .order_by("ordem")
    )

    # Build tree structure in O(N) using in-memory parent-children map
    children_map = defaultdict(list)
    for d in dispositivos:
        children_map[d.dispositivo_pai_id].append(d)

    def build_tree_nodes(parent_id=None):
        return [
            {"dispositivo": child, "children": build_tree_nodes(child.id)}
            for child in children_map.get(parent_id, [])
        ]

    tree = build_tree_nodes(None)

    context = {
        "active_nav": "normas",
        "norma": norma,
        "tree": tree,
        "total_dispositivos": dispositivos.count(),
    }

    return render(request, "legislation/norma_tree.html", context)


@ensure_csrf_cookie  # the frontend reads this cookie to send X-CSRFToken on every POST/DELETE
def chatbot_view(request: HttpRequest, session_slug: str = None) -> HttpResponse:
    """
    Chatbot interface for RAG-based legal question answering.

    GET: Renders the chat interface
    - /chatbot/ - Nova conversa (welcome state)
    - /chatbot/<slug>/ - Conversa específica (ex: /chatbot/abc123def456)

    POST: Processes questions and returns AI-generated answers
    """
    if request.method == "GET":
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
                except ChatSession.DoesNotExist:
                    # Invalid slug, redirect to new chat
                    from django.shortcuts import redirect

                    return redirect("legislation:chatbot")
            else:
                # No slug - this is a new conversation
                # Don't load any active session - show welcome state
                active_session = None
                current_session_id = None

            # Get recent sessions for sidebar (last 10)
            chat_sessions = ChatSession.objects.filter(user=request.user).order_by("-updated_at")[
                :10
            ]

            # Don't create session automatically - only create when user sends first message
            # This matches Gemini behavior: show welcome state until user actually sends something
        # GET is intentionally read-only: anonymous session state and persisted
        # chat records are initialized only when the user sends the first POST.

        prefill_question = ""
        requested_question = request.GET.get("question", "").strip()
        if requested_question and len(requested_question) <= settings.LLM_MAX_QUESTION_LENGTH:
            prefill_question = requested_question
        else:
            norma_id_raw = request.GET.get("norma_id", "").strip()
            if norma_id_raw.isdigit():
                norma_context = (
                    Norma.objects.filter(pk=int(norma_id_raw), status="consolidated")
                    .only("tipo", "numero", "ano")
                    .first()
                )
                if norma_context:
                    tipo_getter = getattr(norma_context, "get_tipo_display_name", None)
                    tipo_label = tipo_getter() if callable(tipo_getter) else norma_context.tipo
                    prefill_question = (
                        f"Sobre {tipo_label} nº {norma_context.numero}/{norma_context.ano}: "
                    )

        # Render chat interface
        context = {
            "page_title": "Assistente Jurídico - Jurix",
            "total_dispositivos": Dispositivo.objects.filter(embedding__isnull=False).count(),
            "total_normas": consolidated_normas_for_product().count(),
            "chat_sessions": chat_sessions,
            "active_session": active_session,
            "current_session_id": current_session_id,
            "current_session_slug": session_slug,
            "prefill_question": prefill_question,
            "max_question_length": settings.LLM_MAX_QUESTION_LENGTH,
            "qa_archive_mode": (
                getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
                and request.GET.get("corpus") == "archive-qa"
            ),
        }
        return render(request, "legislation/chatbot.html", context)

    elif request.method == "POST":
        limited = rate_limit_response(request)
        if limited:
            return limited

        # Process question via AJAX
        try:
            # Parse and validate JSON body (k is clamped, model must be allowed)
            data = json.loads(request.body)
            try:
                question, k, model = parse_llm_request(data)
            except InvalidLLMParams as exc:
                return JsonResponse({"success": False, "error": str(exc)}, status=400)

            if not question:
                return JsonResponse({"success": False, "error": "Pergunta vazia"}, status=400)

            logger.info("Chatbot question received (question_length=%s)", len(question))

            # Get session_id from request if regenerating
            session_id = data.get("session_id")
            regenerate = data.get("regenerate", False)

            # IMPORTANT: Create session IMMEDIATELY when user sends first message (before processing)
            # This ensures the session appears in history right away
            chat_session = None

            try:
                if request.user.is_authenticated:
                    # Try to get existing session if session_id provided
                    if session_id:
                        try:
                            chat_session = ChatSession.objects.get(id=session_id, user=request.user)
                        except ChatSession.DoesNotExist:
                            session_id = None  # Reset if session doesn't exist
                            pass

                    if not chat_session:
                        # Create new session with temporary title "Nova Conversa"
                        # Title will be generated by AI after the response
                        title = "Nova Conversa"
                        # Create session WITHOUT slug first to avoid any database errors
                        chat_session = ChatSession.objects.create(
                            user=request.user, title=title, is_active=True
                        )
                    session_id = chat_session.id
                    # ChatSession.save() generates the slug, so there is nothing to patch up here.
                    # Save user message immediately so session appears in history
                    try:
                        user_message = ChatMessage.objects.create(
                            session=chat_session, role="user", content=question
                        )
                        # Force save and refresh to ensure it's committed
                        user_message.save()
                        logger.info(
                            f"Created user message {user_message.id} for session {session_id}"
                        )

                        # Verify message was saved
                        from django.db import transaction

                        transaction.on_commit(
                            lambda: logger.info(
                                f"User message {user_message.id} committed to database"
                            )
                        )

                        # Immediate verification
                        verify_count = ChatMessage.objects.filter(session_id=session_id).count()
                        logger.info(
                            f"Session {session_id} has {verify_count} messages after creating user message"
                        )
                    except Exception as e:
                        log_exception_safely(logger, "Error creating user message", e)
                    logger.info(
                        "Created new chat session %s (slug: %s)",
                        session_id,
                        chat_session.slug,
                    )
                else:
                    # Anonymous sessions are represented by the signed Django
                    # session key. Never dereference the authenticated model
                    # session here: doing so used to raise AttributeError and
                    # silently skip conversation persistence.
                    session_id = request.session.get("temp_chat_session_id")
                    if not session_id:
                        session_id = f"temp_{request.session.session_key or uuid.uuid4().hex}"
                        request.session["temp_chat_session_id"] = session_id
                    # Update session title if it's still the default
                    # Use direct query instead of related manager to avoid errors
                    try:
                        request.session["temp_chat_title"] = question[:50] + (
                            "..." if len(question) > 50 else ""
                        )
                        request.session.modified = True
                    except Exception as e:
                        log_exception_safely(logger, "Could not update anonymous session", e)
                    # Save user message if not regenerating
                    if not regenerate:
                        try:
                            request.session.setdefault("temp_chat_messages", []).append(
                                {"role": "user", "content": question}
                            )
                            request.session.modified = True
                        except Exception as e:
                            log_exception_safely(logger, "Error creating user message", e)
                            # Continue even if message creation fails
            except Exception as e:
                log_exception_safely(logger, "Error in session management", e)
                # Continue with RAG processing even if session creation fails

            # Initialize RAG service with error handling
            try:
                rag_service = RAGService()
            except Exception as e:
                log_exception_safely(logger, "Error initializing RAG service", e)
                return JsonResponse(
                    {
                        "success": False,
                        "error": "Erro ao inicializar serviço de IA. Tente novamente.",
                    },
                    status=500,
                )

            # Generate answer with error handling
            try:
                response = rag_service.answer_question(question=question, k=k, model=model)
                if not response or "answer" not in response:
                    raise ValueError("Invalid response from RAG service")
            except Exception as e:
                log_exception_safely(logger, "Error generating answer", e)
                return JsonResponse(
                    {"success": False, "error": "Erro ao gerar resposta. Tente novamente."},
                    status=500,
                )

            # Format sources for frontend with centralized serializer
            sources = [
                serialize_dispositivo_source(source) for source in response.get("sources", [])
            ]

            # Persist assistant message (user message already saved above)
            if request.user.is_authenticated and chat_session:
                try:
                    # If regenerating, delete last assistant message
                    # Use direct query instead of related manager
                    if regenerate:
                        try:
                            last_assistant = (
                                ChatMessage.objects.filter(
                                    session_id=chat_session.id, role="assistant"
                                )
                                .order_by("-created_at")
                                .first()
                            )
                            if last_assistant:
                                last_assistant.delete()
                        except Exception as e:
                            log_exception_safely(
                                logger, "Could not delete previous assistant message", e
                            )

                    # Save assistant message with error handling
                    try:
                        assistant_message = ChatMessage.objects.create(
                            session=chat_session,
                            role="assistant",
                            content=response.get("answer", ""),
                            sources_json=sources,
                            metadata_json={
                                "model": response.get("model", model),
                                "confidence": response.get("confidence", 0.0),
                                "context_length": response.get("context_length", 0),
                                "sources_count": len(sources),
                            },
                        )
                        logger.info(
                            f"Created assistant message {assistant_message.id} for session {chat_session.id}"
                        )

                        # Force save to ensure it's committed
                        assistant_message.save()

                        # Verify message was saved - try both session_id and session object
                        message_count_by_id = ChatMessage.objects.filter(
                            session_id=chat_session.id
                        ).count()
                        message_count_by_obj = ChatMessage.objects.filter(
                            session=chat_session
                        ).count()
                        logger.info(
                            f"Session {chat_session.id} now has {message_count_by_id} messages (by session_id) or {message_count_by_obj} messages (by session object)"
                        )

                        # If counts don't match, log warning
                        if message_count_by_id != message_count_by_obj:
                            logger.warning(
                                f"Session {chat_session.id}: Message count mismatch! session_id={message_count_by_id}, session={message_count_by_obj}"
                            )

                        logger.info("Session %s message count verified", chat_session.id)

                        # Generate title using AI if this is a new session with temporary title
                        if chat_session.title == "Nova Conversa":
                            try:
                                from src.llm_engine.ollama_service import OllamaService

                                ollama = OllamaService(model=settings.OLLAMA_MODEL)

                                # Get first user message for context
                                first_user_msg = (
                                    ChatMessage.objects.filter(
                                        session_id=chat_session.id, role="user"
                                    )
                                    .order_by("created_at")
                                    .first()
                                )

                                if first_user_msg:
                                    # Generate a concise title based on the first question
                                    title_prompt = f"""Gere um título curto e descritivo (máximo 50 caracteres) para uma conversa sobre a seguinte pergunta jurídica:

"{first_user_msg.content}"

Responda APENAS com o título, sem aspas, sem explicações, sem pontuação final. O título deve ser claro e profissional."""

                                    generated_title = ollama.generate_text(
                                        prompt=title_prompt,
                                        model=settings.OLLAMA_MODEL,
                                        temperature=0.3,
                                        max_tokens=50,
                                    )

                                    if generated_title:
                                        # Clean up the title: remove quotes, extra whitespace, and limit length
                                        clean_title = (
                                            generated_title.strip().strip('"').strip("'").strip()
                                        )
                                        # Remove trailing punctuation
                                        if clean_title and clean_title[-1] in ".,;:!?":
                                            clean_title = clean_title[:-1].strip()
                                        # Limit to 50 characters
                                        if len(clean_title) > 50:
                                            clean_title = clean_title[:47] + "..."

                                        if clean_title:
                                            chat_session.title = clean_title
                                            chat_session.save(update_fields=["title"])
                                            logger.info(
                                                "Generated AI title for session %s", chat_session.id
                                            )
                            except Exception as e:
                                # If title generation fails, keep "Nova Conversa" or use fallback
                                log_exception_safely(logger, "Failed to generate AI title", e)
                                # Fallback: use first 50 chars of question
                                try:
                                    first_user_msg = (
                                        ChatMessage.objects.filter(
                                            session_id=chat_session.id, role="user"
                                        )
                                        .order_by("created_at")
                                        .first()
                                    )
                                    if first_user_msg:
                                        fallback_title = first_user_msg.content[:50] + (
                                            "..." if len(first_user_msg.content) > 50 else ""
                                        )
                                        chat_session.title = fallback_title
                                        chat_session.save(update_fields=["title"])
                                except Exception:
                                    pass  # Keep "Nova Conversa" if everything fails
                    except Exception as e:
                        log_exception_safely(logger, "Error creating assistant message", e)
                        # Continue even if message saving fails
                except Exception as e:
                    log_exception_safely(logger, "Error in message persistence", e)
                    # Continue even if persistence fails

            session_slug = chat_session.slug if chat_session else None
            public_session_id = session_id if request.user.is_authenticated else None

            # Build response with error handling
            try:
                return JsonResponse(
                    {
                        "success": True,
                        "answer": response.get("answer", ""),
                        "sources": sources,
                        "confidence": response.get("confidence", 0.0),
                        # Anonymous state is stored in the signed browser session
                        # but remains intentionally absent from the authenticated
                        # ChatSession API contract.
                        "session_id": public_session_id,
                        "session_slug": session_slug if request.user.is_authenticated else None,
                        "metadata": {
                            "model": response.get("model", model),
                            "context_length": response.get("context_length", 0),
                            "sources_count": len(sources),
                        },
                    }
                )
            except Exception as e:
                log_exception_safely(logger, "Error building JSON response", e)
                return JsonResponse(
                    {"success": False, "error": "Erro ao construir resposta"}, status=500
                )

        except json.JSONDecodeError:
            return JsonResponse({"success": False, "error": "JSON inválido"}, status=400)
        except Exception as e:
            # Details go to the log only: never echo str(e) or a traceback to the client.
            log_exception_safely(logger, "Error in chatbot POST", e)
            return JsonResponse(
                {
                    "success": False,
                    "error": "Erro ao processar pergunta. Tente novamente em instantes.",
                },
                status=500,
            )

    return JsonResponse({"error": "Method not allowed"}, status=405)
