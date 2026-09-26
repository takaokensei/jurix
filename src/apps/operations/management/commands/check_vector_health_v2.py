"""
Inspect pgvector availability and legal embedding health without mutating data.
"""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection

from src.apps.legislation.models import Dispositivo, Norma


class Command(BaseCommand):
    help = "Inspect PostgreSQL/pgvector readiness and embedding coverage."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--sample", type=int, default=20)

    def handle(self, *args, **options):
        strict = bool(options["strict"])
        failures: list[str] = []

        engine = connection.settings_dict.get("ENGINE", "")
        if "postgresql" not in engine:
            message = "Database engine is not PostgreSQL."
            if strict:
                failures.append(message)
                self.stdout.write(self.style.ERROR(message))
            else:
                self.stdout.write(self.style.WARNING(message))
        else:
            with connection.cursor() as cursor:
                cursor.execute("SELECT extname FROM pg_extension WHERE extname = 'vector'")
                vector_enabled = bool(cursor.fetchone())
                if not vector_enabled:
                    failures.append("PostgreSQL extension 'vector' is not installed.")
                    self.stdout.write(self.style.ERROR(failures[-1]))

                cursor.execute(
                    """
                    SELECT indexname
                    FROM pg_indexes
                    WHERE tablename = %s
                      AND indexdef ILIKE %s
                    ORDER BY indexname
                    """,
                    [Dispositivo._meta.db_table, "%embedding%"],
                )
                vector_indexes = [row[0] for row in cursor.fetchall()]
                self.stdout.write(f"Vector-related indexes: {len(vector_indexes)}")
                for index_name in vector_indexes:
                    self.stdout.write(f"  - {index_name}")

        total = Dispositivo.objects.count()
        with_embedding = Dispositivo.objects.exclude(embedding=None).count()
        ready = Norma.objects.filter(status=Norma.Status.CONSOLIDATED).count()
        ready_without_embeddings = (
            Dispositivo.objects.filter(norma__status=Norma.Status.CONSOLIDATED, embedding=None).count()
        )

        coverage = with_embedding / total if total else 0.0
        self.stdout.write(f"Dispositivos={total}")
        self.stdout.write(f"Embeddings={with_embedding}")
        self.stdout.write(f"Embedding coverage={coverage:.4f}")
        self.stdout.write(f"Consolidated normas={ready}")
        self.stdout.write(f"Ready devices without embedding={ready_without_embeddings}")

        if strict and ready_without_embeddings:
            failures.append(
                f"{ready_without_embeddings} dispositivos consolidados não possuem embedding."
            )

        if strict and total and coverage < 0.95:
            failures.append(f"Embedding coverage {coverage:.4f} is below 0.95.")

        if failures:
            self.stderr.write(self.style.ERROR("Vector health FAILED"))
            for item in failures:
                self.stderr.write(f" - {item}")
            raise SystemExit(2)

        self.stdout.write(self.style.SUCCESS("Vector health PASSED"))
