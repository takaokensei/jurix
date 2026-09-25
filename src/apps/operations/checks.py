"""Deployment-time configuration checks for Jurix.

The checks intentionally focus on invariants that can be validated without
knowing deployment-specific infrastructure details. They complement Django's
built-in ``check --deploy`` checks and are surfaced by the production gate.
"""
from __future__ import annotations

from django.conf import settings
from django.core.checks import Error, Tags, Warning, register

_DEV_PASSWORD = "jurix_pass_dev"


@register(Tags.security, deploy=True)
def check_production_contract(app_configs=None, **kwargs):
    """Validate settings that must not silently fall back in production."""
    issues = []
    debug = bool(getattr(settings, "DEBUG", False))

    if debug:
        issues.append(
            Error(
                "DEBUG=True is not valid for a production deployment.",
                id="jurix.E001",
            )
        )

    if not getattr(settings, "SECRET_KEY", "") or len(settings.SECRET_KEY) < 50:
        issues.append(
            Error(
                "DJANGO_SECRET_KEY must be a non-trivial production secret.",
                id="jurix.E002",
            )
        )

    allowed_hosts = list(getattr(settings, "ALLOWED_HOSTS", []))
    if not allowed_hosts or "*" in allowed_hosts:
        issues.append(
            Error(
                "ALLOWED_HOSTS must be explicit in production.",
                id="jurix.E003",
            )
        )

    database = getattr(settings, "DATABASES", {}).get("default", {})
    if database.get("PASSWORD") == _DEV_PASSWORD:
        issues.append(
            Error(
                "The development PostgreSQL password is still active.",
                id="jurix.E004",
            )
        )

    if getattr(settings, "USE_LOCMEM_CACHE", False):
        issues.append(
            Error(
                "LocMemCache must not be used in production; configure Redis.",
                id="jurix.E005",
            )
        )

    if getattr(settings, "LLM_RATE_LIMIT_REQUESTS", 20) == 0:
        issues.append(
            Warning(
                "LLM_RATE_LIMIT_REQUESTS=0 disables request throttling.",
                id="jurix.W001",
            )
        )

    max_pages = int(getattr(settings, "SAPL_OCR_MAX_PAGES", 0))
    if not 1 <= max_pages <= 500:
        issues.append(
            Error(
                "SAPL_OCR_MAX_PAGES must be between 1 and 500.",
                id="jurix.E006",
            )
        )

    storage_backend = str(getattr(settings, "STORAGE_BACKEND", "")).lower()
    if storage_backend not in {"local", "s3"}:
        issues.append(
            Error(
                "STORAGE_BACKEND must be either 'local' or 's3'.",
                id="jurix.E007",
            )
        )
    elif storage_backend == "s3":
        missing = [
            name
            for name in ("S3_ENDPOINT", "S3_BUCKET", "S3_ACCESS_KEY", "S3_SECRET_KEY")
            if not getattr(settings, name, "")
        ]
        if missing:
            issues.append(
                Error(
                    "S3 storage is selected but required settings are missing: "
                    + ", ".join(missing),
                    id="jurix.E008",
                )
            )
    elif debug is False:
        attachment_root = getattr(settings, "JURIX_ATTACHMENT_ROOT", "") or ""
        if not attachment_root:
            issues.append(
                Error(
                    "JURIX_ATTACHMENT_ROOT must be explicit when local storage is used.",
                    id="jurix.E009",
                )
            )

    if getattr(settings, "SECURE_SSL_REDIRECT", False):
        csrf_origins = getattr(settings, "CSRF_TRUSTED_ORIGINS", [])
        if not csrf_origins:
            issues.append(
                Warning(
                    "SECURE_SSL_REDIRECT is enabled without CSRF_TRUSTED_ORIGINS.",
                    id="jurix.W002",
                )
            )

    if getattr(settings, "SECURE_HSTS_SECONDS", 0) == 0:
        issues.append(
            Warning(
                "SECURE_HSTS_SECONDS is zero; enable HSTS after validating HTTPS.",
                id="jurix.W003",
            )
        )

    return issues
