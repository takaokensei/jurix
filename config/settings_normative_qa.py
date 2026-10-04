"""Settings isolated from the developer and production Jurix databases.

These settings are intentionally opt-in and only accept the dedicated local
audit PostgreSQL/Redis ports declared by ``docker-compose.audit.yml``.
"""

from __future__ import annotations

import os
import re
from copy import deepcopy
from pathlib import Path
from urllib.parse import urlparse

from django.core.exceptions import ImproperlyConfigured

_EXPECTED_DATABASE = {
    "scheme": "postgresql",
    "hostname": "127.0.0.1",
    "port": 55432,
    "username": "jurix_audit",
    "database": "jurix_audit",
    "password": "audit-only-local-fixture",
}
_EXPECTED_REDIS = {"hostname": "127.0.0.1", "port": 16380}


def _require_qa_environment() -> Path:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise ImproperlyConfigured("QA settings require JURIX_QA_ONLY=1.")
    if os.environ.get("DJANGO_SKIP_DOTENV") != "1":
        raise ImproperlyConfigured("QA settings must not load a project .env file.")

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
    actual_connection = {key: value for key, value in actual_database.items() if key != "database"}
    database_name = actual_database["database"]
    allowed_name = database_name == "jurix_audit" or bool(
        re.fullmatch(r"jurix_migtest_[0-9]+", database_name)
    )
    if actual_connection != expected_connection or not allowed_name:
        raise ImproperlyConfigured(
            "QA settings only accept the dedicated local audit PostgreSQL target."
        )

    for variable in ("REDIS_URL", "CACHE_REDIS_URL"):
        parsed = urlparse(os.environ.get(variable, ""))
        if (
            parsed.scheme != "redis"
            or parsed.hostname != _EXPECTED_REDIS["hostname"]
            or parsed.port != _EXPECTED_REDIS["port"]
            or parsed.username
            or parsed.password
        ):
            raise ImproperlyConfigured(
                f"{variable} must use the dedicated local audit Redis service."
            )

    raw_root = os.environ.get("JURIX_QA_ROOT", "")
    if not raw_root:
        raise ImproperlyConfigured("JURIX_QA_ROOT must point to a dedicated QA directory.")
    root = Path(raw_root).resolve()
    temp_root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "").resolve()
    if not temp_root.is_dir() or not root.is_relative_to(temp_root) or root == temp_root:
        raise ImproperlyConfigured("JURIX_QA_ROOT must be a child of the system temp directory.")
    root.mkdir(parents=True, exist_ok=True)
    return root


QA_ROOT = _require_qa_environment()

# Prevent config.settings from reading .env; the helper supplies fixture values
# explicitly and strips inherited connection settings before launching children.
from config import settings as _base  # noqa: E402

globals().update({key: value for key, value in vars(_base).items() if key.isupper()})

DEBUG = True
SECRET_KEY = "jurix-normative-qa-only-not-for-deployment"
ALLOWED_HOSTS = ["127.0.0.1", "localhost", "testserver"]
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": urlparse(os.environ["DATABASE_URL"]).path.lstrip("/"),
        "USER": urlparse(os.environ["DATABASE_URL"]).username,
        "PASSWORD": urlparse(os.environ["DATABASE_URL"]).password,
        "HOST": urlparse(os.environ["DATABASE_URL"]).hostname,
        "PORT": str(urlparse(os.environ["DATABASE_URL"]).port),
        "TEST": {"NAME": "test_jurix_audit"}
        if urlparse(os.environ["DATABASE_URL"]).path == "/jurix_audit"
        else {},
    }
}
REDIS_URL = "redis://127.0.0.1:16380/0"
CACHE_REDIS_URL = "redis://127.0.0.1:16380/1"
CELERY_BROKER_URL = REDIS_URL
CELERY_RESULT_BACKEND = REDIS_URL
CELERY_BEAT_SCHEDULE = {}
CELERY_TASK_ALWAYS_EAGER = False
CELERY_TASK_ROUTES = {
    "ingestion.enqueue_normative_impact": {"queue": "normative_qa"},
    "ingestion.claim_normative_work_item": {"queue": "normative_qa"},
    "ingestion.process_normative_work_item": {"queue": "normative_qa"},
    "ingestion.dispatch_normative_work_batch": {"queue": "normative_qa"},
    "ingestion.finish_normative_stage": {"queue": "normative_qa"},
    "ingestion.fail_normative_stage": {"queue": "normative_qa"},
    "ingestion.review_normative_work_item": {"queue": "normative_qa"},
}
CELERYD_CONCURRENCY = 1
CELERYD_PREFETCH_MULTIPLIER = 1
USE_LOCMEM_CACHE = False
CACHES = {
    "default": {
        "BACKEND": "django.core.cache.backends.redis.RedisCache",
        "LOCATION": CACHE_REDIS_URL,
        "KEY_PREFIX": "jurix-normative-qa",
    }
}
MEDIA_ROOT = QA_ROOT / "media"
STATIC_ROOT = QA_ROOT / "static"
STATIC_ROOT.mkdir(parents=True, exist_ok=True)
JURIX_ATTACHMENT_ROOT = str(QA_ROOT / "attachments")
JURIX_ATTACHMENT_STAGING_DIR = QA_ROOT / "attachment-staging"
LOG_ROOT = QA_ROOT / "logs"
LOG_ROOT.mkdir(parents=True, exist_ok=True)
LOGGING = deepcopy(_base.LOGGING)
LOGGING["handlers"]["file"]["filename"] = str(LOG_ROOT / "jurix.log")
NORMATIVE_ARCHIVE_ENABLED = True
NORMATIVE_ARCHIVE_ASSISTANT_ENABLED = True
NORMATIVE_ARCHIVE_SAPL_LINKS_ENABLED = True
NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED = True
NORMATIVE_GRAPH_ENABLED = True
NORMATIVE_HISTORY_ENABLED = True
RAG_GRAPH_CONTEXT_ENABLED = True
READINESS_REQUIRE_OLLAMA = False
READINESS_REQUIRE_CORPUS = False
