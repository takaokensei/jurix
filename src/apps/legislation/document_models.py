"""Versioned source-document records; these never overwrite legacy Norma text."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from pathlib import PurePosixPath

from django.core.exceptions import ValidationError
from django.core.validators import RegexValidator
from django.db import models

from src.apps.core.models import TimeStampedModel

sha256_validator = RegexValidator(r"^[a-f0-9]{64}$", "Informe um SHA-256 hexadecimal válido.")


class ImmutableRecordQuerySet(models.QuerySet):
    """Stop bulk ORM mutations from bypassing version-level model guards."""

    def update(self, **kwargs):
        raise ValidationError("Registros versionados são imutáveis; crie uma nova revisão.")

    def delete(self):
        raise ValidationError("Registros versionados não podem ser removidos em lote.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Crie revisões versionadas pelo serviço do modelo, sem bulk_create.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Registros versionados não podem ser atualizados em lote.")


class DocumentoNormativo(TimeStampedModel):
    """Immutable identity and provenance for one normative source document."""

    class SourceKind(models.TextChoices):
        ARCHIVE = "archive", "Acervo local"
        SAPL = "sapl", "SAPL"
        OFFICIAL_GAZETTE = "official_gazette", "Diário oficial"
        LEGACY = "legacy", "Registro legado"

    class Role(models.TextChoices):
        ORIGINAL = "original", "Original"
        REPUBLICATION = "republicacao", "Republicação"
        RECTIFICATION = "retificacao", "Retificação"
        ANNEX = "anexo", "Anexo"
        UNDETERMINED = "indeterminado", "Indeterminado"

    class ConditionOfUse(models.TextChoices):
        UNKNOWN = "unknown", "Desconhecida"
        PUBLIC_RECORD_REVIEWED = "public_record_reviewed", "Registro público revisado"
        PERMISSION_REQUIRED = "permission_required", "Permissão necessária"
        LICENSED = "licensed", "Licenciada"

    class ExtractionStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        EXTRACTED = "extracted", "Extraída"
        PARTIAL = "partial", "Parcial"
        NEEDS_REVIEW = "needs_review", "Requer revisão"
        FAILED = "failed", "Falha"

    class ReviewStatus(models.TextChoices):
        PENDING = "pending", "Pendente"
        IN_REVIEW = "in_review", "Em revisão"
        APPROVED = "approved", "Aprovado"
        REJECTED = "rejected", "Rejeitado"

    public_id = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    document_key = models.CharField(max_length=64, unique=True)
    norma = models.ForeignKey(
        "legislation.Norma",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="documentos_normativos",
    )
    source_kind = models.CharField(max_length=24, choices=SourceKind.choices)
    source_ref = models.CharField(max_length=1000)
    archive_sha256 = models.CharField(
        max_length=64, blank=True, validators=[sha256_validator], db_index=True
    )
    entry_index = models.PositiveIntegerField(null=True, blank=True)
    entry_name = models.CharField(max_length=1000, blank=True)
    original_filename = models.CharField(max_length=500, blank=True)
    role = models.CharField(max_length=20, choices=Role.choices, default=Role.UNDETERMINED)
    storage_key = models.CharField(
        max_length=500,
        blank=True,
        help_text="Chave relativa do storage; nunca um caminho absoluto de disco.",
    )
    size_bytes = models.PositiveBigIntegerField(default=0)
    content_sha256 = models.CharField(
        max_length=64, validators=[sha256_validator], db_index=True
    )
    official_url = models.URLField(max_length=1000, null=True, blank=True)
    collected_at = models.DateTimeField(null=True, blank=True)
    condition_of_use = models.CharField(
        max_length=32, choices=ConditionOfUse.choices, default=ConditionOfUse.UNKNOWN
    )
    metadata_json = models.JSONField(default=dict, blank=True)
    conflicts_json = models.JSONField(default=list, blank=True)
    extraction_status = models.CharField(
        max_length=20, choices=ExtractionStatus.choices, default=ExtractionStatus.PENDING
    )
    review_status = models.CharField(
        max_length=20, choices=ReviewStatus.choices, default=ReviewStatus.PENDING
    )
    accepted_extraction = models.ForeignKey(
        "legislation.ExtracaoDocumento",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_by_documents",
    )

    class Meta:
        ordering = ["created_at", "public_id"]
        indexes = [
            models.Index(fields=["norma", "role"], name="doc_norma_role_idx"),
            models.Index(fields=["source_kind", "review_status"], name="doc_source_review_idx"),
        ]

    def clean(self):
        super().clean()
        key = self.storage_key.replace("\\", "/")
        if key and (
            PurePosixPath(key).is_absolute()
            or key.startswith("//")
            or re.match(r"^[A-Za-z]:", key)
            or ".." in key.split("/")
        ):
            raise ValidationError({"storage_key": "A chave deve ser relativa e permanecer no storage."})
        if self.accepted_extraction_id and self.accepted_extraction.documento_id != self.pk:
            raise ValidationError({"accepted_extraction": "A extração deve pertencer a este documento."})

    def save(self, *args, **kwargs):
        self.full_clean()
        return super().save(*args, **kwargs)

    def __str__(self) -> str:
        return self.original_filename or f"Documento {self.public_id}"


class ExtracaoDocumento(TimeStampedModel):
    """Versioned text output; a re-run creates a new extraction, never rewrites one."""

    class Status(models.TextChoices):
        COMPLETE = "complete", "Completa"
        PARTIAL = "partial", "Parcial"
        UNREADABLE = "unreadable", "Ilegível"

    documento = models.ForeignKey(
        DocumentoNormativo,
        on_delete=models.PROTECT,
        related_name="extracoes",
    )
    extractor_version = models.CharField(max_length=120)
    policy_fingerprint = models.CharField(max_length=64, validators=[sha256_validator])
    text_version = models.CharField(max_length=80)
    raw_text = models.TextField(blank=True)
    legal_text = models.TextField(blank=True)
    raw_text_sha256 = models.CharField(max_length=64, validators=[sha256_validator])
    legal_text_sha256 = models.CharField(max_length=64, validators=[sha256_validator])
    page_count = models.PositiveIntegerField(default=0)
    page_map_json = models.JSONField(default=list, blank=True)
    metadata_candidates_json = models.JSONField(default=dict, blank=True)
    quality_json = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PARTIAL)
    extraction_sha256 = models.CharField(max_length=64, validators=[sha256_validator])
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableRecordQuerySet.as_manager()

    class Meta:
        ordering = ["documento", "created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["documento", "extractor_version", "policy_fingerprint"],
                name="unique_doc_extraction_policy",
            )
        ]
        indexes = [
            models.Index(fields=["documento", "status"], name="extr_doc_status_idx"),
            models.Index(fields=["extraction_sha256"], name="extr_sha256_idx"),
        ]

    def clean(self):
        super().clean()
        if len(self.page_map_json or []) > 200:
            raise ValidationError({"page_map_json": "O mapa não pode exceder 200 páginas."})
        try:
            encoded = json.dumps(self.page_map_json, ensure_ascii=False).encode("utf-8")
        except (TypeError, ValueError) as exc:
            raise ValidationError({"page_map_json": "Mapa de páginas deve ser JSON válido."}) from exc
        if len(encoded) > 1_048_576:
            raise ValidationError({"page_map_json": "O mapa de páginas excede 1 MiB."})
        if self.raw_text_sha256 and self.raw_text_sha256 != hashlib.sha256(
            (self.raw_text or "").encode("utf-8")
        ).hexdigest():
            raise ValidationError({"raw_text_sha256": "Hash do texto bruto não confere."})
        if self.legal_text_sha256 and self.legal_text_sha256 != hashlib.sha256(
            (self.legal_text or "").encode("utf-8")
        ).hexdigest():
            raise ValidationError({"legal_text_sha256": "Hash do texto legal não confere."})
        for span in self.page_map_json or []:
            if not isinstance(span, dict):
                raise ValidationError({"page_map_json": "Cada span do mapa deve ser objeto."})
            start, end = span.get("start"), span.get("end")
            if start is not None or end is not None:
                if not isinstance(start, int) or not isinstance(end, int) or not (0 <= start < end <= len(self.legal_text or "")):
                    raise ValidationError({"page_map_json": "Offset do mapa fora da versão legal_text."})

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Extrações existentes são imutáveis; crie uma nova revisão.")
        self.raw_text_sha256 = hashlib.sha256((self.raw_text or "").encode("utf-8")).hexdigest()
        self.legal_text_sha256 = hashlib.sha256((self.legal_text or "").encode("utf-8")).hexdigest()
        if not self.extraction_sha256:
            digest_input = "\0".join(
                (self.documento.document_key, self.extractor_version, self.policy_fingerprint, self.legal_text_sha256)
            )
            self.extraction_sha256 = hashlib.sha256(digest_input.encode("utf-8")).hexdigest()
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Extrações são registros imutáveis e não podem ser removidas.")

    def __str__(self) -> str:
        return f"{self.documento_id}:{self.extractor_version}"


class DocumentoDispositivo(models.Model):
    """Immutable device segmentation belonging to one frozen extraction."""

    class Marker(models.TextChoices):
        NONE = "none", "Sem marca"
        VETOED = "vetado", "Vetado"
        REVOKED = "revogado", "Revogado"
        UNKNOWN = "unknown", "Desconhecido"

    extracao = models.ForeignKey(
        ExtracaoDocumento,
        on_delete=models.PROTECT,
        related_name="dispositivos_documentais",
    )
    structural_key = models.CharField(max_length=160)
    parent_key = models.CharField(max_length=160, null=True, blank=True)
    tipo = models.CharField(max_length=32)
    numero = models.CharField(max_length=80)
    ordem = models.PositiveIntegerField()
    texto = models.TextField()
    start_offset = models.PositiveIntegerField(null=True, blank=True)
    end_offset = models.PositiveIntegerField(null=True, blank=True)
    page_index = models.PositiveIntegerField(null=True, blank=True)
    marker = models.CharField(max_length=12, choices=Marker.choices, default=Marker.NONE)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = ImmutableRecordQuerySet.as_manager()

    class Meta:
        ordering = ["extracao", "ordem"]
        constraints = [
            models.UniqueConstraint(
                fields=["extracao", "structural_key"], name="unique_extraction_device_key"
            )
        ]
        indexes = [models.Index(fields=["extracao", "ordem"], name="doc_device_order_idx")]

    def __str__(self) -> str:
        return f"{self.tipo} {self.numero} ({self.structural_key})"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Dispositivos documentais são imutáveis; gere nova extração.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Dispositivos documentais não podem ser removidos.")

    def clean(self):
        super().clean()
        if (self.start_offset is None) != (self.end_offset is None):
            raise ValidationError("start_offset e end_offset devem ser ambos definidos ou nulos.")
        if self.start_offset is not None:
            if not self.start_offset < self.end_offset <= len(self.extracao.legal_text):
                raise ValidationError("Offsets do dispositivo fora do legal_text da extração.")
            if self.extracao.legal_text[self.start_offset : self.end_offset] != self.texto:
                raise ValidationError("Texto do dispositivo não corresponde aos offsets congelados.")


class SnapshotAppendOnlyQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Snapshots são append-only; uma nova projeção gera outro fingerprint.")

    def delete(self):
        raise ValidationError("Snapshots são preservados para auditoria.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Snapshots não podem ser atualizados em lote.")


class NormativeSnapshot(models.Model):
    """Immutable, content-addressed projection of a reviewed normative source."""

    class Status(models.TextChoices):
        COMPLETE = "complete", "Completa"
        PARTIAL = "partial", "Parcial"
        NOT_RECONSTRUCTABLE = "not_reconstructable", "Não reconstruível"

    norma = models.ForeignKey(
        "legislation.Norma", on_delete=models.PROTECT, related_name="normative_snapshots"
    )
    as_of = models.DateField(db_index=True)
    status = models.CharField(max_length=24, choices=Status.choices)
    input_sha256 = models.CharField(max_length=64, validators=[sha256_validator])
    content_sha256 = models.CharField(max_length=64, validators=[sha256_validator])
    coverage_json = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    objects = SnapshotAppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["norma_id", "as_of", "created_at", "pk"]
        constraints = [
            models.UniqueConstraint(
                fields=["norma", "as_of", "input_sha256"], name="unique_normative_snapshot_input"
            )
        ]
        indexes = [models.Index(fields=["norma", "as_of", "status"], name="norm_snapshot_lookup_idx")]

    def __str__(self) -> str:
        return f"Snapshot norma {self.norma_id} em {self.as_of} ({self.status})"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Snapshots são imutáveis; uma nova entrada exige outro fingerprint.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Snapshots normativos são preservados para auditoria.")

class SnapshotDispositivo(models.Model):
    """One immutable structural device and its legal/provenance state in a snapshot."""

    snapshot = models.ForeignKey(
        NormativeSnapshot, on_delete=models.PROTECT, related_name="dispositivos"
    )
    base_device = models.ForeignKey(
        DocumentoDispositivo, on_delete=models.PROTECT, related_name="snapshot_uses"
    )
    structural_key = models.CharField(max_length=160)
    text = models.TextField()
    legal_status = models.CharField(max_length=24, default="in_force")
    provenance_json = models.JSONField(default=dict, blank=True)
    objects = SnapshotAppendOnlyQuerySet.as_manager()

    class Meta:
        ordering = ["base_device__ordem", "structural_key"]
        constraints = [
            models.UniqueConstraint(
                fields=["snapshot", "structural_key"], name="unique_snapshot_device_key"
            )
        ]

    def __str__(self) -> str:
        return f"{self.structural_key} no snapshot {self.snapshot_id}"

    def save(self, *args, **kwargs):
        if self.pk and type(self).objects.filter(pk=self.pk).exists():
            raise ValidationError("Dispositivos de snapshot são imutáveis.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Dispositivos de snapshot são preservados para auditoria.")
