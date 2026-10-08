"""Guarded command runner for the isolated normative-graph QA environment."""

from __future__ import annotations

import argparse
import os
import socket
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlparse

DATABASE_URL = "postgresql://jurix_audit:audit-only-local-fixture@127.0.0.1:55432/jurix_audit"
REDIS_URL = "redis://127.0.0.1:16380/0"
CACHE_REDIS_URL = "redis://127.0.0.1:16380/1"
QA_SECRET = "jurix-normative-qa-only-not-for-deployment"
ROOT = Path(__file__).resolve().parents[1]


def _validate_target(database_url: str, redis_url: str, cache_url: str) -> None:
    database = urlparse(database_url)
    if (
        database.scheme != "postgresql"
        or database.hostname != "127.0.0.1"
        or database.port != 55432
        or database.username != "jurix_audit"
        or database.password != "audit-only-local-fixture"
        or database.path != "/jurix_audit"
    ):
        raise ValueError("refusing database target outside the dedicated audit fixture")
    for value in (redis_url, cache_url):
        parsed = urlparse(value)
        if (
            parsed.scheme != "redis"
            or parsed.hostname != "127.0.0.1"
            or parsed.port != 16380
            or parsed.username
            or parsed.password
        ):
            raise ValueError("refusing Redis target outside the dedicated audit fixture")


def _qa_environment() -> dict[str, str]:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise ValueError("set JURIX_QA_ONLY=1 explicitly before running QA commands")
    raw_root = os.environ.get("JURIX_QA_ROOT", "")
    if not raw_root:
        raise ValueError("set JURIX_QA_ROOT to a unique directory under the system temp path")
    root = Path(raw_root).resolve()
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "").resolve()
    if not temp.is_dir() or not root.is_relative_to(temp) or root == temp:
        raise ValueError("JURIX_QA_ROOT must be a child of the system temp directory")
    root.mkdir(parents=True, exist_ok=True)
    _validate_target(DATABASE_URL, REDIS_URL, CACHE_REDIS_URL)

    env = os.environ.copy()
    # Remove ambient values that could redirect Django, storage or providers.
    for key in (
        "DATABASE_URL",
        "DB_HOST",
        "DB_PORT",
        "POSTGRES_DB",
        "POSTGRES_USER",
        "POSTGRES_PASSWORD",
        "REDIS_URL",
        "CACHE_REDIS_URL",
        "DJANGO_SECRET_KEY",
        "DEBUG",
        "ALLOWED_HOSTS",
        "USE_SQLITE",
        "USE_LOCMEM_CACHE",
        "JURIX_ATTACHMENT_ROOT",
        "JURIX_ATTACHMENT_STAGING_DIR",
        "OLLAMA_BASE_URL",
        "JURIX_QA_REVIEWER_PASSWORD",
    ):
        env.pop(key, None)
    env.update(
        {
            "JURIX_QA_ONLY": "1",
            "JURIX_QA_ROOT": str(root),
            "DJANGO_SKIP_DOTENV": "1",
            "DJANGO_SETTINGS_MODULE": "config.settings_normative_qa",
            "DATABASE_URL": DATABASE_URL,
            "REDIS_URL": REDIS_URL,
            "CACHE_REDIS_URL": CACHE_REDIS_URL,
            "DJANGO_SECRET_KEY": QA_SECRET,
            "DEBUG": "True",
            "ALLOWED_HOSTS": "127.0.0.1,localhost,testserver",
            "USE_SQLITE": "False",
            "USE_LOCMEM_CACHE": "False",
            "OLLAMA_BASE_URL": "http://127.0.0.1:11434",
            "CELERY_TASK_ALWAYS_EAGER": "False",
        }
    )
    return env


def _allowed_command(command: list[str]) -> list[str]:
    if not command:
        raise ValueError("--run requires an allowlisted command")
    parts = command[1:] if command[0] == "--" else command
    if not parts:
        raise ValueError("--run requires an allowlisted command")
    executable = parts[0].lower()
    args = parts[1:]
    if executable in {"python", "python.exe"}:
        if args[:1] == ["manage.py"]:
            allowed = {
                ("check",),
                ("check", "--deploy"),
                ("migrate", "--plan"),
                ("migrate",),
                ("makemigrations", "legislation", "operations"),
                ("makemigrations", "--check", "--dry-run"),
                ("showmigrations",),
                ("runserver", "127.0.0.1:8007", "--noreload"),
                ("runserver", "127.0.0.1:8009", "--noreload"),
                ("runserver", "127.0.0.1:8010", "--noreload"),
                ("runserver", "127.0.0.1:8011", "--noreload"),
                ("runserver", "127.0.0.1:8012", "--noreload"),
                ("runserver", "127.0.0.1:8013", "--noreload"),
                ("runserver", "127.0.0.1:8014", "--noreload"),
                ("runserver", "127.0.0.1:8015", "--noreload"),
                ("runserver", "127.0.0.1:8016", "--noreload"),
                ("runserver", "127.0.0.1:8017", "--noreload"),
                ("runserver", "127.0.0.1:8018", "--noreload"),
                ("runserver", "127.0.0.1:8019", "--noreload"),
                ("runserver", "127.0.0.1:8020", "--noreload"),
                ("runserver", "127.0.0.1:8021", "--noreload"),
                ("runserver", "127.0.0.1:8022", "--noreload"),
                ("runserver", "127.0.0.1:8023", "--noreload"),
                ("runserver", "127.0.0.1:8024", "--noreload"),
                ("runserver", "127.0.0.1:8025", "--noreload"),
                ("runserver", "127.0.0.1:8026", "--noreload"),
            }
            command_args = args[1:]
            if tuple(command_args) not in allowed:
                if command_args[:1] == ["import_normative_archive"]:
                    allowed_flags = {
                        "--archive", "--manifest", "--limit", "--batch-size", "--resume", "--apply"
                    }
                    if "--all" in command_args or any(
                        item.startswith("--") and item not in allowed_flags for item in command_args[1:]
                    ):
                        raise ValueError("archive import flag is not on the QA allowlist")
                    options = command_args[1:]
                    if "--archive" not in options or "--manifest" not in options:
                        raise ValueError("archive import requires explicit archive and manifest paths")
                elif command_args[:1] == ["stage_normative_corpus"]:
                    allowed_flags = {
                        "--archive", "--manifest", "--batch-size", "--byte-budget",
                        "--time-budget-seconds", "--resume", "--dry-run", "--apply",
                    }
                    options = command_args[1:]
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("corpus staging flag is not on the QA allowlist")
                    if "--archive" not in options or "--manifest" not in options:
                        raise ValueError("corpus staging requires explicit archive and manifest paths")
                    manifest_index = options.index("--manifest")
                    if manifest_index + 1 >= len(options):
                        raise ValueError("corpus staging --manifest requires a path")
                    manifest_path = Path(options[manifest_index + 1]).resolve()
                    qa_root_value = os.environ.get("JURIX_QA_ROOT")
                    if not qa_root_value:
                        raise ValueError("corpus staging requires JURIX_QA_ROOT")
                    qa_root = Path(qa_root_value).resolve()
                    if not manifest_path.is_relative_to(qa_root) or manifest_path == qa_root:
                        raise ValueError("corpus staging manifest must stay inside JURIX_QA_ROOT")
                elif command_args[:1] == ["seed_normative_qa"]:
                    options = command_args[1:]
                    if options[:1] != ["--output"] or len(options) != 2:
                        raise ValueError("synthetic seed requires one explicit --output path")
                elif command_args[:1] == ["build_pilot_manifest"]:
                    allowed_flags = {
                        "--schema-version", "--output", "--corpus-limit", "--pilot-size",
                        "--document-sample-size",
                    }
                    options = command_args[1:]
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("pilot manifest flag is not on the QA allowlist")
                    if "--output" not in options:
                        raise ValueError("QA pilot manifest requires an explicit output path")
                    output_index = options.index("--output")
                    if output_index + 1 >= len(options):
                        raise ValueError("QA pilot manifest --output requires a path")
                    output_path = Path(options[output_index + 1]).resolve()
                    if not output_path.is_relative_to(Path(os.environ["JURIX_QA_ROOT"]).resolve()):
                        raise ValueError("QA pilot manifest output must stay inside JURIX_QA_ROOT")
                elif command_args[:1] == ["diagnose_qa_archive_overview"]:
                    options = command_args[1:]
                    if len(options) != 2 or options[0] != "--output":
                        raise ValueError("QA overview diagnostic requires exactly one --output path")
                    output_path = Path(options[1]).resolve()
                    qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                    if not output_path.is_relative_to(qa_root) or output_path == qa_root:
                        raise ValueError("QA overview diagnostic output must stay inside JURIX_QA_ROOT")
                elif command_args[:1] == ["build_normative_snapshots"]:
                    allowed_flags = {"--as-of", "--norma-id", "--limit", "--apply"}
                    options = command_args[1:]
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("snapshot build flag is not on the QA allowlist")
                    if "--as-of" not in options:
                        raise ValueError("snapshot build requires an explicit --as-of date")
                    if "--apply" in options and options.count("--apply") != 1:
                        raise ValueError("snapshot apply flag is invalid")
                elif command_args[:1] == ["promote_normative_documents"]:
                    allowed_flags = {
                        "--document", "--norma-id", "--actor", "--reason", "--fingerprint",
                        "--identity-key", "--role", "--confirm-public-record", "--plan-legacy", "--output",
                    }
                    if any(item.startswith("--") and item not in allowed_flags for item in command_args[1:]):
                        raise ValueError("promotion flag is not on the QA allowlist")
                elif command_args[:1] == ["run_normative_qa_pipeline"]:
                    allowed_flags = {"--norma-id", "--item-id", "--max-nodes", "--max-items"}
                    if any(item.startswith("--") and item not in allowed_flags for item in command_args[1:]):
                        raise ValueError("normative QA pipeline flag is not on the QA allowlist")
                    if ("--norma-id" in command_args) == ("--item-id" in command_args):
                        raise ValueError("choose exactly one of --norma-id or --item-id")
                else:
                    raise ValueError("manage.py command is not on the QA allowlist")
        elif args[:2] == ["-m", "pytest"]:
            if any(
                arg.startswith("-")
                and arg not in {"-q", "-v", "--reuse-db", "--create-db", "--tb=short"}
                for arg in args[2:]
            ):
                raise ValueError("pytest option is not on the QA allowlist")
        elif args == [
            "-m", "celery", "-A", "config", "worker", "--pool=solo",
            "--concurrency=1", "-Q", "normative_qa", "-l", "warning",
        ]:
            pass
        elif args[:1] == ["scripts/architecture_budget_v2.py"]:
            pass
        elif args[:1] == ["scripts/validate_documentation_contract.py"]:
            pass
        elif args == ["scripts/benchmark_normative_api_qa.py"]:
            pass
        elif args[:1] == ["scripts/collect_normative_rag_experiment.py"]:
            allowed_flags = {
                "--cases", "--output", "--max-cases", "--temperature", "--max-sources",
                "--no-warm-cache",
            }
            options = args[1:]
            if options == ["--help"]:
                pass
            elif any(item.startswith("--") and item not in allowed_flags for item in options):
                raise ValueError("RAG experiment collector received an unsupported flag")
            else:
                if "--cases" not in options or "--output" not in options:
                    raise ValueError("RAG experiment collector requires explicit cases and output")
                if options.index("--cases") + 1 >= len(options) or options.index("--output") + 1 >= len(options):
                    raise ValueError("RAG experiment collector path option has no value")
                cases_path = Path(options[options.index("--cases") + 1]).resolve()
                output_path = Path(options[options.index("--output") + 1]).resolve()
                cases_root = (ROOT / "benchmarks" / "corpus" / "municipal_natal").resolve()
                qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                if not cases_path.is_relative_to(cases_root):
                    raise ValueError("RAG experiment cases must be inside the municipal QA benchmark directory")
                if not output_path.is_relative_to(qa_root) or output_path == qa_root:
                    raise ValueError("RAG experiment output must stay inside JURIX_QA_ROOT")
        elif args[:1] == ["scripts/inventory_normative_archive.py"]:
            if len(args) != 5 or args[1] != "--archive" or args[3] != "--output":
                raise ValueError("inventory command requires --archive and --output only")
        else:
            raise ValueError("Python script is not on the QA allowlist")
        return [sys.executable, *args]
    if executable in {"npm", "npm.cmd"} and args == ["test", "--prefix", "tests/js"]:
        return ["npm.cmd", *args]
    if executable == "node" and args == ["tests/js/normative-product-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-rag-live-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-admin-review.browser.test.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-collections.browser.test.mjs"]:
        return ["node.exe", *args]
    raise ValueError("command is not on the QA allowlist")


def _command_environment(env: dict[str, str], command: list[str]) -> dict[str, str]:
    """Expose the temporary reviewer credential only to synthetic seed and review QA."""
    scoped = env.copy()
    scoped.pop("JURIX_QA_REVIEWER_PASSWORD", None)
    parts = command[1:] if command[:1] == ["--"] else command
    if (
        parts[:2] == ["python", "manage.py"]
        and parts[2:3] == ["seed_normative_qa"]
        and os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
    ):
        scoped["JURIX_QA_REVIEWER_PASSWORD"] = os.environ["JURIX_QA_REVIEWER_PASSWORD"]
    elif (
        parts == ["node", "tests/js/normative-admin-review.browser.test.mjs"]
        and os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
    ):
        scoped["JURIX_QA_REVIEWER_PASSWORD"] = os.environ["JURIX_QA_REVIEWER_PASSWORD"]
    elif (
        parts == ["node", "tests/js/normative-collections.browser.test.mjs"]
        and os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
    ):
        scoped["JURIX_QA_REVIEWER_PASSWORD"] = os.environ["JURIX_QA_REVIEWER_PASSWORD"]
    return scoped


def _check_tcp(host: str, port: int, label: str) -> tuple[bool, str]:
    try:
        with socket.create_connection((host, port), timeout=2):
            return True, f"{label}: reachable"
    except OSError:
        return False, f"{label}: unavailable on the dedicated QA port"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--check", action="store_true", help="validate QA-only environment")
    group.add_argument("--check-services", action="store_true", help="probe dedicated QA ports")
    group.add_argument("--run", nargs=argparse.REMAINDER, help="run an allowlisted command")
    options = parser.parse_args()
    try:
        env = _qa_environment()
        if options.check:
            print("QA guard: accepted dedicated audit database, Redis and isolated temp root.")
            print(f"QA root: {env['JURIX_QA_ROOT']}")
            return 0
        if options.check_services:
            results = [
                _check_tcp("127.0.0.1", 55432, "PostgreSQL QA"),
                _check_tcp("127.0.0.1", 16380, "Redis QA"),
            ]
            for _, message in results:
                print(message)
            return 0 if all(ok for ok, _ in results) else 2
        command = _allowed_command(options.run)
        command_env = _command_environment(env, options.run)
        return subprocess.run(command, cwd=ROOT, env=command_env, check=False).returncode
    except (ValueError, OSError) as exc:
        print(f"QA guard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
