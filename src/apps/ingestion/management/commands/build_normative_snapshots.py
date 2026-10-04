"""Dry-run-first, bounded builder for immutable historical snapshots."""

from __future__ import annotations

import json
import os

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from src.apps.legislation.models import Norma
from src.processing.normative_projection import persist_projection, project_norma_as_of


class Command(BaseCommand):
    help = "Planeja snapshots temporais; --apply persiste somente no banco QA isolado."

    def add_arguments(self, parser):
        parser.add_argument("--as-of", required=True, help="Data ISO AAAA-MM-DD")
        parser.add_argument("--norma-id", action="append", type=int, default=[])
        parser.add_argument("--limit", type=int, default=40)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        from datetime import date

        from django.conf import settings

        if os.environ.get("JURIX_QA_ONLY") != "1" or not str(settings.SETTINGS_MODULE).endswith("settings_normative_qa"):
            raise CommandError("Snapshots desta tarefa exigem settings QA e JURIX_QA_ONLY=1.")
        try:
            as_of = date.fromisoformat(options["as_of"])
        except ValueError as exc:
            raise CommandError("--as-of deve usar AAAA-MM-DD.") from exc
        limit = options["limit"]
        if not 1 <= limit <= 40:
            raise CommandError("--limit deve estar entre 1 e 40.")
        ids = sorted(set(options["norma_id"]))
        query = Norma.objects.filter(documento_base__isnull=False).order_by("pk")
        if ids:
            query = query.filter(pk__in=ids)
            if query.count() != len(ids):
                raise CommandError("Um ou mais IDs não apontam para norma com documento-base.")
        normas = list(query[: limit + 1])
        if len(normas) > limit:
            raise CommandError("Escopo excede o limite; use --norma-id explícito ou reduza --limit.")
        results = []
        context = transaction.atomic() if options["apply"] else _NoTransaction()
        with context:
            for norma in normas:
                projection = project_norma_as_of(norma, as_of)
                record = {
                    "norma_id": norma.pk,
                    "as_of": as_of.isoformat(),
                    "status": projection.status,
                    "input_sha256": projection.input_sha256,
                    "content_sha256": projection.content_sha256,
                    "coverage": projection.coverage,
                    "persisted": False,
                }
                if options["apply"]:
                    snapshot = persist_projection(projection)
                    record.update(
                        persisted=True,
                        snapshot_id=snapshot.pk,
                        devices=snapshot.dispositivos.count(),
                    )
                results.append(record)
        self.stdout.write(json.dumps({"dry_run": not options["apply"], "results": results}, ensure_ascii=False, sort_keys=True))


class _NoTransaction:
    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False
