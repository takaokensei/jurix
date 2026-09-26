from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.models import Norma
from src.processing.temporal_scope import build_norma_timeline


class Command(BaseCommand):
    help = "Export an auditable chronological timeline for a norma."

    def add_arguments(self, parser):
        parser.add_argument("norma_id", type=int)
        parser.add_argument("--output")

    def handle(self, *args, **options):
        try:
            norma = Norma.objects.get(pk=options["norma_id"])
        except Norma.DoesNotExist as exc:
            raise CommandError("Norma não encontrada.") from exc
        payload = {
            "norma": {"id": norma.id, "ref": str(norma)},
            "timeline": build_norma_timeline(norma),
        }
        encoded = json.dumps(payload, ensure_ascii=False, indent=2)
        if options.get("output"):
            Path(options["output"]).write_text(encoded + "\n", encoding="utf-8")
        self.stdout.write(encoded)
