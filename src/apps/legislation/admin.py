import json

from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.event_review import (
    EventReviewForm,
    EventTemporalReviewForm,
    event_review_fingerprint,
    event_review_status,
    review_event,
    review_event_effective_date,
)

from .models import ChatMessage, ChatSession, Collection, Dispositivo, EventoAlteracao, Norma


@admin.register(Norma)
class NormaAdmin(admin.ModelAdmin):
    list_display = (
        "tipo",
        "numero",
        "ano",
        "status_badge",
        "data_publicacao",
        "data_vigencia",
        "vacatio_status",
        "created_at",
    )
    list_filter = ("tipo", "ano", "status", "needs_review", "data_publicacao")
    search_fields = ("numero", "ementa", "tipo", "sapl_id")
    ordering = ("-ano", "-numero")
    date_hierarchy = "data_publicacao"
    readonly_fields = ("created_at", "updated_at", "sapl_metadata")

    fieldsets = (
        ("Identificação", {"fields": ("tipo", "numero", "ano", "ementa", "observacao")}),
        ("Datas", {"fields": ("data_publicacao", "data_vigencia")}),
        ("Conteúdo", {"fields": ("texto_original", "pdf_url", "pdf_path")}),
        (
            "Integração SAPL",
            {"fields": ("sapl_id", "sapl_url", "sapl_metadata"), "classes": ("collapse",)},
        ),
        (
            "Controle de Processamento",
            {
                "fields": ("status", "needs_review", "processing_error"),
            },
        ),
        ("Timestamps", {"fields": ("created_at", "updated_at"), "classes": ("collapse",)}),
    )

    def status_badge(self, obj):
        """Exibe badge colorido para o status."""
        colors = {
            "consolidated": "#10b981",  # green
            "ready": "#3b82f6",  # blue
            "failed": "#ef4444",  # red
            "pending": "#f59e0b",  # yellow
        }
        color = colors.get(obj.status, "#6b7280")
        return format_html(
            '<span style="background: {}; color: white; padding: 2px 8px; border-radius: 4px; font-size: 11px;">{}</span>',
            color,
            obj.get_status_display(),
        )

    status_badge.short_description = "Status"

    def vacatio_status(self, obj):
        """Indica se está em vacatio legis."""
        if obj.is_em_vacatio_legis():
            return format_html('<span style="color: #f59e0b;">⚠️ Em vacatio legis</span>')
        return "—"

    vacatio_status.short_description = "Vacatio Legis"


@admin.register(Dispositivo)
class DispositivoAdmin(admin.ModelAdmin):
    list_display = ("norma", "tipo", "numero", "texto_preview", "has_embedding")
    list_filter = ("tipo", "norma__tipo", "norma__ano")
    search_fields = ("texto", "numero", "norma__numero", "norma__tipo")
    ordering = ("norma", "ordem")
    readonly_fields = ("created_at", "updated_at", "embedding_generated_at")

    def texto_preview(self, obj):
        """Preview do texto (primeiros 100 caracteres)."""
        return obj.texto[:100] + ("..." if len(obj.texto) > 100 else "")

    texto_preview.short_description = "Texto"

    def has_embedding(self, obj):
        """Indica se tem embedding."""
        return "✅" if obj.embedding else "❌"

    has_embedding.short_description = "Embedding"


@admin.register(EventoAlteracao)
class EventoAlteracaoAdmin(admin.ModelAdmin):
    change_form_template = "admin/legislation/eventoalteracao/change_form.html"
    list_display = ("dispositivo_fonte", "acao", "norma_alvo", "dispositivo_alvo", "review_status")
    list_filter = ("acao", "validado", "extraction_method", "is_active")
    search_fields = ("target_text", "dispositivo_fonte__texto", "norma_alvo__numero")
    ordering = ("-created_at",)
    actions = None

    class Media:
        css = {"all": ("css/jurix-admin-review.css",)}

    def render_change_form(self, request, context, *args, **kwargs):
        obj = context.get("original")
        context["review_status"] = event_review_status(obj) if obj else "pending"
        return super().render_change_form(request, context, *args, **kwargs)

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields) + (
            "source_text_display",
            "evidence_display",
            "target_candidate_display",
            "review_status",
        )

    def get_fieldsets(self, request, obj=None):
        return (
            (
                "Evento extraído",
                {"fields": ("dispositivo_fonte", "source_text_display", "acao", "target_text")},
            ),
            (
                "Alvo e evidência",
                {
                    "fields": (
                        "norma_alvo",
                        "dispositivo_alvo",
                        "target_candidate_display",
                        "evidence_display",
                    )
                },
            ),
            (
                "Estado de revisão",
                {"fields": ("review_status", "validado", "review_revision", "is_active")},
            ),
            (
                "Auditoria técnica",
                {
                    "fields": (
                        "referencia_tipo",
                        "referencia_numero",
                        "revision_fingerprint",
                        "provenance_json",
                        "target_reference_json",
                        "evidence_json",
                        "effective_on",
                        "effective_date_status",
                        "effective_date_basis",
                        "extraction_confidence",
                        "extraction_method",
                        "created_at",
                        "updated_at",
                    )
                },
            ),
        )

    @admin.display(description="Texto literal do dispositivo fonte")
    def source_text_display(self, obj):
        return obj.dispositivo_fonte.texto if obj and obj.dispositivo_fonte_id else "—"

    @admin.display(description="Evidência literal e offsets")
    def evidence_display(self, obj):
        return json.dumps(obj.evidence_json or {}, ensure_ascii=False, indent=2) if obj else "—"

    @admin.display(description="Candidatura tipada do alvo")
    def target_candidate_display(self, obj):
        return (
            json.dumps(obj.target_reference_json or {}, ensure_ascii=False, indent=2)
            if obj
            else "—"
        )

    @admin.display(description="Revisão jurídica")
    def review_status(self, obj):
        return {
            "pending": "Pendente",
            "confirmed": "Confirmada por revisor",
            "rejected": "Rejeitada por revisor",
        }[event_review_status(obj)]

    def get_urls(self):
        custom = [
            path(
                "<path:object_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="legislation_eventoalteracao_review",
            ),
            path(
                "<path:object_id>/temporal-review/",
                self.admin_site.admin_view(self.temporal_review_view),
                name="legislation_eventoalteracao_temporal_review",
            ),
        ]
        return custom + super().get_urls()

    def review_view(self, request, object_id):
        event = get_object_or_404(
            EventoAlteracao.objects.select_related(
                "dispositivo_fonte__norma", "norma_alvo", "dispositivo_alvo", "review_revision"
            ),
            pk=object_id,
        )
        if not self.has_change_permission(request, event):
            raise PermissionDenied
        if request.method == "POST":
            form = EventReviewForm(request.POST, event=event)
            if form.is_valid():
                try:
                    review = review_event(
                        event_id=event.pk,
                        actor=request.user,
                        decision=form.cleaned_data["decision"],
                        reason=form.cleaned_data["reason"],
                        expected_fingerprint=form.cleaned_data["expected_fingerprint"],
                        target_norma_id=int(form.cleaned_data["target_norma_id"])
                        if form.cleaned_data["target_norma_id"]
                        else None,
                        target_dispositivo_id=int(form.cleaned_data["target_dispositivo_id"])
                        if form.cleaned_data["target_dispositivo_id"]
                        else None,
                    )
                except (ValidationError, PermissionDenied) as exc:
                    messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
                else:
                    messages.success(
                        request, f"Decisão registrada ({review.decision}); histórico preservado."
                    )
                    return HttpResponseRedirect(
                        reverse("admin:legislation_eventoalteracao_change", args=[event.pk])
                    )
        else:
            form = EventReviewForm(
                event=event,
                initial={
                    "target_norma_id": str(event.norma_alvo_id or ""),
                    "target_dispositivo_id": str(event.dispositivo_alvo_id or ""),
                    "decision": "approve",
                },
            )
        context = {
            **self.admin_site.each_context(request),
            "media": self.media,
            "opts": self.model._meta,
            "original": event,
            "title": f"Revisar evento: {event}",
            "event": event,
            "form": form,
            "fingerprint": event_review_fingerprint(event),
            "review_status": event_review_status(event),
            "source_text": event.dispositivo_fonte.texto,
            "evidence_json": json.dumps(event.evidence_json or {}, ensure_ascii=False, indent=2),
            "target_json": json.dumps(
                event.target_reference_json or {}, ensure_ascii=False, indent=2
            ),
        }
        return TemplateResponse(request, "admin/legislation/eventoalteracao/review.html", context)

    def temporal_review_view(self, request, object_id):
        event = get_object_or_404(
            EventoAlteracao.objects.select_related(
                "dispositivo_fonte__norma", "norma_alvo", "dispositivo_alvo", "review_revision"
            ),
            pk=object_id,
        )
        if not self.has_change_permission(request, event):
            raise PermissionDenied
        if request.method == "POST":
            form = EventTemporalReviewForm(request.POST, event=event)
            if form.is_valid():
                try:
                    review = review_event_effective_date(
                        event_id=event.pk,
                        actor=request.user,
                        effective_on=form.cleaned_data["effective_on"],
                        evidence_quote=form.cleaned_data["evidence_quote"],
                        reason=form.cleaned_data["reason"],
                        expected_fingerprint=form.cleaned_data["expected_fingerprint"],
                    )
                except (ValidationError, PermissionDenied) as exc:
                    messages.error(request, " ".join(getattr(exc, "messages", [str(exc)])))
                else:
                    messages.success(
                        request,
                        f"Data de efeito registrada na revisão {review.public_id}; relação e efeito permanecem decisões distintas.",
                    )
                    return HttpResponseRedirect(
                        reverse("admin:legislation_eventoalteracao_change", args=[event.pk])
                    )
        else:
            form = EventTemporalReviewForm(event=event)
        context = {
            **self.admin_site.each_context(request),
            "media": self.media,
            "opts": self.model._meta,
            "original": event,
            "title": f"Revisar data de efeito: {event}",
            "event": event,
            "form": form,
            "source_text": event.dispositivo_fonte.texto,
            "review_status": event_review_status(event),
        }
        return TemplateResponse(
            request, "admin/legislation/eventoalteracao/temporal_review.html", context
        )


@admin.register(DocumentoNormativo)
class DocumentoNormativoAdmin(admin.ModelAdmin):
    list_display = (
        "original_filename",
        "role",
        "extraction_status",
        "review_status",
        "condition_of_use",
        "norma",
        "created_at",
    )
    list_filter = ("source_kind", "role", "extraction_status", "review_status", "condition_of_use")
    search_fields = ("original_filename", "document_key", "content_sha256", "norma__numero")
    ordering = ("created_at",)
    readonly_fields = (
        "public_id",
        "document_key",
        "norma",
        "source_kind",
        "source_ref",
        "archive_sha256",
        "entry_index",
        "entry_name",
        "original_filename",
        "role",
        "storage_key",
        "size_bytes",
        "content_sha256",
        "official_url",
        "metadata_json",
        "conflicts_json",
        "extraction_status",
        "review_status",
        "accepted_extraction",
        "promotion_fingerprint_display",
        "created_at",
        "updated_at",
    )
    fields = readonly_fields

    @admin.display(description="Fingerprint atual da revisão")
    def promotion_fingerprint_display(self, obj):
        return promotion_fingerprint(obj) if obj else "—"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ChatSession)
class ChatSessionAdmin(admin.ModelAdmin):
    list_display = ("title", "user", "is_active", "message_count", "created_at", "updated_at")
    list_filter = ("is_active", "created_at", "updated_at")
    search_fields = ("title", "user__username")
    ordering = ("-updated_at",)
    readonly_fields = ("created_at", "updated_at")

    def message_count(self, obj):
        """Conta mensagens na sessão."""
        return obj.messages.count()

    message_count.short_description = "Mensagens"


@admin.register(ChatMessage)
class ChatMessageAdmin(admin.ModelAdmin):
    list_display = ("session", "role", "content_preview", "created_at")
    list_filter = ("role", "created_at", "session__user")
    search_fields = ("content", "session__title", "session__user__username")
    ordering = ("-created_at",)
    readonly_fields = ("created_at", "updated_at")

    def content_preview(self, obj):
        """Preview do conteúdo."""
        return obj.content[:100] + ("..." if len(obj.content) > 100 else "")

    content_preview.short_description = "Conteúdo"


@admin.register(Collection)
class CollectionAdmin(admin.ModelAdmin):
    list_display = ("name", "user", "norma_count", "updated_at")
    list_filter = ("updated_at",)
    search_fields = ("name", "description", "user__username")
    filter_horizontal = ("normas",)
    readonly_fields = ("created_at", "updated_at")

    def norma_count(self, obj):
        return obj.normas.count()

    norma_count.short_description = "Normas"
