from __future__ import annotations

from collections import Counter

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, Q

from src.apps.legislation.models import Norma


class Command(BaseCommand):
    help = "Audita a superfície de pesquisa das normas consolidadas."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict", action="store_true", help="Falha se houver anomalias bloqueantes."
        )
        parser.add_argument(
            "--limit", type=int, default=20, help="Quantidade máxima de exemplos por categoria."
        )

    def handle(self, *args, **options):
        strict = bool(options["strict"])
        limit = max(1, min(int(options["limit"]), 100))
        qs = Norma.objects.filter(status=Norma.Status.CONSOLIDATED)
        total = qs.count()
        missing_ementa = qs.filter(Q(ementa__isnull=True) | Q(ementa="")).count()
        missing_identifier = qs.filter(Q(tipo="") | Q(numero="") | Q(ano__isnull=True)).count()
        missing_sapl = qs.filter(sapl_id__isnull=True).count()
        duplicated_identifiers = (
            qs.values("tipo", "numero", "ano").annotate(total=Count("id")).filter(total__gt=1)
        )
        duplicate_count = duplicated_identifiers.count()
        types = Counter(qs.values_list("tipo", flat=True))

        self.stdout.write(self.style.MIGRATE_HEADING("Jurix — auditoria da biblioteca de normas"))
        self.stdout.write(f"Normas consolidadas: {total}")
        self.stdout.write(f"Sem ementa: {missing_ementa}")
        self.stdout.write(f"Sem identificador: {missing_identifier}")
        self.stdout.write(f"Sem SAPL ID: {missing_sapl}")
        self.stdout.write(f"Identificadores duplicados: {duplicate_count}")
        self.stdout.write("Tipos:")
        for name, count in types.most_common():
            self.stdout.write(f"  - {name}: {count}")

        if missing_ementa:
            self.stdout.write(
                self.style.WARNING("Ementas ausentes reduzem a qualidade das sugestões dinâmicas.")
            )
        if missing_sapl:
            self.stdout.write(
                self.style.WARNING("Normas sem SAPL ID não podem originar sugestões do corpus.")
            )
        if duplicate_count:
            examples = list(duplicated_identifiers[:limit])
            self.stdout.write(self.style.ERROR(f"Encontradas chaves duplicadas: {examples}"))
        if strict and (missing_identifier or duplicate_count):
            raise CommandError("A auditoria de normas falhou no modo --strict.")
