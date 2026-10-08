"""Safely stage a bounded batch of authentic normative PDFs into isolated QA."""

from __future__ import annotations

import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.archive_import import ArchiveImportError
from src.apps.ingestion.corpus_staging import stage_normative_corpus


class Command(BaseCommand):
    help = "Stage one bounded batch of PDF documents in the isolated QA corpus."

    def add_arguments(self, parser):
        parser.add_argument("--archive", required=True, type=Path)
        parser.add_argument("--manifest", required=True, type=Path)
        parser.add_argument("--batch-size", type=int, default=10)
        parser.add_argument("--byte-budget", type=int, default=256 * 1024 * 1024)
        parser.add_argument("--time-budget-seconds", type=int, default=300)
        parser.add_argument("--resume")
        parser.add_argument("--dry-run", action="store_true", help="Only report the next safe batch; default behavior.")
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        if os.environ.get("JURIX_QA_ONLY") != "1":
            raise CommandError("JURIX_QA_ONLY=1 é obrigatório")
        if options["apply"] and options["dry_run"]:
            raise CommandError("--apply e --dry-run são opções incompatíveis")
        try:
            result = stage_normative_corpus(
                archive_path=options["archive"],
                manifest_path=options["manifest"],
                apply=options["apply"],
                batch_size=options["batch_size"],
                byte_budget=options["byte_budget"],
                time_budget_seconds=options["time_budget_seconds"],
                resume=options["resume"],
            )
        except (ArchiveImportError, OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
