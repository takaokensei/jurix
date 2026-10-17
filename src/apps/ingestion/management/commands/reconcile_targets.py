from __future__ import annotations

import json

from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.models import Norma
from src.processing.target_reconciliation import reconcile_unresolved_event_targets


class Command(BaseCommand):
    help = "Tenta resolver novamente eventos de alteração que ficaram sem norma-alvo."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=5000)
        parser.add_argument(
            "--norma-id",
            action="append",
            type=int,
            default=[],
            help="Restringe a segunda passagem a uma ou mais normas recém-ingressadas.",
        )
        parser.add_argument(
            "--identity-key",
            action="append",
            default=[],
            help="Restringe a segunda passagem às identidades normativas recém-ingressadas.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Inspeciona os resultados candidatos sem alterar vínculos ou metadados.",
        )
        parser.add_argument(
            "--details",
            action="store_true",
            help="Inclui identidade e diagnóstico estrutural sanitizado (somente em dry-run).",
        )

    def handle(self, *args, **options):
        if options["details"] and not options["dry_run"]:
            raise CommandError("--details só pode ser usado junto com --dry-run.")
        norma_ids = set(options["norma_id"])
        if options["identity_key"]:
            norma_ids.update(
                Norma.objects.filter(identity_key__in=options["identity_key"]).values_list(
                    "pk", flat=True
                )
            )
        scope = norma_ids if options["norma_id"] or options["identity_key"] else None
        stats = reconcile_unresolved_event_targets(
            options["limit"],
            target_norma_ids=scope,
            dry_run=options["dry_run"],
            return_cursor=options["dry_run"],
            include_diagnostics=options["details"],
        )
        self.stdout.write(
            self.style.SUCCESS(json.dumps(stats, sort_keys=True))
        )
