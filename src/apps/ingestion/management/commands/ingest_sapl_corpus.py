from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.tasks import ingest_sapl_corpus_task


class Command(BaseCommand):
    help = "Enfileira a ingestão boundada do corpus municipal do SAPL."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=300)
        parser.add_argument("--year-start", type=int, default=None)
        parser.add_argument("--year-end", type=int, default=None)
        parser.add_argument("--auto-download", action="store_true")
        parser.add_argument(
            "--sync", action="store_true", help="Executa no processo atual em vez de Celery."
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        if not 1 <= limit <= 5000:
            raise CommandError("--limit deve estar entre 1 e 5000")
        kwargs = {
            "max_normas": limit,
            "ano_inicio": options["year_start"],
            "ano_fim": options["year_end"],
            "auto_download": options["auto_download"],
        }
        result = (
            ingest_sapl_corpus_task.apply(kwargs=kwargs)
            if options["sync"]
            else ingest_sapl_corpus_task.delay(**kwargs)
        )
        if options["sync"]:
            self.stdout.write(self.style.SUCCESS(f"Corpus SAPL processado: {result.result}"))
        else:
            self.stdout.write(self.style.SUCCESS(f"Task enfileirada: {result.id}"))
