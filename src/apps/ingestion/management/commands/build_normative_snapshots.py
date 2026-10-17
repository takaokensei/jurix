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

        database = settings.DATABASES.get("default", {})
        host_qa_database = (
            database.get("ENGINE") == "django.db.backends.postgresql"
            and database.get("HOST") == "127.0.0.1"
            and str(database.get("PORT")) == "55432"
            and database.get("USER") == "jurix_audit"
            and database.get("NAME") in {"jurix_audit", "test_jurix_audit"}
        )
        container_qa_database = (
            os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings_normative_container_qa"
            and database.get("ENGINE") == "django.db.backends.postgresql"
            and database.get("HOST") == "db"
            and str(database.get("PORT")) == "5432"
            and database.get("USER") == "jurix_audit"
            and database.get("NAME") in {"jurix_audit", "test_jurix_audit"}
        )
        qa_database = host_qa_database or container_qa_database
        ephemeral_test_database = (
            database.get("ENGINE") == "django.db.backends.sqlite3"
            and str(database.get("NAME"))
            in {":memory:", "file:memorydb_default?mode=memory&cache=shared"}
        )
        if os.environ.get("JURIX_QA_ONLY") != "1":
            raise CommandError("Snapshots desta tarefa exigem JURIX_QA_ONLY=1.")
        if options["apply"] and not qa_database:
            target = ", ".join(
                f"{key}={database.get(key)}"
                for key in ("ENGINE", "HOST", "PORT", "USER", "NAME")
            )
            raise CommandError(
                "Persistência de snapshots exige PostgreSQL QA dedicado "
                f"(qa_flag={os.environ.get('JURIX_QA_ONLY')!r}; {target})."
            )
        if not options["apply"] and not (qa_database or ephemeral_test_database):
            raise CommandError(
                "Prévia de snapshots exige PostgreSQL QA ou SQLite efêmero de teste."
            )
        try:
            as_of = date.fromisoformat(options["as_of"])
        except ValueError as exc:
            raise CommandError("--as-of deve usar AAAA-MM-DD.") from exc
        limit = options["limit"]
        if not 1 <= limit <= 40:
            raise CommandError("--limit deve estar entre 1 e 40.")
        ids = sorted(set(options["norma_id"]))
        # Explicit identities must be reportable even when their source has not
        # passed review yet. project_norma_as_of() returns a fail-closed
        # NOT_RECONSTRUCTABLE result for those rows; the default batch remains
        # limited to norms with a document base so an unscoped run stays useful.
        query = Norma.objects.order_by("pk") if ids else Norma.objects.filter(
            documento_base__isnull=False
        ).order_by("pk")
        if ids:
            query = query.filter(pk__in=ids)
            if query.count() != len(ids):
                raise CommandError("Um ou mais IDs não apontam para uma norma existente.")
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
