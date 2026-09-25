"""Validate the complete production configuration contract."""
from __future__ import annotations

from django.conf import settings
from django.core import checks
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Validate Jurix production settings and deployment invariants."

    def add_arguments(self, parser):
        parser.add_argument(
            "--strict",
            action="store_true",
            help="Treat warnings as failures as well as errors.",
        )
        parser.add_argument(
            "--show-settings",
            action="store_true",
            help="Print non-secret production settings that were evaluated.",
        )

    def handle(self, *args, **options):
        issues = checks.run_checks(include_deployment_checks=True)
        errors = [issue for issue in issues if issue.is_serious()]
        warnings = [issue for issue in issues if not issue.is_serious()]

        for issue in issues:
            style = self.style.ERROR if issue.is_serious() else self.style.WARNING
            self.stdout.write(style(f"{issue.id}: {issue.msg}"))

        if options["show_settings"]:
            safe = {
                "DEBUG": settings.DEBUG,
                "ALLOWED_HOSTS": settings.ALLOWED_HOSTS,
                "STORAGE_BACKEND": getattr(settings, "STORAGE_BACKEND", ""),
                "OLLAMA_MODEL": getattr(settings, "OLLAMA_MODEL", ""),
                "OLLAMA_EMBEDDING_MODEL": getattr(
                    settings, "OLLAMA_EMBEDDING_MODEL", ""
                ),
                "SAPL_OCR_MAX_PAGES": getattr(settings, "SAPL_OCR_MAX_PAGES", 0),
                "LLM_MAX_K": getattr(settings, "LLM_MAX_K", 0),
                "LLM_MAX_QUESTION_LENGTH": getattr(
                    settings, "LLM_MAX_QUESTION_LENGTH", 0
                ),
                "LLM_RATE_LIMIT_REQUESTS": getattr(
                    settings, "LLM_RATE_LIMIT_REQUESTS", 0
                ),
            }
            for key, value in safe.items():
                self.stdout.write(f"{key}={value}")

        if errors or (options["strict"] and warnings):
            raise CommandError(
                f"Production configuration invalid: {len(errors)} error(s), "
                f"{len(warnings)} warning(s)."
            )

        self.stdout.write(
            self.style.SUCCESS(
                f"Production configuration valid: {len(errors)} error(s), "
                f"{len(warnings)} warning(s)."
            )
        )
