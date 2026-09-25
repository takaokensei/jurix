"""Single command for the operational pre-release validation contract."""

from __future__ import annotations

import json
import shutil
import subprocess

from django.conf import settings
from django.core.management import BaseCommand, call_command
from django.db import connection


class Command(BaseCommand):
    help = "Executa verificações de configuração, banco, storage e ferramentas de release."

    def add_arguments(self, parser):
        parser.add_argument("--strict", action="store_true")
        parser.add_argument("--json", action="store_true")

    def handle(self, *args, **options):
        results = {}
        try:
            call_command("check", deploy=True, fail_level="ERROR", stdout=subprocess.DEVNULL)
            results["django_deploy_checks"] = "passed"
        except (SystemExit, Exception) as exc:
            results["django_deploy_checks"] = f"failed:{exc}"

        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT 1")
            results["database"] = "passed"
        except (SystemExit, Exception) as exc:
            results["database"] = f"failed:{type(exc).__name__}"

        try:
            call_command("verify_vector_index", stdout=subprocess.DEVNULL)
            results["vector_index"] = "verified"
        except (SystemExit, Exception) as exc:
            results["vector_index"] = f"failed:{type(exc).__name__}"

        results["storage_backend"] = str(getattr(settings, "STORAGE_BACKEND", ""))
        results["python"] = shutil.which("python") or "missing"

        strict_failures = [
            key
            for key, value in results.items()
            if isinstance(value, str) and value.startswith("failed:")
        ]
        payload = {"ok": not strict_failures, "results": results, "failures": strict_failures}
        if options["json"]:
            self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            self.stdout.write("Production validation: " + ("PASS" if payload["ok"] else "FAIL"))
            for key, value in results.items():
                self.stdout.write(f"- {key}: {value}")
        if options["strict"] and strict_failures:
            raise SystemExit(1)
