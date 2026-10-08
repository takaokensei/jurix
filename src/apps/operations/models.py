"""Persistent operational state for integrations and scheduled jobs."""

from __future__ import annotations

import re
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

sha256_validator = RegexValidator(r"^[a-f0-9]{64}$", "Informe um SHA-256 hexadecimal válido.")


class SaplSyncState(models.Model):
    """Checkpoint and lease for one SAPL synchronization cursor.

    ``filter_fingerprint`` makes the checkpoint specific to the query scope,
    preventing a run for one year/type filter from corrupting another run's
    cursor.
    """

    source = models.CharField(max_length=100, default="sapl", db_index=True)
    filter_fingerprint = models.CharField(max_length=64)
    last_success_at = models.DateTimeField(null=True, blank=True)
    last_started_at = models.DateTimeField(null=True, blank=True)
    last_cursor = models.PositiveIntegerField(default=0)
    last_cursor_url = models.CharField(max_length=2048, blank=True)
    last_remote_timestamp = models.DateTimeField(null=True, blank=True)
    last_sync_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    last_full_sync_at = models.DateTimeField(null=True, blank=True)
    full_sweep_token = models.CharField(max_length=64, blank=True)
    full_sweep_expected_count = models.PositiveIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("source", "filter_fingerprint"),
                name="unique_sapl_sync_state_scope",
            )
        ]
        indexes = [
            models.Index(fields=("source", "last_success_at")),
            models.Index(fields=("lease_until",)),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.filter_fingerprint[:12]}"


class AttachmentRecord(models.Model):
    """Persistent metadata for session-bound chat attachments.

    The session hash is used instead of storing the raw Django session key. File
    bytes are addressed through ``storage_key`` and ``text_storage_key`` so the
    application does not depend on a container-local filesystem path.
    """

    id = models.CharField(max_length=32, primary_key=True)
    session_hash = models.CharField(max_length=64, db_index=True)
    name = models.CharField(max_length=120)
    size = models.PositiveBigIntegerField()
    content_type = models.CharField(max_length=150)
    storage_key = models.CharField(max_length=500, unique=True)
    text_storage_key = models.CharField(max_length=500, unique=True)
    sha256 = models.CharField(max_length=64, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        indexes = [
            models.Index(fields=("session_hash", "created_at")),
            models.Index(fields=("expires_at",)),
        ]

    def __str__(self) -> str:
        return self.name


class CorpusRevision(models.Model):
    """Durable, shared identity of the legal corpus used by answers and caches."""

    key = models.CharField(max_length=32, primary_key=True, default="municipal")
    revision = models.PositiveBigIntegerField(default=0)
    digest = models.CharField(max_length=64, blank=True)
    norm_count = models.PositiveIntegerField(default=0)
    device_count = models.PositiveIntegerField(default=0)
    active_event_count = models.PositiveIntegerField(default=0)
    schema_version = models.PositiveSmallIntegerField(default=1)
    segmentation_version = models.CharField(max_length=40, default="hierarchy-v1")
    completeness = models.CharField(
        max_length=16,
        choices=[
            ("unknown", "Desconhecida"),
            ("partial", "Parcial"),
            ("complete", "Declarada completa"),
        ],
        default="unknown",
    )
    generated_at = models.DateTimeField(null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self) -> str:
        return f"Corpus {self.key} r{self.revision}"


class CorpusCoverageScopeQuerySet(models.QuerySet):
    """Coverage evidence is append-only; new checks create new snapshots."""

    def update(self, **kwargs):
        raise ValidationError("Evidências de cobertura são imutáveis; registre novo snapshot.")

    def delete(self):
        raise ValidationError("Evidências de cobertura não podem ser removidas em lote.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Registre snapshots de cobertura individualmente.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Snapshots de cobertura não podem ser atualizados em lote.")


class CorpusCoverageScope(models.Model):
    """Immutable, source-scoped evidence of corpus coverage at one revision."""

    class Status(models.TextChoices):
        UNKNOWN = "unknown", "Desconhecida"
        PARTIAL = "partial", "Parcial"
        REVIEWED = "reviewed", "Revisada no escopo"

    scope_key = models.CharField(max_length=64, db_index=True)
    record_fingerprint = models.CharField(max_length=64, unique=True)
    source = models.CharField(max_length=80)
    jurisdiction = models.CharField(max_length=100)
    series = models.CharField(max_length=80)
    period_start = models.DateField(null=True, blank=True)
    period_end = models.DateField(null=True, blank=True)
    checked_until = models.DateField(null=True, blank=True)
    source_checksum = models.CharField(max_length=64, blank=True, validators=[sha256_validator])
    corpus_revision_number = models.PositiveBigIntegerField()
    corpus_revision_digest = models.CharField(max_length=64, blank=True, validators=[sha256_validator])
    last_success_at = models.DateTimeField(null=True, blank=True)
    coverage_status = models.CharField(
        max_length=16, choices=Status.choices, default=Status.UNKNOWN, db_index=True
    )
    missing_intervals = models.JSONField(null=True, blank=True)
    pending_review_count = models.PositiveIntegerField(null=True, blank=True)
    review_reason = models.TextField(blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="reviewed_corpus_coverage_scopes",
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = CorpusCoverageScopeQuerySet.as_manager()

    class Meta:
        ordering = ["source", "jurisdiction", "series", "period_start", "created_at", "pk"]
        constraints = [
            models.CheckConstraint(
                condition=(
                    models.Q(period_start__isnull=True)
                    | models.Q(period_end__isnull=True)
                    | models.Q(period_start__lte=models.F("period_end"))
                ),
                name="coverage_scope_period_order_ck",
            ),
        ]
        indexes = [
            models.Index(
                fields=["corpus_revision_digest", "scope_key", "created_at"],
                name="coverage_scope_revision_idx",
            ),
            models.Index(fields=["jurisdiction", "series", "coverage_status"], name="coverage_juris_series_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source}:{self.jurisdiction}:{self.series}:{self.coverage_status}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Snapshots de cobertura são imutáveis; crie nova revisão.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Snapshots de cobertura não podem ser removidos.")

    def clean(self):
        super().clean()
        for field in ("source", "jurisdiction", "series"):
            if not getattr(self, field, "").strip():
                raise ValidationError({field: "Informe o escopo da fonte."})
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", self.source):
            raise ValidationError({"source": "Use um identificador de fonte, não uma URL ou caminho."})
        if not re.fullmatch(r"[A-Z0-9][A-Z0-9_.-]{0,99}", self.jurisdiction):
            raise ValidationError({"jurisdiction": "Jurisdição deve ser um código estável."})
        if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{0,79}", self.series):
            raise ValidationError({"series": "Série deve ser um identificador estável."})
        if self.coverage_status == self.Status.REVIEWED:
            reviewer = self.reviewed_by
            if not (
                reviewer
                and reviewer.is_active
                and reviewer.is_staff
                and reviewer.has_perm("operations.add_corpuscoveragescope")
                and self.reviewed_at
                and self.checked_until
                and self.period_start
                and self.source_checksum
                and self.missing_intervals is not None
                and self.pending_review_count is not None
                and self.review_reason.strip()
            ):
                raise ValidationError(
                    "Escopo revisado exige revisor staff ativo, justificativa e data de corte."
                )


class ArchiveImportRun(models.Model):
    """QA/research import checkpoint; a run never implies document approval."""

    class Status(models.TextChoices):
        PLANNED = "planned", "Planejada"
        RUNNING = "running", "Em execução"
        PAUSED = "paused", "Pausada"
        COMPLETED = "completed", "Concluída"
        FAILED = "failed", "Falha"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    archive_sha256 = models.CharField(max_length=64, validators=[sha256_validator], db_index=True)
    manifest_sha256 = models.CharField(max_length=64, validators=[sha256_validator])
    manifest_path = models.CharField(
        max_length=1000,
        help_text="Path operacional privado; nunca é serializado em API pública.",
    )
    cursor = models.PositiveIntegerField(default=0)
    total_entries = models.PositiveIntegerField(default=0)
    import_limit = models.PositiveIntegerField(default=40)
    batch_size = models.PositiveIntegerField(default=10)
    stats_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PLANNED)
    lease_token = models.CharField(max_length=64, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    started_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(fields=["archive_sha256", "status"], name="archive_run_hash_status_idx"),
            models.Index(fields=["status", "lease_until"], name="archive_run_lease_idx"),
        ]

    def __str__(self) -> str:
        return f"Import {str(self.id)[:8]}:{self.status}"


class NormativeWorkItem(models.Model):
    """Bounded, resumable queue state for explicitly requested normative work."""

    class Status(models.TextChoices):
        PENDING = "pending", "Pendente"
        LEASED = "leased", "Em execução"
        AWAITING_REVIEW = "awaiting_review", "Aguardando revisão"
        COMPLETED = "completed", "Concluída"
        FAILED = "failed", "Falha"
        CANCELLED = "cancelled", "Cancelada"

    class Stage(models.TextChoices):
        CHANGED = "changed", "Alteração detectada"
        EXTRACTION = "extraction", "Extração"
        REVIEW = "review", "Revisão"
        SEGMENT = "segment", "Segmentação"
        EVENT = "event", "Eventos"
        RECONCILE = "reconcile", "Reconciliação"
        SNAPSHOT = "snapshot", "Projeção temporal"
        INVALIDATE = "invalidate", "Invalidar cache"
        EMBEDDING = "embedding", "Embeddings"

    dedupe_key = models.CharField(max_length=180, unique=True)
    source_kind = models.CharField(max_length=32, default="norma")
    source_id = models.CharField(max_length=100)
    source_revision = models.CharField(max_length=64)
    stage = models.CharField(max_length=20, choices=Stage.choices, default=Stage.CHANGED)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.PENDING, db_index=True)
    payload = models.JSONField(default=dict, blank=True)
    result = models.JSONField(default=dict, blank=True)
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=3)
    lease_token = models.UUIDField(null=True, blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    last_error = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL,
        related_name="reviewed_normative_work_items",
    )
    review_reason = models.CharField(max_length=500, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["created_at", "pk"]
        indexes = [
            models.Index(fields=["status", "created_at"], name="norm_work_status_created_idx"),
            models.Index(fields=["source_kind", "source_id", "source_revision"], name="norm_work_source_revision_idx"),
            models.Index(fields=["lease_until"], name="norm_work_lease_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.source_kind}:{self.source_id}:{self.stage}:{self.status}"
