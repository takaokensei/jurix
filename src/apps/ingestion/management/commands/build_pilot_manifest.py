import json
from collections import defaultdict
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.models import Norma


class Command(BaseCommand):
    help = "Cria o manifesto do piloto de 20 normas a partir do corpus municipal já ingerido."

    def add_arguments(self, parser):
        parser.add_argument("--corpus-limit", type=int, default=300)
        parser.add_argument("--pilot-size", type=int, default=20)
        parser.add_argument(
            "--output",
            default="benchmarks/corpus/municipal_natal/pilot.jsonl",
        )

    def handle(self, *args, **options):
        corpus_limit = options["corpus_limit"]
        pilot_size = options["pilot_size"]
        if corpus_limit < 1 or pilot_size < 1 or pilot_size > corpus_limit:
            raise CommandError("pilot-size deve ser >=1 e <= corpus-limit")

        qs = (
            Norma.objects.filter(sapl_id__isnull=False)
            .exclude(ementa="")
            .order_by("-ano", "tipo", "numero")[:corpus_limit]
        )
        buckets: dict[str, list[Norma]] = defaultdict(list)
        for norma in qs:
            buckets[norma.tipo].append(norma)

        selected: list[Norma] = []
        while buckets and len(selected) < pilot_size:
            empty = []
            for tipo in sorted(buckets):
                bucket = buckets[tipo]
                if not bucket:
                    empty.append(tipo)
                    continue
                selected.append(bucket.pop(0))
                if len(selected) >= pilot_size:
                    break
            for tipo in empty:
                buckets.pop(tipo, None)
            buckets = defaultdict(list, {k: v for k, v in buckets.items() if v})

        out = Path(options["output"])
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("w", encoding="utf-8") as handle:
            for norma in selected:
                record = {
                    "norma_id": norma.id,
                    "sapl_id": norma.sapl_id,
                    "identifier": f"{norma.tipo} {norma.numero}/{norma.ano}",
                    "ementa": norma.ementa,
                    "source_url": norma.sapl_url,
                    "ai_review_status": "pending",
                    "human_review_status": "pending",
                    "annotation_status": "pending",
                    "notes": "",
                }
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        self.stdout.write(
            self.style.SUCCESS(f"Manifesto piloto escrito em {out} ({len(selected)} normas).")
        )
