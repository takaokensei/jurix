"""Repair exactly one missing DOM PDF blob in isolated QA after hash verification."""

from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.dom_sync import DomNatalCandidateError, repair_dom_edition_blob_qa


class Command(BaseCommand):
    help = "Verifica ou restaura um único PDF DOM QA, preservando o registro imutável."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument("--edition-number", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = repair_dom_edition_blob_qa(
                year=options["year"],
                month=options["month"],
                edition_number=options["edition_number"],
                apply=options["apply"],
            )
        except (DomNatalCandidateError, ValueError, RuntimeError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=True, sort_keys=True))
