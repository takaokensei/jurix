from __future__ import annotations

from django.core.management.base import BaseCommand

from src.apps.ingestion.bounded_pipeline import bounded_sapl_ingest_task


class Command(BaseCommand):
    help = "Ingere páginas do SAPL em sequência, evitando flood da fila Celery."

    def add_arguments(self, parser):
        parser.add_argument("--max-normas", type=int, default=500)
        parser.add_argument("--batch-size", type=int, default=25)
        parser.add_argument("--offset", type=int, default=0)
        parser.add_argument("--tipo", default=None)
        parser.add_argument("--ano-inicio", type=int, default=None)
        parser.add_argument("--ano-fim", type=int, default=None)

    def handle(self, *args, **options):
        filters = {
            key: value
            for key, value in {
                "tipo": options.get("tipo"),
                "ano_inicio": options.get("ano_inicio"),
                "ano_fim": options.get("ano_fim"),
            }.items()
            if value is not None
        }
        result = bounded_sapl_ingest_task.apply(
            kwargs={
                "max_normas": options["max_normas"],
                "batch_size": options["batch_size"],
                "offset": options["offset"],
                **filters,
            }
        )
        if not result.successful():
            self.stderr.write(self.style.ERROR(str(result.result)))
            return
        self.stdout.write(self.style.SUCCESS(str(result.result)))
