"""Persistent operational state for integrations and scheduled jobs."""

from __future__ import annotations

from django.db import models


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
    last_remote_timestamp = models.DateTimeField(null=True, blank=True)
    last_sync_count = models.PositiveIntegerField(default=0)
    last_error = models.TextField(blank=True)
    lease_until = models.DateTimeField(null=True, blank=True)
    lease_token = models.CharField(max_length=64, blank=True)
    last_full_sync_at = models.DateTimeField(null=True, blank=True)
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
