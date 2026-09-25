"""Safely prune expired attachment objects.

This command is intentionally separate from ``audit_attachment_storage``. The
audit command remains read-only; pruning requires ``--execute`` and prints a
machine-readable summary so scheduled jobs can be monitored safely.
"""

from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.attachment_storage import get_attachment_storage
from src.apps.operations.models import AttachmentRecord


class Command(BaseCommand):
    help = "Lista ou remove objetos de anexos expirados com confirmação explícita."

    def add_arguments(self, parser):
        parser.add_argument("--execute", action="store_true")
        parser.add_argument("--older-than-days", type=int, default=0)
        parser.add_argument("--limit", type=int, default=0)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        older_than_days = options["older_than_days"]
        if older_than_days < 0:
            raise CommandError("--older-than-days não pode ser negativo.")
        limit = options["limit"]
        if limit < 0:
            raise CommandError("--limit não pode ser negativo.")

        cutoff = timezone.now()
        if older_than_days:
            cutoff -= timedelta(days=older_than_days)

        queryset = AttachmentRecord.objects.filter(expires_at__lte=cutoff).order_by("expires_at")
        if limit:
            queryset = queryset[:limit]

        storage = get_attachment_storage()
        planned = []
        for record in queryset:
            planned.append(
                {
                    "id": record.id,
                    "storage_key": record.storage_key,
                    "text_storage_key": record.text_storage_key,
                    "expires_at": record.expires_at.isoformat(),
                }
            )

        summary = {
            "matched": len(planned),
            "deleted": 0,
            "failed": 0,
            "dry_run": not options["execute"],
        }
        if options["execute"]:
            with transaction.atomic():
                for item in planned:
                    try:
                        storage.delete(item["storage_key"])
                        storage.delete(item["text_storage_key"])
                        AttachmentRecord.objects.filter(pk=item["id"]).delete()
                        summary["deleted"] += 1
                    except Exception as exc:  # pragma: no cover - defensive operational path
                        summary["failed"] += 1
                        self.stderr.write(f"Falha ao excluir {item['id']}: {exc}")

        if options["json"]:
            self.stdout.write(
                json.dumps({"summary": summary, "records": planned}, ensure_ascii=False)
            )
        else:
            mode = "DRY-RUN" if summary["dry_run"] else "EXECUÇÃO"
            self.stdout.write(f"{mode}: {summary['matched']} registros expirados.")
            if options["execute"]:
                self.stdout.write(f"Excluídos: {summary['deleted']} | Falhas: {summary['failed']}")
            else:
                self.stdout.write("Use --execute para efetivar a exclusão.")
