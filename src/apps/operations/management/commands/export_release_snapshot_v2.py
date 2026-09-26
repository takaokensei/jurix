"""
Export a metadata-only release snapshot.

The command intentionally excludes legal text and chat content. It captures
counts, model identifiers and status distributions useful for deployment
records.
"""
from __future__ import annotations

import json
from datetime import UTC, datetime

from django.conf import settings
from django.core.management.base import BaseCommand

from src.apps.legislation.models import Dispositivo, Norma


class Command(BaseCommand):
    help = "Export a metadata-only Jurix release snapshot."

    def add_arguments(self, parser):
        parser.add_argument("--output", default="release-snapshot-v2.json")

    def handle(self, *args, **options):
        statuses = {}
        for row in Norma.objects.values("status").order_by("status").distinct():
            value = row["status"] or ""
            statuses[value] = Norma.objects.filter(status=value).count()

        snapshot = {
            "schema_version": 2,
            "generated_at": datetime.now(UTC).isoformat(),
            "settings": {
                "embedding_model": getattr(settings, "OLLAMA_EMBEDDING_MODEL", ""),
                "generation_model": getattr(settings, "OLLAMA_MODEL", ""),
                "storage_backend": getattr(settings, "STORAGE_BACKEND", ""),
            },
            "counts": {
                "normas": Norma.objects.count(),
                "dispositivos": Dispositivo.objects.count(),
            },
            "norma_status_counts": statuses,
        }
        with open(options["output"], "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, indent=2)
        self.stdout.write(self.style.SUCCESS(f"Snapshot written: {options['output']}"))
