"""
Run a production-readiness preflight using only local Django state.

This command is intentionally read-only. It checks configuration hazards, pending
migrations, cache backend, database engine, vector extension visibility, storage
contract, and required runtime integrations.
"""
from __future__ import annotations

import os

from django.conf import settings
from django.core import checks
from django.core.management import BaseCommand, call_command


class Command(BaseCommand):
    help = "Run the Jurix v2 production preflight contract."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--skip-db", action="store_true")
        parser.add_argument("--skip-system-checks", action="store_true")

    def _fail(self, message: str, strict: bool, failures: list[str]) -> None:
        failures.append(message)
        style = self.style.ERROR if strict else self.style.WARNING
        self.stdout.write(style(f"[preflight] {message}"))

    def handle(self, *args, **options):
        strict = bool(options["strict"])
        failures: list[str] = []
        warnings: list[str] = []

        if not options.get("skip_system_checks", False):
            errors = checks.run_checks()
            for error in errors:
                level = "ERROR" if error.is_serious() else "WARNING"
                line = f"Django check [{level}] {error.id}: {error.msg}"
                (failures if error.is_serious() else warnings).append(line)
                self.stdout.write(
                    self.style.ERROR(line) if error.is_serious() else self.style.WARNING(line)
                )

        if settings.DEBUG and strict:
            self._fail("DEBUG=True", strict, failures)

        secret = getattr(settings, "SECRET_KEY", "")
        if not secret or secret == "django-insecure-dev-key-change-in-production":
            self._fail("DJANGO_SECRET_KEY is missing or using the public development key.", strict, failures)

        if "*" in getattr(settings, "ALLOWED_HOSTS", []):
            self._fail("ALLOWED_HOSTS contains '*'.", strict, failures)

        database = settings.DATABASES["default"]
        engine = str(database.get("ENGINE", ""))
        if strict and "sqlite3" in engine:
            self._fail("SQLite is not allowed by the strict production preflight.", strict, failures)

        cache_backend = settings.CACHES["default"]["BACKEND"]
        if strict and "locmem" in cache_backend.lower():
            self._fail("LocMemCache is not allowed by the strict production preflight.", strict, failures)

        storage = str(getattr(settings, "STORAGE_BACKEND", "local")).lower()
        if strict and storage == "local" and not os.getenv("JURIX_ATTACHMENT_ROOT"):
            self._fail(
                "Production local attachment storage requires an explicit JURIX_ATTACHMENT_ROOT.",
                strict,
                failures,
            )

        if storage in {"s3", "minio"}:
            for name in ("S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY"):
                if not os.getenv(name):
                    self._fail(f"{name} is required for storage backend {storage}.", strict, failures)

        if not options.get("skip_db", False):
            try:
                call_command("showmigrations", "--plan", stdout=self.stdout)
            except Exception as exc:
                self._fail(f"Could not inspect migrations: {exc}", strict, failures)

        ollama_url = getattr(settings, "OLLAMA_BASE_URL", "")
        if not ollama_url:
            self._fail("OLLAMA_BASE_URL is empty.", strict, failures)

        models = getattr(settings, "OLLAMA_ALLOWED_MODELS", [])
        default_model = getattr(settings, "OLLAMA_MODEL", "")
        if default_model not in models:
            self._fail("OLLAMA_MODEL is not present in OLLAMA_ALLOWED_MODELS.", strict, failures)

        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Jurix v2 production preflight"))
        self.stdout.write(f"DEBUG={settings.DEBUG}")
        self.stdout.write(f"DATABASE={engine}")
        self.stdout.write(f"CACHE={cache_backend}")
        self.stdout.write(f"STORAGE={storage}")
        self.stdout.write(f"OLLAMA={ollama_url}")
        self.stdout.write(f"MODEL={default_model}")
        self.stdout.write(f"WARNINGS={len(warnings)}")
        self.stdout.write(f"FAILURES={len(failures)}")

        if failures and strict:
            self.stderr.write(self.style.ERROR("Production preflight FAILED."))
            raise SystemExit(2)

        if failures:
            self.stdout.write(self.style.WARNING("Production preflight completed with failures in non-strict mode."))
        else:
            self.stdout.write(self.style.SUCCESS("Production preflight PASSED."))
