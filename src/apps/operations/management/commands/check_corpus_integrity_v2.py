"""
Corpus integrity audit for Norma, Dispositivo and EventoAlteracao relations.
"""

from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db.models import Count

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma


class Command(BaseCommand):
    help = "Audit legal corpus integrity without mutating rows."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--limit", type=int, default=100)

    def handle(self, *args, **options):
        strict = bool(options["strict"])
        failures: list[str] = []

        duplicate_normas = list(
            Norma.objects.values("tipo", "numero", "ano")
            .annotate(count=Count("id"))
            .filter(count__gt=1)
            .order_by("-count")[: options["limit"]]
        )
        if duplicate_normas:
            failures.append(f"Duplicate legal identifiers: {len(duplicate_normas)} groups")

        orphan_devices = Dispositivo.objects.filter(norma__isnull=True).count()
        if orphan_devices:
            failures.append(f"Orphan devices: {orphan_devices}")

        parent_rows = list(Dispositivo.objects.values_list("id", "norma_id", "dispositivo_pai_id"))
        parent_map = {row_id: (norma_id, parent_id) for row_id, norma_id, parent_id in parent_rows}
        external_parents = [
            child_id
            for child_id, (norma_id, parent_id) in parent_map.items()
            if parent_id and (parent_id not in parent_map or parent_map[parent_id][0] != norma_id)
        ]
        if external_parents:
            failures.append(
                f"Parent links cross normas or point to missing rows: "
                f"{external_parents[: options['limit']]}"
            )

        cycle_nodes: set[int] = set()
        complete: set[int] = set()
        for start in parent_map:
            path: list[int] = []
            positions: dict[int, int] = {}
            current = start
            while current in parent_map and current not in complete:
                if current in positions:
                    cycle_nodes.update(path[positions[current] :])
                    break
                positions[current] = len(path)
                path.append(current)
                current = parent_map[current][1]
                if current is None:
                    break
            complete.update(path)
        if cycle_nodes:
            failures.append(f"Device parent cycles: {sorted(cycle_nodes)[: options['limit']]}")

        bad_order_groups = list(
            Dispositivo.objects.values("norma")
            .annotate(count=Count("id"), distinct_orders=Count("ordem", distinct=True))
            .filter(count__gt=0)
        )
        order_collisions = sum(
            1 for row in bad_order_groups if row["count"] != row["distinct_orders"]
        )
        if order_collisions:
            failures.append(f"Potential order collisions in {order_collisions} norma groups")

        orphan_event_sources = EventoAlteracao.objects.filter(
            dispositivo_fonte__isnull=True
        ).count()
        if orphan_event_sources:
            failures.append(f"Orphan alteration sources: {orphan_event_sources}")

        unlinked_high_confidence = EventoAlteracao.objects.filter(
            extraction_confidence__gte=0.9,
            validado=False,
            norma_alvo__isnull=True,
            dispositivo_alvo__isnull=True,
        ).count()
        if unlinked_high_confidence:
            self.stdout.write(
                self.style.WARNING(
                    f"Unlinked high-confidence alteration events: {unlinked_high_confidence}"
                )
            )

        self.stdout.write(f"Normas={Norma.objects.count()}")
        self.stdout.write(f"Dispositivos={Dispositivo.objects.count()}")
        self.stdout.write(f"Eventos={EventoAlteracao.objects.count()}")
        self.stdout.write(f"Failures={len(failures)}")

        if failures:
            for item in failures:
                self.stderr.write(f" - {item}")
            if strict:
                raise SystemExit(2)
            self.stdout.write(self.style.WARNING("Corpus integrity completed with findings."))
            return

        self.stdout.write(self.style.SUCCESS("Corpus integrity PASSED"))
