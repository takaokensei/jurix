"""Read-only inspection of the official DOM catalog against QA candidates."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.dom_sync import inspect_dom_natal_editions


class Command(BaseCommand):
    help = "Inspeciona o catálogo do DOM e candidatos QA sem baixar PDFs ou gravar dados."

    def add_arguments(self, parser):
        parser.add_argument("--lookback-months", type=int, default=3)

    def handle(self, *args, **options):
        try:
            report = inspect_dom_natal_editions(lookback_months=options["lookback_months"])
        except (ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(report, ensure_ascii=False, sort_keys=True))
        if report["catalog_status"] != "available":
            raise CommandError("Uma ou mais consultas ao catálogo DOM não foram concluídas.")
