from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "normative_qa.py"
SPEC = importlib.util.spec_from_file_location("normative_qa_helper", MODULE_PATH)
qa = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa)


def test_accepts_only_dedicated_audit_targets():
    qa._validate_target(qa.DATABASE_URL, qa.REDIS_URL, qa.CACHE_REDIS_URL)


@pytest.mark.parametrize(
    "database,redis,cache",
    [
        ("sqlite:///db.sqlite3", qa.REDIS_URL, qa.CACHE_REDIS_URL),
        ("postgresql://user:secret@db:5432/jurix", qa.REDIS_URL, qa.CACHE_REDIS_URL),
        (qa.DATABASE_URL, "redis://localhost:6379/0", qa.CACHE_REDIS_URL),
        (qa.DATABASE_URL, qa.REDIS_URL, "redis://remote:6379/1"),
    ],
)
def test_rejects_non_qa_targets(database, redis, cache):
    with pytest.raises(ValueError):
        qa._validate_target(database, redis, cache)


def test_command_runner_does_not_accept_shell_or_unknown_commands():
    with pytest.raises(ValueError):
        qa._allowed_command(["python", "-c", "print('not allowed')"])
    with pytest.raises(ValueError):
        qa._allowed_command(["python", "manage.py", "flush"])


def test_command_runner_maps_python_to_active_interpreter():
    assert qa._allowed_command(["python", "manage.py", "check"])[0] == qa.sys.executable


def test_command_runner_allows_only_the_runbook_qa_web_server():
    expected = ["python", "manage.py", "runserver", "127.0.0.1:8007", "--noreload"]
    assert qa._allowed_command(expected) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8007",
        "--noreload",
    ]
    diagnostic_port = ["python", "manage.py", "runserver", "127.0.0.1:8009", "--noreload"]
    assert qa._allowed_command(diagnostic_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8009",
        "--noreload",
    ]
    for unsafe in (
        ["python", "manage.py", "runserver", "127.0.0.1:8006", "--noreload"],
        ["python", "manage.py", "runserver", "0.0.0.0:8009", "--noreload"],
        ["python", "manage.py", "runserver", "0.0.0.0:8007", "--noreload"],
        ["python", "manage.py", "runserver", "127.0.0.1:8007"],
    ):
        with pytest.raises(ValueError):
            qa._allowed_command(unsafe)


def test_command_runner_allows_only_the_bounded_normative_qa_worker_and_dispatcher():
    worker = [
        "python", "-m", "celery", "-A", "config", "worker", "--pool=solo",
        "--concurrency=1", "-Q", "normative_qa", "-l", "warning",
    ]
    assert qa._allowed_command(worker)[0] == qa.sys.executable
    with pytest.raises(ValueError):
        qa._allowed_command(worker[:-4] + ["-Q", "default", "-l", "warning"])
    assert qa._allowed_command([
        "python", "manage.py", "run_normative_qa_pipeline", "--norma-id", "8",
        "--max-nodes", "10", "--max-items", "10",
    ])[0] == qa.sys.executable
    with pytest.raises(ValueError):
        qa._allowed_command([
            "python", "manage.py", "run_normative_qa_pipeline", "--norma-id", "8", "--all",
        ])


def test_django_settings_reject_a_database_url_outside_the_audit_service():
    env = os.environ.copy()
    env.update(
        {
            "JURIX_QA_ONLY": "1",
            "JURIX_QA_ROOT": str(Path(os.environ["JURIX_QA_ROOT"]).resolve()),
            "DJANGO_SKIP_DOTENV": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings_normative_qa",
            "DATABASE_URL": "postgresql://user:pass@127.0.0.1:5432/production",
            "REDIS_URL": qa.REDIS_URL,
            "CACHE_REDIS_URL": qa.CACHE_REDIS_URL,
        }
    )
    result = subprocess.run(
        [sys.executable, "-c", "import config.settings_normative_qa"],
        cwd=qa.ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode != 0
    assert "only accept the dedicated local audit PostgreSQL target" in result.stderr
