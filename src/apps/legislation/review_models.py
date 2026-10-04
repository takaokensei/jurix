"""Append-only human decisions over a document or a legal relation."""

from __future__ import annotations

import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q


class AppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Revisões são append-only; registre nova decisão.")

    def delete(self):
        raise ValidationError("Revisões jurídicas não podem ser removidas em lote.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Revisões devem ser criadas com validação individual.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Revisões jurídicas não podem ser atualizadas em lote.")


class RevisaoJuridica(models.Model):
    class Decision(models.TextChoices):
        APPROVE = "approve", "Aprovar"
        REJECT = "reject", "Rejeitar"
        SUPERSEDE = "supersede", "Substituir decisão"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    documento = models.ForeignKey(
        "legislation.DocumentoNormativo",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revisoes_juridicas",
    )
    evento = models.ForeignKey(
        "legislation.EventoAlteracao",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="revisoes_juridicas",
    )
    target_fingerprint = models.CharField(max_length=64)
    decision = models.CharField(max_length=12, choices=Decision.choices)
    reason = models.TextField()
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name="jurix_legal_reviews",
    )
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    objects = AppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(documento__isnull=False, evento__isnull=True) | Q(documento__isnull=True, evento__isnull=False)),
                name="legal_review_exactly_one_target",
            )
        ]
        indexes = [models.Index(fields=["decision", "created_at"], name="review_action_time_idx")]

    def __str__(self) -> str:
        return f"{self.decision}:{self.public_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Revisões jurídicas são append-only; registre nova decisão.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Revisões jurídicas não podem ser removidas.")

    def clean(self):
        super().clean()
        if bool(self.documento_id) == bool(self.evento_id):
            raise ValidationError("A revisão deve apontar exatamente para documento ou evento.")
        if not self.reason.strip():
            raise ValidationError({"reason": "Informe o motivo da decisão."})
