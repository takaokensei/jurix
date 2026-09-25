"""Inspect and optionally create the pgvector index used by semantic search."""

from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError
from django.db import connection

INDEX_NAME = "jurix_dispositivo_embedding_hnsw_cosine"
TABLE_NAME = "legislation_dispositivo"
COLUMN_NAME = "embedding"


class Command(BaseCommand):
    help = "Verifica/cria o índice HNSW de cosine distance do campo embedding."

    def add_arguments(self, parser):
        parser.add_argument("--create", action="store_true")
        parser.add_argument("--m", type=int, default=16)
        parser.add_argument("--ef-construction", type=int, default=64)
        parser.add_argument("--strict", action="store_true")

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write("vector index: skipped (database não é PostgreSQL)")
            return
        m = options["m"]
        ef = options["ef_construction"]
        if not 4 <= m <= 64:
            raise CommandError("--m deve estar entre 4 e 64")
        if not 8 <= ef <= 1024:
            raise CommandError("--ef-construction deve estar entre 8 e 1024")

        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT indexname
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = %s
                """,
                [TABLE_NAME],
            )
            names = {row[0] for row in cursor.fetchall()}
            exists = INDEX_NAME in names
            if exists or not options["create"]:
                status = "present" if exists else "missing"
                self.stdout.write(f"vector index: {status} ({INDEX_NAME})")
                if not exists and options["strict"]:
                    raise CommandError(f"Required vector index is missing: {INDEX_NAME}")
                return

            cursor.execute(
                f"CREATE INDEX CONCURRENTLY IF NOT EXISTS {INDEX_NAME} "
                f"ON {TABLE_NAME} USING hnsw ({COLUMN_NAME} vector_cosine_ops) "
                f"WITH (m = {m}, ef_construction = {ef})"
            )
        self.stdout.write(f"vector index: created ({INDEX_NAME})")
