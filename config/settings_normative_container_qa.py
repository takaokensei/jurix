"""Strict QA-only settings for the isolated audit Compose network."""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from tempfile import gettempdir
from urllib.parse import urlparse

from celery.schedules import crontab
from django.core.exceptions import ImproperlyConfigured

_EXPECTED_DATABASE = {
    "scheme": "postgresql",
    "hostname": "db",
    "port": 5432,
    "username": "jurix_audit",
    "database": "jurix_audit",
    "password": "audit-only-local-fixture",
}
_EXPECTED_SECRET = "audit-only-local-secret-not-for-production"


def _require_container_qa_environment() -> tuple[Path, str, str]:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise ImproperlyConfigured("Container QA settings require JURIX_QA_ONLY=1.")
    if os.environ.get("DJANGO_SKIP_DOTENV") != "1":
        raise ImproperlyConfigured("Container QA settings must not load a project .env file.")
    if os.environ.get("DJANGO_SECRET_KEY") != _EXPECTED_SECRET:
        raise ImproperlyConfigured("Container QA settings require the fixed QA-only secret.")

    database = urlparse(os.environ.get("DATABASE_URL", ""))
    actual_database = {
        "scheme": database.scheme,
        "hostname": database.hostname,
        "port": database.port,
        "username": database.username,
        "database": database.path.lstrip("/"),
        "password": database.password,
    }
    expected_connection = {
        key: value for key, value in _EXPECTED_DATABASE.items() if key != "database"
    }
    actual_connection = {
        key: value for key, value in actual_database.items() if key != "database"
    }
    database_name = actual_database["database"]
    allowed_name = database_name == _EXPECTED_DATABASE["database"] or bool(
        re.fullmatch(r"jurix_migtest_[0-9]+", database_name)
    )
    if actual_connection != expected_connection:
        mismatched_fields = sorted(
            key for key, value in expected_connection.items() if actual_connection.get(key) != value
        )
        raise ImproperlyConfigured(
            "Container QA settings only accept the dedicated audit database service "
            f"(mismatched connection fields: {', '.join(mismatched_fields)})."
        )
    if not allowed_name:
        raise ImproperlyConfigured(
            "Container QA settings only accept the audit database or a namespaced migration scratch database."
        )

    expected_urls = {
        "REDIS_URL": "redis://redis:6379/0",
        "CACHE_REDIS_URL": "redis://redis:6379/1",
    }
    for variable, expected_url in expected_urls.items():
        value = os.environ.get(variable, "")
        parsed = urlparse(value)
        if (
            value != expected_url
            or parsed.scheme != "redis"
            or parsed.hostname != "redis"
            or parsed.port != 6379
            or parsed.username
            or parsed.password
        ):
            raise ImproperlyConfigured(
                f"{variable} must use the dedicated audit Redis service."
            )

    raw_root = os.environ.get("JURIX_QA_ROOT", "")
    if not raw_root:
        raise ImproperlyConfigured("JURIX_QA_ROOT must point to an isolated QA directory.")
    root = Path(raw_root).resolve()
    temp_root = Path(gettempdir()).resolve()
    if root == temp_root or not root.is_relative_to(temp_root):
        raise ImproperlyConfigured("JURIX_QA_ROOT must be a child of the container temp directory.")
    root.mkdir(parents=True, exist_ok=True)
    return root, os.environ["DATABASE_URL"], os.environ["REDIS_URL"]


QA_ROOT, _DATABASE_URL, _REDIS_URL = _require_container_qa_environment()

# Import only after forbidding dotenv and validating every connection target.
from config import settings as _base  # noqa: E402

globals().update({key: value for key, value in vars(_base).items() if key.isupper()})

DEBUG = True
SECRET_KEY = _EXPECTED_SECRET
ALLOWED_HOSTS = ["localhost", "127.0.0.1", "testserver"]
JURIX_BUILD_PROFILE = "qa"
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": urlparse(_DATABASE_URL).path.lstrip("/"),
        "USER": _EXPECTED_DATABASE["username"],
        "PASSWORD": _EXPECTED_DATABASE["password"],
        "HOST": _EXPECTED_DATABASE["hostname"],
        "PORT": str(_EXPECTED_DATABASE["port"]),
        "TEST": {"NAME": "test_jurix_audit"},
    }
}
REDIS_URL = _REDIS_URL
CACHE_REDIS_URL = "redis://redis:6379/1"
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_BEAT_SCHEDULE = {}
if os.environ.get("SAPL_SYNC_SCHEDULE_ENABLED") == "1":
    sapl_incremental_limit = max(
        1, min(50, int(os.environ.get("SAPL_INCREMENTAL_SYNC_LIMIT", "50")))
    )
    CELERY_BEAT_SCHEDULE.update(
        {
            "incremental-sapl-sync-daily-qa": {
                "task": "ingestion.incremental_sync_sapl_task",
                "schedule": crontab(hour=2, minute=0),
                "kwargs": {"limit": sapl_incremental_limit},
                "options": {"queue": "normative_qa"},
            },
            "sapl-full-sweep-weekly-qa": {
                "task": "ingestion.full_sync_sapl_task",
                "schedule": crontab(day_of_week="sun", hour=3, minute=0),
                "kwargs": {"limit": 50},
                "options": {"queue": "normative_qa"},
            },
        }
    )
if os.environ.get("JURIX_QA_DOM_NATAL_SYNC_SCHEDULE_ENABLED") == "1":
    CELERY_BEAT_SCHEDULE["dom-natal-editions-daily-qa"] = {
        "task": "ingestion.sync_dom_natal_editions",
        "schedule": crontab(hour=2, minute=30),
        "kwargs": {"lookback_months": 3, "max_new_total": 5},
        "options": {"queue": "normative_qa"},
    }
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_ROUTES = {
    task: {"queue": "normative_qa"}
    for task in (
        "legislation.check_foundation",
        "ingestion.enqueue_normative_impact",
        "ingestion.claim_normative_work_item",
        "ingestion.process_normative_work_item",
        "ingestion.dispatch_normative_work_batch",
        "ingestion.finish_normative_stage",
        "ingestion.fail_normative_stage",
        "ingestion.review_normative_work_item",
        "ingestion.reconcile_new_normative_targets",
        "ingestion.incremental_sync_sapl_task",
        "ingestion.full_sync_sapl_task",
        "ingestion.sync_dom_natal_editions",
    )
}
CELERYD_CONCURRENCY = 1
CELERYD_PREFETCH_MULTIPLIER = 1
USE_LOCMEM_CACHE = False
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_REDIS_URL,
        "KEY_PREFIX": "jurix-normative-container-qa",
    }
}
MEDIA_ROOT = QA_ROOT / "media"
STATIC_ROOT = QA_ROOT / "static"
JURIX_ATTACHMENT_ROOT = str(QA_ROOT / "attachments")
JURIX_ATTACHMENT_STAGING_DIR = QA_ROOT / "attachment-staging"
LOG_ROOT = QA_ROOT / "logs"
for _path in (MEDIA_ROOT, STATIC_ROOT, JURIX_ATTACHMENT_STAGING_DIR, LOG_ROOT):
    _path.mkdir(parents=True, exist_ok=True)
LOGGING = deepcopy(_base.LOGGING)
LOGGING["handlers"]["file"]["filename"] = str(LOG_ROOT / "jurix.log")
NORMATIVE_ARCHIVE_ENABLED = True
NORMATIVE_ARCHIVE_ASSISTANT_ENABLED = True
SAPL_MATTER_LOOKUP_ENABLED = False
NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED = True
NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED = True
NORMATIVE_GRAPH_ENABLED = True
PGM_CONSOLIDATION_DEMO_ENABLED = True
NORMATIVE_HISTORY_ENABLED = True
RAG_GRAPH_CONTEXT_ENABLED = True
READINESS_REQUIRE_OLLAMA = False
READINESS_REQUIRE_CORPUS = False
