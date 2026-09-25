"""Audit persistent attachment metadata against the configured object store."""

from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from src.apps.legislation.attachment_storage import get_attachment_storage
from src.apps.operations.models import AttachmentRecord


class Command(BaseCommand):
    help = "Verifica integridade dos objetos de anexos referenciados no PostgreSQL."

    def add_arguments(self, parser):
        parser.add_argument("--verify-hash", action="store_true")
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--fail-on-missing", action="store_true")

    def handle(self, *args, **options):
        storage = get_attachment_storage()
        queryset = AttachmentRecord.objects.order_by("created_at")
        if options["limit"] > 0:
            queryset = queryset[: options["limit"]]

        checked = missing = mismatched = expired = 0
        now = timezone.now()

        for record in queryset:
            checked += 1
            if record.expires_at <= now:
                expired += 1

            try:
                original = storage.read_bytes(record.storage_key)
                storage.read_bytes(record.text_storage_key)
            except Exception:
                missing += 1
                self.stdout.write(self.style.ERROR(f"MISSING {record.id} {record.storage_key}"))
                continue

            if options["verify_hash"]:
                digest = hashlib.sha256(original).hexdigest()
                if digest != record.sha256:
                    mismatched += 1
                    self.stdout.write(
                        self.style.ERROR(
                            f"HASH_MISMATCH {record.id} expected={record.sha256} actual={digest}"
                        )
                    )

        summary = (
            f"checked={checked} missing={missing} "
            f"hash_mismatches={mismatched} expired={expired}"
        )
        if missing or mismatched:
            self.stdout.write(self.style.ERROR(summary))
            if options["fail_on_missing"]:
                raise CommandError(summary)
            return
        self.stdout.write(self.style.SUCCESS(summary))
