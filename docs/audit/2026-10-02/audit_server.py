"""Serve the unchanged workspace against a temporary backup of its SQLite database."""
import os
from pathlib import Path
import sqlite3
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.chdir(ROOT)
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
from django.conf import settings

if not settings.DATABASES["default"]["ENGINE"].endswith("sqlite3"):
    raise SystemExit("Audit isolation currently supports the configured local SQLite database only.")
audit_temp = Path(tempfile.mkdtemp(prefix="jurix-audit-20261002-"))
with sqlite3.connect(f"file:{settings.DATABASES['default']['NAME']}?mode=ro", uri=True) as source:
    with sqlite3.connect(audit_temp / "audit.sqlite3") as dest:
        source.backup(dest)
settings.DATABASES["default"]["NAME"] = audit_temp / "audit.sqlite3"
settings.MIDDLEWARE = [*settings.MIDDLEWARE, "audit_runtime.AuditTelemetryMiddleware"]
settings.LOGGING = {"version": 1, "disable_existing_loggers": False,
                    "handlers": {"console": {"class": "logging.StreamHandler"}},
                    "root": {"handlers": ["console"], "level": "WARNING"},
                    "loggers": {"django.server": {"handlers": ["console"], "level": "WARNING", "propagate": False}}}
import django
django.setup()
from django.core.management import execute_from_command_line
print("Audit: original configuration retained; only database location and logging are isolated.", flush=True)
execute_from_command_line(["audit", "runserver", "127.0.0.1:8006", "--noreload"])
