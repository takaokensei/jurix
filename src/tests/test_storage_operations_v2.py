"""Operational tests for attachment lifecycle commands."""
from __future__ import annotations

from datetime import timedelta
from io import StringIO
from unittest.mock import patch

from django.core.management import call_command
from django.test import TestCase
from django.utils import timezone

from src.apps.operations.models import AttachmentRecord


class AttachmentPruneCommandTests(TestCase):
    def make_record(self, expires_at):
        return AttachmentRecord.objects.create(
            id="a" * 32,
            session_hash="b" * 64,
            name="arquivo.pdf",
            size=10,
            content_type="application/pdf",
            storage_key="attachments/x.pdf",
            text_storage_key="attachments/x.txt",
            sha256="c" * 64,
            expires_at=expires_at,
        )

    @patch("src.apps.operations.management.commands.prune_attachment_storage.get_attachment_storage")
    def test_dry_run_does_not_delete(self, get_storage):
        record = self.make_record(timezone.now() - timedelta(days=1))
        out = StringIO()
        call_command("prune_attachment_storage", stdout=out)
        assert AttachmentRecord.objects.filter(pk=record.pk).exists()
        get_storage.return_value.delete.assert_not_called()

    @patch("src.apps.operations.management.commands.prune_attachment_storage.get_attachment_storage")
    def test_execute_removes_storage_and_metadata(self, get_storage):
        record = self.make_record(timezone.now() - timedelta(days=1))
        storage = get_storage.return_value
        call_command("prune_attachment_storage", "--execute")
        assert not AttachmentRecord.objects.filter(pk=record.pk).exists()
        assert storage.delete.call_count == 2
