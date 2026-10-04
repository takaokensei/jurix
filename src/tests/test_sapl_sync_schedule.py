import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _read_schedule(enabled: bool, incremental_limit: str = "50") -> dict:
    environment = {
        key: os.environ[key]
        for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
        if key in os.environ
    }
    environment.update(
        {
            "DJANGO_SKIP_DOTENV": "1",
            "DEBUG": "1",
            "DJANGO_SECRET_KEY": "schedule-test-only",
            "USE_SQLITE": "1",
            "SAPL_SYNC_SCHEDULE_ENABLED": "1" if enabled else "0",
            "SAPL_INCREMENTAL_SYNC_LIMIT": incremental_limit,
        }
    )
    code = """
import json
from config import settings

result = {}
for name, entry in settings.CELERY_BEAT_SCHEDULE.items():
    schedule = entry.get('schedule')
    result[name] = {
        'task': entry.get('task'),
        'kwargs': entry.get('kwargs', {}),
        'minute': getattr(schedule, '_orig_minute', None),
        'hour': getattr(schedule, '_orig_hour', None),
        'day_of_week': getattr(schedule, '_orig_day_of_week', None),
    }
print(json.dumps(result, sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", code],
        cwd=PROJECT_ROOT,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
        timeout=30,
    )
    return json.loads(completed.stdout)


def test_sapl_beat_schedules_are_disabled_by_default():
    schedule = _read_schedule(enabled=False)

    assert "expire-chat-attachments" in schedule
    assert "incremental-sapl-sync-daily" not in schedule
    assert "sapl-full-sweep-weekly" not in schedule


def test_opt_in_schedules_daily_incremental_and_weekly_bounded_full_sweep():
    schedule = _read_schedule(enabled=True, incremental_limit="500")

    daily = schedule["incremental-sapl-sync-daily"]
    assert daily["task"] == "ingestion.incremental_sync_sapl_task"
    assert daily["hour"] == 2
    assert daily["minute"] == 0
    assert daily["kwargs"] == {"limit": 50}

    weekly = schedule["sapl-full-sweep-weekly"]
    assert weekly["task"] == "ingestion.full_sync_sapl_task"
    assert weekly["day_of_week"] == "sun"
    assert weekly["hour"] == 3
    assert weekly["minute"] == 0
    assert weekly["kwargs"] == {"limit": 50}


def test_qa_settings_never_enable_beat_even_with_product_opt_in():
    with tempfile.TemporaryDirectory(prefix="jurix-schedule-qa-") as qa_root:
        environment = {
            key: os.environ[key]
            for key in ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP")
            if key in os.environ
        }
        environment.update(
            {
                "DJANGO_SKIP_DOTENV": "1",
                "DJANGO_SETTINGS_MODULE": "config.settings_normative_qa",
                "DEBUG": "1",
                "DJANGO_SECRET_KEY": "schedule-test-only",
                "JURIX_QA_ONLY": "1",
                "JURIX_QA_ROOT": qa_root,
                "DATABASE_URL": (
                    "postgresql://jurix_audit:audit-only-local-fixture"
                    "@127.0.0.1:55432/jurix_audit"
                ),
                "REDIS_URL": "redis://127.0.0.1:16380/0",
                "CACHE_REDIS_URL": "redis://127.0.0.1:16380/1",
                "SAPL_SYNC_SCHEDULE_ENABLED": "1",
            }
        )
        completed = subprocess.run(
            [
                sys.executable,
                "-c",
                "from config.settings_normative_qa import CELERY_BEAT_SCHEDULE; "
                "import json; print(json.dumps(CELERY_BEAT_SCHEDULE))",
            ],
            cwd=PROJECT_ROOT,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )

    assert json.loads(completed.stdout) == {}
