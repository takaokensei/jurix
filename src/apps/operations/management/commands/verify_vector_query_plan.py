"""Verify that pgvector retrieval has a usable ANN execution path."""

from __future__ import annotations

import re

from django.conf import settings
from django.core.management import BaseCommand, CommandError
from django.db import connection

_VECTOR_INDEX_SCAN = re.compile(
    r"\b(?:Index Scan|Index Only Scan|Bitmap Index Scan)\s+using\s+\S*(?:hnsw|ivfflat)\S*\b",
    re.I,
)


class Command(BaseCommand):
    help = "Executa EXPLAIN e valida o caminho de índice para pgvector."

    def handle(self, *args, **options):
        if connection.vendor != "postgresql":
            raise CommandError("O plano vetorial exige PostgreSQL.")
        vector = "[" + ",".join(["0"] * 768) + "]"
        query = (
            "EXPLAIN (FORMAT TEXT) SELECT id FROM legislation_dispositivo "
            "WHERE embedding IS NOT NULL "
            "ORDER BY embedding <=> %s::vector LIMIT 5"
        )
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT COUNT(*) FROM legislation_dispositivo WHERE embedding IS NOT NULL"
            )
            row_count = int(cursor.fetchone()[0] or 0)
            cursor.execute(query, [vector])
            plan = "\n".join(str(row[0]) for row in cursor.fetchall())

            if _VECTOR_INDEX_SCAN.search(plan):
                self.stdout.write(self.style.SUCCESS("Plano pgvector usa acesso indexado."))
                return

            threshold = int(getattr(settings, "VECTOR_INDEX_MIN_ROWS_FOR_STRICT_PLAN", 1000))
            if row_count < threshold:
                self.stdout.write(
                    self.style.WARNING(
                        f"Plano usa seq scan com apenas {row_count} embeddings; "
                        f"abaixo do limiar de {threshold}. Índice já foi verificado separadamente."
                    )
                )
                return

            # The command runs in Django's autocommit mode. SET LOCAL would be
            # discarded immediately when issued outside an explicit transaction
            # and would therefore fail to exercise the ANN index in the probe.
            cursor.execute("SET enable_seqscan = off")
            cursor.execute(query, [vector])
            forced_plan = "\n".join(str(row[0]) for row in cursor.fetchall())

        if not _VECTOR_INDEX_SCAN.search(forced_plan):
            raise CommandError(
                "Mesmo com seqscan desativado, pgvector não encontrou caminho indexado."
            )
        self.stdout.write(
            self.style.WARNING(
                "O planner escolheu seq scan para o vetor sintético da probe, "
                "mas o caminho HNSW/IVFFlat foi confirmado com seqscan desativado. "
                "Valide EXPLAIN ANALYZE com vetores reais antes da promoção."
            )
        )
