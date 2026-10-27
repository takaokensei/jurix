"""Stage only SAPL LC 261/2025 as an unlinked, pending QA document candidate."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.management.commands.stage_lc208_unlinked_sapl_candidate_qa import (
    stage_lc261_unlinked_candidate,
)


class Command(BaseCommand):
    help = "Registra a fonte oficial LC 261/2025 como PDF QA não associado."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = stage_lc261_unlinked_candidate(apply=options["apply"])
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
