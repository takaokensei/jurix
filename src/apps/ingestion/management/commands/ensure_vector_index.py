"""Create the pgvector HNSW index used by the semantic retrieval path."""
from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Cria o índice HNSW pgvector para embeddings de Dispositivo."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            self.stdout.write(self.style.WARNING("Índice vetorial requer PostgreSQL + pgvector; nenhuma alteração foi feita."))
            return

        with connection.cursor() as cursor:
            cursor.execute("CREATE EXTENSION IF NOT EXISTS vector")
            cursor.execute(
                """
                CREATE INDEX IF NOT EXISTS legislation_dispositivo_embedding_hnsw_idx
                ON legislation_dispositivo
                USING hnsw (embedding vector_cosine_ops)
                WITH (m = 16, ef_construction = 64)
                """
            )
        self.stdout.write(self.style.SUCCESS("Índice HNSW criado/verificado."))
