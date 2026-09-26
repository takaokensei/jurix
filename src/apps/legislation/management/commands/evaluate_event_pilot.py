from __future__ import annotations

import json
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.processing.event_evaluation import evaluate, load_cases


class Command(BaseCommand):
    help = "Evaluate legal alteration events against a reviewed JSONL pilot."

    def add_arguments(self, parser):
        parser.add_argument("gold", help="Path to reviewed JSONL cases")
        parser.add_argument("--output", help="Optional JSON report output path")

    def handle(self, *args, **options):
        path = Path(options["gold"])
        if not path.exists():
            raise CommandError(f"Arquivo não encontrado: {path}")
        try:
            report = evaluate(load_cases(path))
        except (ValueError, json.JSONDecodeError) as exc:
            raise CommandError(str(exc)) from exc
        encoded = json.dumps(report, ensure_ascii=False, indent=2)
        if options.get("output"):
            Path(options["output"]).write_text(encoded + "\n", encoding="utf-8")
        self.stdout.write(encoded)
