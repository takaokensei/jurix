"""
Views for the legislation app.

Provides web interfaces for viewing consolidated legal texts and
comparing versions.
"""

import json
import logging
import re
import textwrap
import uuid
from collections import defaultdict
from typing import Any

from django.conf import settings
from django.db.models import Q
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.csrf import ensure_csrf_cookie
from django.views.generic import DetailView, ListView

from src.observability.safe_logging import log_exception_safely
from src.processing.legal_diff import build_legal_diff
from src.processing.rag_service import RAGService
from src.processing.temporal_scope import build_norma_timeline, temporal_status

from .api_limits import InvalidLLMParams, parse_llm_request, rate_limit_response
from .models import ChatMessage, ChatSession, Dispositivo, EventoAlteracao, Norma
from .norma_ordering import order_normas_by_publication
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


def _normalize_norma_query(value: object) -> str:
    return str(value or "").strip()[:MAX_NORMA_SEARCH_LENGTH]


def _norma_list_facets() -> tuple[list[str], list[int]]:
    queryset = Norma.objects.filter(status="consolidated")
    types = list(queryset.values_list("tipo", flat=True).distinct().order_by("tipo"))
    years = list(queryset.values_list("ano", flat=True).distinct().order_by("-ano"))
    return types, years


class NormaListView(ListView):
    """Responsive, filterable list of consolidated municipal norms."""

    model = Norma
    template_name = "legislation/norma_list.html"
    context_object_name = "normas"
    paginate_by = 18

    def get_queryset(self):
        queryset = Norma.objects.filter(status="consolidated")
        search_query = _normalize_norma_query(self.request.GET.get("q"))
        if search_query:
            queryset = queryset.filter(
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
        context["total_consolidated"] = Norma.objects.filter(status="consolidated").count()

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
            .select_related("dispositivo_fonte", "dispositivo_fonte__norma", "dispositivo_alvo")
            .order_by("created_at")
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
            "total_eventos": eventos_recebidos.count(),
            "total_chars": len(norma.texto_consolidado) if norma.texto_consolidado else 0,
            "has_original": bool(norma.texto_original),
            "has_consolidated": bool(norma.texto_consolidado),
        }

        if self.request.user.is_authenticated:
            from .models import Collection

            context["user_collections"] = Collection.objects.filter(
                user=self.request.user
            ).prefetch_related("normas")
        context.update(
            {
                "active_nav": "normas",
                "eventos_recebidos": eventos_recebidos,
                "official_source_url": canonical_norma_url(norma),
                "dispositivos": dispositivos,
                "root_dispositivos": root_dispositivos,
                "stats": stats,
                "consolidated_text": _presentation_consolidated_text(norma),
                "timeline": build_norma_timeline(norma),
                "temporal_status": temporal_status(norma),
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

    return render(request, "legislation/norma_compare.html", context)


def norma_pdf_export_view(request: HttpRequest, pk: int) -> HttpResponse:
    """Generate a paginated, print-ready PDF of the consolidated norm."""
    norma = get_object_or_404(Norma, pk=pk)
    import fitz

    document = fitz.open()
    title = f"{norma.get_tipo_display_name()} nº {norma.numero}/{norma.ano}"
    body = _presentation_consolidated_text(norma) or "Texto consolidado não disponível."
    lines = []
    for raw_line in body.splitlines():
        lines.extend(textwrap.wrap(raw_line, width=96, replace_whitespace=False) or [""])
    page_lines = 52
    for offset in range(0, len(lines) or 1, page_lines):
        page = document.new_page(width=595, height=842)
        page.insert_text(
            (48, 48), "JURIX · NORMA CONSOLIDADA", fontsize=9, color=(0.18, 0.43, 0.78)
        )
        page.insert_text((48, 75), title, fontsize=16, fontname="hebo", color=(0.06, 0.10, 0.18))
        page.insert_text(
            (48, 94), "Exportação do texto consolidado", fontsize=9, color=(0.35, 0.40, 0.48)
        )
        page.insert_textbox(
            fitz.Rect(48, 120, 547, 790),
            "\n".join(lines[offset : offset + page_lines]),
            fontsize=9.5,
            lineheight=1.45,
            fontname="cour",
            color=(0.10, 0.12, 0.16),
        )
        page.insert_text(
            (48, 818),
            f"Fonte oficial: SAPL · Página {offset // page_lines + 1}",
            fontsize=8,
            color=(0.40, 0.44, 0.50),
        )
    payload = document.tobytes(garbage=4, deflate=True)
    document.close()
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
            "total_normas": Norma.objects.filter(status="consolidated").count(),
            "chat_sessions": chat_sessions,
            "active_session": active_session,
            "current_session_id": current_session_id,
            "current_session_slug": session_slug,
            "prefill_question": prefill_question,
            "max_question_length": settings.LLM_MAX_QUESTION_LENGTH,
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
