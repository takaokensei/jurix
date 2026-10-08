from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import HttpResponseRedirect
from django.shortcuts import get_object_or_404
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils.html import format_html

from src.apps.ingestion.normative_impact import resolve_normative_review
from src.apps.ingestion.normative_tasks import process_normative_work_item_task

from .models import NormativeWorkItem


class NormativeWorkItemReviewForm(forms.Form):
    decision = forms.ChoiceField(
        label="Decisão",
        choices=(("approve", "Aprovar e continuar"), ("reject", "Rejeitar e encerrar")),
    )
    reason = forms.CharField(
        label="Justificativa",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 4}),
        help_text="Registre o motivo da decisão. A justificativa fica vinculada ao item.",
    )

    def clean_reason(self):
        reason = self.cleaned_data["reason"].strip()
        if not reason:
            raise forms.ValidationError("Informe a justificativa da decisão.")
        return reason


@admin.register(NormativeWorkItem)
class NormativeWorkItemAdmin(admin.ModelAdmin):
    list_display = ("id", "source_kind", "source_id", "stage", "status", "updated_at", "review_link")
    list_filter = ("status", "stage", "source_kind")
    search_fields = ("source_id", "dedupe_key", "last_error")
    readonly_fields = tuple(field.name for field in NormativeWorkItem._meta.fields)
    ordering = ("status", "created_at", "pk")
    list_per_page = 50

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_urls(self):
        return [
            path(
                "<path:object_id>/review/",
                self.admin_site.admin_view(self.review_view),
                name="operations_normativeworkitem_review",
            ),
        ] + super().get_urls()

    @admin.display(description="Revisão")
    def review_link(self, item):
        if item.status != NormativeWorkItem.Status.AWAITING_REVIEW:
            return "—"
        url = reverse("admin:operations_normativeworkitem_review", args=[item.pk])
        return format_html('<a href="{}">Revisar checkpoint</a>', url)

    def review_view(self, request, object_id):
        if not self.has_change_permission(request):
            raise PermissionDenied
        item = get_object_or_404(NormativeWorkItem, pk=object_id)
        if item.status != NormativeWorkItem.Status.AWAITING_REVIEW:
            messages.info(request, "Este item não está mais aguardando revisão.")
            return HttpResponseRedirect(reverse("admin:operations_normativeworkitem_changelist"))

        if request.method == "POST":
            form = NormativeWorkItemReviewForm(request.POST)
            if form.is_valid():
                approved = form.cleaned_data["decision"] == "approve"
                try:
                    resolved = resolve_normative_review(
                        item.pk,
                        actor=request.user,
                        approved=approved,
                        reason=form.cleaned_data["reason"],
                    )
                except (PermissionError, RuntimeError, ValueError, ValidationError) as exc:
                    messages.error(request, str(exc))
                else:
                    if approved and resolved.status == NormativeWorkItem.Status.PENDING:
                        process_normative_work_item_task.apply_async(
                            args=[resolved.pk], queue="normative_qa"
                        )
                    decision_label = "aprovada; processamento retomado" if approved else "rejeitada"
                    messages.success(request, f"Revisão {decision_label} e registrada.")
                    return HttpResponseRedirect(
                        reverse("admin:operations_normativeworkitem_change", args=[resolved.pk])
                    )
        else:
            form = NormativeWorkItemReviewForm(initial={"decision": "approve"})

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": f"Revisar item normativo #{item.pk}",
            "item": item,
            "form": form,
        }
        return TemplateResponse(request, "admin/operations/normativeworkitem/review.html", context)
