"""Report source freshness from persisted sync checkpoints without mutation."""

from __future__ import annotations

import json
from datetime import timedelta

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.source_sync_health import get_source_sync_health
from src.apps.operations.worker_health import get_normative_worker_health


class Command(BaseCommand):
    help = "Report if each known sync scope is current, stale, degraded, or unavailable."

    def add_arguments(self, parser):
        parser.add_argument("--source", default="sapl")
        parser.add_argument("--max-age-hours", type=int, default=36)

    def handle(self, *args, **options):
        source = options["source"]
        max_age_hours = options["max_age_hours"]
        if not source or not source.strip():
            raise CommandError("--source must be a non-empty identifier")
        if not 1 <= max_age_hours <= 8760:
            raise CommandError("--max-age-hours must be between 1 and 8760")

        report = get_source_sync_health(
            source, max_age=timedelta(hours=max_age_hours)
        )
        report["checked_at"] = report["checked_at"].isoformat()
        if report["last_success_at"] is not None:
            report["last_success_at"] = report["last_success_at"].isoformat()
        worker = get_normative_worker_health()
        self.stdout.write(
            json.dumps(
                {"source_sync": report, "normative_queue": worker},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        if report["status"] != "current" or worker["status"] != "current":
            raise CommandError(
                "Source processing is not ready: "
                f"source={source}, status={report['status']}, queue={worker['status']}"
            )
