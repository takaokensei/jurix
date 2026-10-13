"""Bounded QA sync for official Natal DOM edition PDFs."""

from __future__ import annotations

import json
from datetime import date, timedelta

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from src.apps.ingestion.dom_sync import (
    DomNatalCandidateError,
    inspect_dom_natal_editions,
    sync_dom_natal_editions,
)


class Command(BaseCommand):
    help = "Inspeciona o catálogo do DOM; baixar e guardar candidato exige --apply explícito."

    def add_arguments(self, parser):
        parser.add_argument("--lookback-months", type=int, default=1)
        parser.add_argument("--max-new-total", type=int, default=1)
        parser.add_argument(
            "--as-of",
            type=date.fromisoformat,
            help="Retoma um mês histórico explícito, no máximo 366 dias atrás.",
        )
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        lookback_months = options["lookback_months"]
        max_new_total = options["max_new_total"]
        if not 1 <= lookback_months <= 3:
            raise CommandError("lookback-months deve estar entre 1 e 3 no runner QA.")
        if max_new_total != 1:
            raise CommandError("max-new-total está limitado a uma edição por execução QA.")
        as_of = options["as_of"]
        if as_of is not None:
            today = timezone.localdate()
            if as_of > today or as_of < today - timedelta(days=366):
                raise CommandError("as-of deve estar entre hoje e os últimos 366 dias.")
            if lookback_months != 1:
                raise CommandError("a retomada por data exige exatamente um mês de escopo.")

        try:
            if options["apply"]:
                report = sync_dom_natal_editions(
                    as_of=as_of,
                    lookback_months=lookback_months,
                    max_new_total=max_new_total,
                )
                report["read_only"] = False
                report["persisted"] = True
            else:
                report = inspect_dom_natal_editions(
                    as_of=as_of,
                    lookback_months=lookback_months,
                )
                report["persisted"] = False
                report["apply_required_for_download"] = True
                report["max_new_total"] = max_new_total
        except (DomNatalCandidateError, ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc

        self.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True))
