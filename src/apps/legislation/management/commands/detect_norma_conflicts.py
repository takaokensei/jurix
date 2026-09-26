from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.models import Norma
from src.processing.conflict_detection import detect_for_norma


class Command(BaseCommand):
    help = "Detect advisory conflict/integrity signals for a norma."

    def add_arguments(self, parser):
        parser.add_argument("norma_id", type=int)
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        try:
            norma = Norma.objects.get(pk=options["norma_id"])
        except Norma.DoesNotExist as exc:
            raise CommandError("Norma não encontrada.") from exc
        signals = detect_for_norma(norma)
        if options["json"]:
            self.stdout.write(json.dumps(signals, ensure_ascii=False, indent=2))
            return
        if not signals:
            self.stdout.write(self.style.SUCCESS(f"Nenhum sinal encontrado para {norma}."))
            return
        for signal in signals:
            self.stdout.write(
                f"[{signal['severity']}] {signal['code']}: {signal['description']} "
                f"eventos={signal['event_ids']}"
            )
