from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _container_qa_env(root: Path, temp_root: Path) -> dict[str, str]:
    env = os.environ.copy()
    for name in (
        "DATABASE_URL",
        "REDIS_URL",
        "CACHE_REDIS_URL",
        "DJANGO_SECRET_KEY",
        "JURIX_QA_ONLY",
        "JURIX_QA_ROOT",
        "DJANGO_SKIP_DOTENV",
    ):
        env.pop(name, None)
    env.update(
        {
            "JURIX_QA_ONLY": "1",
            "JURIX_QA_ROOT": str(root),
            "DJANGO_SKIP_DOTENV": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings_normative_container_qa",
            "DJANGO_SECRET_KEY": "audit-only-local-secret-not-for-production",
            "DEBUG": "1",
            "DATABASE_URL": (
                "postgresql://jurix_audit:audit-only-local-fixture@db:5432/jurix_audit"
            ),
            "REDIS_URL": "redis://redis:6379/0",
            "CACHE_REDIS_URL": "redis://redis:6379/1",
            "TEMP": str(temp_root),
            "TMP": str(temp_root),
        }
    )
    return env


def _load_profile(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "from django.conf import settings; import json; print(json.dumps({"
            "'database': settings.DATABASES['default']['NAME'],"
            "'db_host': settings.DATABASES['default']['HOST'],"
            "'broker': settings.CELERY_BROKER_URL,"
            "'cache': settings.CACHES['default']['LOCATION'],"
            "'qa_root': str(settings.QA_ROOT),"
            "'queue': settings.CELERY_TASK_ROUTES['ingestion.sync_dom_natal_editions']['queue'],"
            "'foundation_queue': settings.CELERY_TASK_ROUTES['legislation.check_foundation']['queue'],"
            "'beat': settings.CELERY_BEAT_SCHEDULE,"
            "'matter_lookup': settings.SAPL_MATTER_LOOKUP_ENABLED,"
            "'sapl_base': settings.SAPL_BASE_URL}))",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_container_qa_profile_uses_only_isolated_services_and_disables_beat(tmp_path):
    temp_root = tmp_path / "container-temp"
    qa_root = temp_root / "jurix-normative-qa"
    temp_root.mkdir()
    result = _load_profile(_container_qa_env(qa_root, temp_root))

    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings["database"] == "jurix_audit"
    assert settings["db_host"] == "db"
    assert settings["broker"] == "redis://redis:6379/0"
    assert settings["cache"] == "redis://redis:6379/1"
    assert settings["qa_root"] == str(qa_root.resolve())
    assert settings["queue"] == "normative_qa"
    assert settings["foundation_queue"] == "normative_qa"
    assert settings["beat"] == {}
    assert settings["matter_lookup"] is False
    assert settings["sapl_base"] == "https://sapl.natal.rn.leg.br/api"


def test_container_qa_profile_allows_only_namespaced_migration_scratch_database(tmp_path):
    temp_root = tmp_path / "container-temp"
    temp_root.mkdir()
    env = _container_qa_env(temp_root / "jurix-normative-qa", temp_root)
    env["DATABASE_URL"] = (
        env["DATABASE_URL"].rsplit("/", 1)[0] + "/jurix_migtest_12345"
    )

    result = _load_profile(env)

    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["database"] == "jurix_migtest_12345"


@pytest.mark.parametrize(
    ("variable", "value"),
    [
        (
            "DATABASE_URL",
            "postgresql://jurix_user:secret@db:5432/production",
        ),
        ("REDIS_URL", "redis://production-redis:6379/0"),
        ("CACHE_REDIS_URL", "redis://redis:6379/0"),
    ],
)
def test_container_qa_profile_rejects_non_audit_database_or_redis(
    tmp_path, variable, value
):
    temp_root = tmp_path / "container-temp"
    temp_root.mkdir()
    env = _container_qa_env(temp_root / "jurix-normative-qa", temp_root)
    env[variable] = value
    result = _load_profile(env)

    assert result.returncode != 0
    assert "dedicated audit" in result.stderr
    assert "secret" not in result.stderr
