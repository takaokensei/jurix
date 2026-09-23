from __future__ import annotations

from django.core.management.base import BaseCommand

from src.processing.target_reconciliation import reconcile_unresolved_event_targets


class Command(BaseCommand):
    help = "Tenta resolver novamente eventos de alteração que ficaram sem norma-alvo."

    def add_arguments(self, parser):
        parser.add_argument('--limit', type=int, default=5000)

    def handle(self, *args, **options):
        stats = reconcile_unresolved_event_targets(options['limit'])
        self.stdout.write(self.style.SUCCESS(str(stats)))
