"""Single production-readiness gate for local use and CI.

The gate is intentionally conservative: it validates the repository shape and,
when requested, executes the same Django/Ruff/Pytest checks used for release.
It does not claim legal correctness; that requires the reviewed RAG benchmark.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "manage.py",
    "pyproject.toml",
    "requirements.txt",
    "docker-compose.prod.yml",
    ".env.production.example",
    "docs/production-validation.md",
    "scripts/check_rag_regression.py",
    "scripts/validate_rag_benchmark.py",
)


def fail(message: str) -> None:
    print(f"[FAIL] {message}")


def ok(message: str) -> None:
    print(f"[ OK ] {message}")


def run(command: list[str], env: dict[str, str] | None = None) -> int:
    print("[RUN ]", " ".join(command))
    return subprocess.run(command, cwd=ROOT, env=env, check=False).returncode


def validate_files() -> int:
    failures = 0
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            fail(f"required file missing: {relative}")
            failures += 1
        else:
            ok(f"found {relative}")

    compose = (ROOT / "docker-compose.prod.yml").read_text(encoding="utf-8")
    if "jurix_data:" not in compose:
        fail("docker-compose.prod.yml has no persistent jurix_data volume")
        failures += 1
    else:
        ok("production compose declares persistent application data")

    if "DJANGO_SECRET_KEY:?" not in compose:
        fail("production compose does not require DJANGO_SECRET_KEY")
        failures += 1
    else:
        ok("production compose requires DJANGO_SECRET_KEY")

    has_literal_db_password = any(
        line.strip().startswith("POSTGRES_PASSWORD:") and "${POSTGRES_PASSWORD" not in line
        for line in compose.splitlines()
    )
    if has_literal_db_password:
        fail("production compose contains a literal PostgreSQL password")
        failures += 1
    else:
        ok("production compose has no literal database password")

    env_example = (ROOT / ".env.production.example").read_text(encoding="utf-8")
    for key in (
        "DJANGO_SECRET_KEY",
        "ALLOWED_HOSTS",
        "OLLAMA_BASE_URL",
        "OLLAMA_MODEL",
        "SAPL_OCR_MAX_PAGES",
        "STORAGE_BACKEND",
    ):
        if not re.search(rf"^{re.escape(key)}=", env_example, re.MULTILINE):
            fail(f"production env example omits {key}")
            failures += 1
        else:
            ok(f"production env documents {key}")

    ci = (ROOT / ".github/workflows/ci.yml").read_text(encoding="utf-8")
    duplicate_run = re.compile(r"(?m)^\s+run:\s*\|\n\s+run:\s*\|")
    if duplicate_run.search(ci):
        fail("ci.yml contains consecutive duplicate run keys")
        failures += 1
    else:
        ok("ci.yml has no duplicate run-key block")

    return failures


def run_django_gate() -> int:
    env = os.environ.copy()
    env.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
    env.setdefault("DATABASE_URL", "postgresql://jurix:testpassword@localhost:5432/jurix_test")
    env.setdefault("REDIS_URL", "redis://localhost:6379/0")
    env.setdefault("DJANGO_SECRET_KEY", "ci-only-production-gate-secret-change-me")
    env.setdefault("DEBUG", "False")
    env.setdefault("ALLOWED_HOSTS", "localhost,127.0.0.1")
    env.setdefault("STORAGE_BACKEND", "local")
    env.setdefault("JURIX_ATTACHMENT_ROOT", "/app/data/chat_attachments")
    env.setdefault("SAPL_OCR_MAX_PAGES", "200")
    env.setdefault("USE_LOCMEM_CACHE", "False")
    env.setdefault("SECURE_HSTS_SECONDS", "0")

    commands = [
        [sys.executable, "manage.py", "check", "--deploy"],
        [sys.executable, "manage.py", "validate_production_config"],
        [sys.executable, "manage.py", "makemigrations", "--check", "--dry-run"],
        [sys.executable, "-m", "pytest", "src/tests/", "-q"],
    ]
    return max(run(command, env=env) for command in commands)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--with-django", action="store_true")
    parser.add_argument("--with-lint", action="store_true")
    parser.add_argument("--require-rag", action="store_true")
    args = parser.parse_args(argv)

    failures = validate_files()

    if args.with_lint:
        failures += bool(run([sys.executable, "-m", "ruff", "check", "src"]))
        failures += bool(run([sys.executable, "-m", "ruff", "format", "--check", "src"]))

    if args.with_django:
        failures += bool(run_django_gate())

    manifest = ROOT / "benchmarks/rag/production/manifest.json"
    if manifest.exists():
        failures += bool(run([sys.executable, "scripts/validate_rag_benchmark.py", str(manifest)]))
    elif args.require_rag:
        fail("production RAG benchmark manifest is missing")
        failures += 1
    else:
        print("[WARN] production RAG benchmark manifest not populated yet")

    if failures:
        print(f"Production gate failed with {failures} failing check(s).")
        return 1

    print("Production gate passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
