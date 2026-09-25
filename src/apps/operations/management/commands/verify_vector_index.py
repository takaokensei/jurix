"""Verify a pgvector ANN index compatible with cosine retrieval."""
from __future__ import annotations

from django.core.management import BaseCommand, CommandError
from django.db import connection


class Command(BaseCommand):
    help = "Verifica índice HNSW/IVFFlat com vector_cosine_ops para dispositivos."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("O índice vetorial exige PostgreSQL/pgvector.")
        with connection.cursor() as cursor:
            cursor.execute(
                """SELECT indexname, indexdef
                   FROM pg_indexes
                   WHERE schemaname = current_schema()
                     AND tablename = 'legislation_dispositivo'
                     AND (indexdef ILIKE '%USING hnsw%' OR indexdef ILIKE '%USING ivfflat%')
                     AND indexdef ILIKE '%vector_cosine_ops%'
                   ORDER BY indexname"""
            )
            indexes = cursor.fetchall()
        if not indexes:
            raise CommandError(
                "Nenhum índice ANN pgvector com vector_cosine_ops foi encontrado "
                "em legislation_dispositivo."
            )
        self.stdout.write(self.style.SUCCESS(
            "Índice vetorial válido: " + ", ".join(row[0] for row in indexes)
        ))
