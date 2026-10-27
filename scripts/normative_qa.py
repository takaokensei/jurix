"""Guarded command runner for the isolated normative-graph QA environment."""

from __future__ import annotations

import argparse
import os
import re
import socket
import subprocess
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path
from urllib.parse import urlparse

DATABASE_URL = "postgresql://jurix_audit:audit-only-local-fixture@127.0.0.1:55432/jurix_audit"
REDIS_URL = "redis://127.0.0.1:16380/0"
CACHE_REDIS_URL = "redis://127.0.0.1:16380/1"
QA_SECRET = "jurix-normative-qa-only-not-for-deployment"
ROOT = Path(__file__).resolve().parents[1]
CONTAINER_STORAGE_COMMANDS = {
    "extract_archive_candidate_qa",
    "extract_archive_candidates_batch_qa",
    "inspect_archive_extraction_coverage_qa",
    "resume_archive_ocr_qa",
    "stage_lc55_original_candidate_qa",
}
HOST_STORAGE_SAPL_CANDIDATES = {
    # LC 258/2024 was staged by the host runner into JURIX_QA_ROOT. Keep its
    # selected-page OCR resume on that same verified host storage.
    "00c841d2-4b08-42a3-80b1-f018b1e86d43",
    # Ordinary Law 1,894/1969 is a pending original-PDF candidate for the LC258
    # Art. 260 species conflict; it is never accepted or consolidated here.
    "f08cb4c6-41e8-4332-8c4f-2a764ca2f6a6",
}
HOST_STORAGE_QA_DOCUMENTS = {
    # Official CTM 2021 municipal-consolidation PDF staged in the host QA evidence volume.
    "a68fdb23-c0aa-4082-8871-fe99096847b9",
    # Official CTM 2024 municipal-consolidation PDF staged by the host QA runner.
    "9d524b40-5e66-4678-9958-b9a9f9d1cf55",
    # Official promulgated LC 271/2025 amendment PDF staged by the host QA runner.
    "cb810b42-ecea-4cbc-870a-b2581c30df6c",
    # Official municipal LP 275/2009 PDF staged in the host QA evidence volume.
    "c452bfe5-1138-4962-a3f2-c4cc9b662007",
    # Official LP 275/2009 candidate staged from its previously hash-verified QA PDF.
    "8dea863e-e736-452e-8ca6-288f6061d239",
}


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
                ("check_source_sync_health",),
                (
                    "audit_archive_sapl_crosswalk_qa",
                    "--max-pages", "2", "--page-size", "100",
                ),
                (
                    "audit_archive_sapl_crosswalk_qa",
                    "--max-pages", "100", "--page-size", "100",
                ),
                (
                    "isolate_synthetic_norma_identity_qa",
                    "--norma-id", "7",
                    "--expected-identity-key",
                    "BR-RN-NATAL|lei_complementar|municipal_lc|198|2021",
                    "--expected-tipo", "Lei Complementar",
                    "--expected-numero", "198",
                    "--expected-ano", "2021",
                ),
                (
                    "isolate_synthetic_norma_identity_qa",
                    "--norma-id", "7",
                    "--expected-identity-key",
                    "BR-RN-NATAL|lei_complementar|municipal_lc|198|2021",
                    "--expected-tipo", "Lei Complementar",
                    "--expected-numero", "198",
                    "--expected-ano", "2021",
                    "--apply",
                ),
                ("provision_pgm_qa_reviewer",),
                ("provision_pgm_qa_reviewer", "--disable"),
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
                ("runserver", "127.0.0.1:8028", "--noreload"),
                ("runserver", "127.0.0.1:8029", "--noreload"),
                ("runserver", "127.0.0.1:8030", "--noreload"),
                ("runserver", "127.0.0.1:8040", "--noreload"),
                ("runserver", "127.0.0.1:8280", "--noreload"),
                ("runserver", "127.0.0.1:8281", "--noreload"),
                ("runserver", "127.0.0.1:8282", "--noreload"),
                ("runserver", "127.0.0.1:8283", "--noreload"),
                ("runserver", "127.0.0.1:8284", "--noreload"),
                ("runserver", "127.0.0.1:8285", "--noreload"),
                ("runserver", "127.0.0.1:8286", "--noreload"),
                ("runserver", "127.0.0.1:8287", "--noreload"),
                ("runserver", "127.0.0.1:8288", "--noreload"),
                ("runserver", "127.0.0.1:8289", "--noreload"),
                ("runserver", "127.0.0.1:8291", "--noreload"),
                ("runserver", "127.0.0.1:8292", "--noreload"),
                ("runserver", "127.0.0.1:8293", "--noreload"),
            }
            command_args = args[1:]
            if tuple(command_args) not in allowed:
                if command_args == [
                    "diagnose_sapl", "--limit", "10", "--max-pages", "4"
                ]:
                    # Bounded GET-only probe of the public Natal SAPL API. The
                    # command's configured base URL is pinned again in the
                    # subprocess environment below.
                    pass
                elif command_args[:1] == ["provision_pgm_qa_reviewer"]:
                    options = command_args[1:]
                    if (
                        len(options) not in {2, 3, 4}
                        or options[:1] != ["--username"]
                        or not re.fullmatch(r"jurix-pgm-preview-[0-9a-f]{8}", options[1])
                        or options[2:] not in (
                            [],
                            ["--disable"],
                            ["--include-pending-relations"],
                            ["--include-pending-relations", "--disable"],
                        )
                    ):
                        raise ValueError(
                            "QA preview reviewer accepts a generated username, optional pending-relations scope, and optional --disable"
                        )
                elif command_args[:1] == ["check_source_sync_health"]:
                    options = command_args[1:]
                    parsed = {}
                    index = 0
                    while index < len(options):
                        flag = options[index]
                        if flag == "--details":
                            if flag in parsed:
                                raise ValueError("source health option is duplicated")
                            parsed[flag] = True
                            index += 1
                            continue
                        if flag not in {"--source", "--max-age-hours"} or flag in parsed:
                            raise ValueError("source health option is not on the QA allowlist")
                        if index + 1 >= len(options):
                            raise ValueError("source health options require values")
                        parsed[flag] = options[index + 1]
                        index += 2
                    if parsed.get("--source", "sapl") not in {"sapl", "dom_natal"}:
                        raise ValueError("source health source is not on the QA allowlist")
                    if "--max-age-hours" in parsed:
                        value = parsed["--max-age-hours"]
                        if not value.isdecimal() or not 1 <= int(value) <= 8760:
                            raise ValueError("source health age is outside the QA limit")
                elif command_args[:1] == ["inspect_dom_natal_editions"]:
                    options = command_args[1:]
                    if len(options) not in {0, 2} or (
                        options and options[0] != "--lookback-months"
                    ):
                        raise ValueError("DOM catalog inspection accepts only --lookback-months N")
                    if options:
                        value = options[1]
                        if not value.isdecimal() or not 1 <= int(value) <= 12:
                            raise ValueError("DOM catalog lookback must be between 1 and 12 months")
                elif command_args[:1] == ["sync_dom_natal_editions_qa"]:
                    allowed_runs = {
                        ("--lookback-months", "1", "--max-new-total", "1"),
                        ("--lookback-months", "1", "--max-new-total", "1", "--apply"),
                        ("--lookback-months", "2", "--max-new-total", "1"),
                        ("--lookback-months", "2", "--max-new-total", "1", "--apply"),
                    }
                    options = tuple(command_args[1:])
                    if options not in allowed_runs:
                        applying = options[-1:] == ("--apply",)
                        bounded = options[:-1] if applying else options
                        if (
                            len(bounded) != 6
                            or bounded[:5]
                            != (
                                "--lookback-months",
                                "1",
                                "--max-new-total",
                                "1",
                                "--as-of",
                            )
                        ):
                            raise ValueError(
                                "DOM QA sync is limited to one month and at most one edition per run"
                            )
                        try:
                            as_of = date.fromisoformat(bounded[5])
                        except ValueError as exc:
                            raise ValueError(
                                "historical DOM QA date must use YYYY-MM-DD"
                            ) from exc
                        today = date.today()
                        if as_of > today or as_of < today - timedelta(days=366):
                            raise ValueError(
                                "historical DOM QA date must be within the last 366 days"
                            )
                elif command_args[:1] == ["repair_dom_edition_blob_qa"]:
                    options = command_args[1:]
                    applying = options[-1:] == ["--apply"]
                    bounded = options[:-1] if applying else options
                    if len(bounded) != 6 or bounded[::2] != [
                        "--year", "--month", "--edition-number"
                    ]:
                        raise ValueError(
                            "DOM blob repair accepts exactly one year/month/edition number"
                        )
                    try:
                        repair_year, repair_month, edition_number = map(
                            int, (bounded[1], bounded[3], bounded[5])
                        )
                    except ValueError as exc:
                        raise ValueError("DOM blob repair identifiers must be integers") from exc
                    today = date.today()
                    if (
                        repair_year not in {today.year - 1, today.year}
                        or not 1 <= repair_month <= 12
                        or not 1 <= edition_number <= 100_000
                    ):
                        raise ValueError("DOM blob repair target is outside the QA allowlist")
                elif command_args[:1] == ["inspect_dom_gazette_boundaries_qa"]:
                    options = command_args[1:]
                    if len(options) % 2:
                        raise ValueError("DOM boundary inspection options require values")
                    parsed = {}
                    allowed_flags = {
                        "--year", "--month", "--edition-number", "--kind", "--max-pages"
                    }
                    for index in range(0, len(options), 2):
                        flag, value = options[index : index + 2]
                        if flag not in allowed_flags or flag in parsed:
                            raise ValueError("DOM boundary inspection option is not on the QA allowlist")
                        parsed[flag] = value
                    if not {"--year", "--month", "--edition-number", "--kind"}.issubset(parsed):
                        raise ValueError("DOM boundary inspection requires an explicit edition identity")
                    numeric_limits = {
                        "--year": (2001, 2100),
                        "--month": (1, 12),
                        "--edition-number": (1, 99_999_999),
                        "--max-pages": (1, 500),
                    }
                    for flag, (minimum, maximum) in numeric_limits.items():
                        if flag not in parsed:
                            continue
                        value = parsed[flag]
                        if not value.isdecimal() or not minimum <= int(value) <= maximum:
                            raise ValueError(f"{flag} is outside the bounded QA range")
                    if parsed["--kind"] not in {"regular", "special"}:
                        raise ValueError("DOM edition kind must be regular or special")
                elif command_args[:1] == ["import_normative_archive"]:
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
                elif command_args[:1] == ["provision_pgm_qa_reviewer"]:
                    options = command_args[1:]
                    if options not in ([], ["--disable"]):
                        if (
                            len(options) not in {2, 3, 4}
                            or options[:1] != ["--username"]
                            or not re.fullmatch(
                                r"jurix-pgm-preview-[0-9a-f]{8}", options[1]
                            )
                            or options[2:] not in (
                                [],
                                ["--disable"],
                                ["--include-pending-relations"],
                                ["--include-pending-relations", "--disable"],
                            )
                        ):
                            raise ValueError(
                                "QA preview reviewer accepts only a generated username, "
                                "optional pending-relations scope, and optional --disable"
                            )
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
                elif command_args[:1] == ["extract_archive_candidate_qa"]:
                    options = command_args[1:]
                    allowed_flags = {
                        "--document-id", "--max-pages", "--max-ocr-pages", "--ocr-timeout-seconds",
                        "--ocr-page",
                    }
                    if len(options) % 2 or any(
                        options[index] not in allowed_flags for index in range(0, len(options), 2)
                    ):
                        raise ValueError("single-document QA extraction received unsupported flags")
                    parsed = dict(zip(options[::2], options[1::2], strict=True))
                    if len(parsed) != len(options) // 2:
                        raise ValueError("single-document QA extraction flags cannot be repeated")
                    if options.count("--document-id") != 1:
                        raise ValueError("single-document QA extraction requires one --document-id")
                    try:
                        uuid.UUID(parsed["--document-id"])
                    except ValueError as exc:
                        raise ValueError("--document-id must be a valid UUID") from exc
                    try:
                        max_ocr_pages = int(parsed.get("--max-ocr-pages", "0"))
                        ocr_timeout = int(parsed.get("--ocr-timeout-seconds", "15"))
                    except ValueError as exc:
                        raise ValueError("OCR limits must be integers") from exc
                    if not 0 <= max_ocr_pages <= 10:
                        raise ValueError("single-document QA extraction OCR page cap must be 0–10")
                    if not 1 <= ocr_timeout <= 30:
                        raise ValueError("single-document QA extraction OCR timeout must be 1–30 seconds")
                    if "--ocr-page" in parsed:
                        if (
                            parsed.get("--document-id") != "cb810b42-ecea-4cbc-870a-b2581c30df6c"
                            or parsed.get("--ocr-page") != "7"
                            or max_ocr_pages != 1
                        ):
                            raise ValueError(
                                "explicit OCR is restricted to page 7 of the LC 271/2025 QA PDF"
                            )
                elif command_args[:1] == ["stage_sapl_normative_candidate_qa"]:
                    allowed_staging = {
                        ("--sapl-id", sapl_id)
                        for sapl_id in ("9406", "1160", "4052", "8823", "925", "254", "3666", "6817")
                    } | {
                        ("--sapl-id", sapl_id, "--apply")
                        for sapl_id in ("9406", "1160", "4052", "8823", "925", "254", "3666", "6817")
                    } | {
                        ("--sapl-id", sapl_id, "--inspect-existing")
                        for sapl_id in ("9406", "4052", "1160", "254")
                    }
                    if tuple(command_args[1:]) not in allowed_staging:
                        raise ValueError(
                            "SAPL candidate staging is restricted to the exact QA allowlist"
                        )
                elif command_args[:1] == ["extract_lc_chain_relation_candidates_qa"]:
                    options = command_args[1:]
                    allowed_flags = {"--extraction-id", "--source-article", "--apply"}
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("LC chain relation extraction received unsupported flags")
                    if options.count("--apply") > 1 or options.count("--extraction-id") not in {1, 2}:
                        raise ValueError("LC chain relation extraction accepts one or two exact IDs")
                    if options.count("--source-article") > 1:
                        raise ValueError("source article filter cannot be repeated")
                    if "--apply" in options and options[-1] != "--apply":
                        raise ValueError("LC chain relation apply flag must be final")
                    if any(
                        index + 1 >= len(options) or options[index + 1].startswith("--")
                        for index, item in enumerate(options)
                        if item in {"--extraction-id", "--source-article"}
                    ):
                        raise ValueError("LC chain extraction options require one value")
                    ids = [
                        options[index + 1]
                        for index, item in enumerate(options[:-1])
                        if item == "--extraction-id"
                    ]
                    if len(ids) != options.count("--extraction-id") or any(
                        value not in {"1391", "6920", "7114", "7115", "7135", "7141", "7144", "7149", "7150", "7151"} for value in ids
                    ):
                        raise ValueError("LC chain relation extraction is restricted to exact QA IDs")
                    if len(set(ids)) != len(ids):
                        raise ValueError("LC chain extraction IDs cannot be duplicated")
                    if "--source-article" in options:
                        source_article = options[options.index("--source-article") + 1]
                        allowed_source_article = (
                            ids == ["7135"] and source_article == "118"
                        ) or (
                            ids in (["7114"], ["7115"]) and source_article == "1"
                        ) or (
                                ids in (["7149"], ["7150"], ["7151"], ["6920"])
                            and source_article in {"1", "2", "3", "5"}
                        ) or (ids == ["7141"] and source_article == "261") or (
                            ids == ["1391"] and source_article == "260"
                        )
                        if not allowed_source_article:
                            raise ValueError(
                                "source article extraction is restricted to the exact allowlisted QA act and article"
                            )
                elif command_args[:1] == ["extract_sapl_normative_candidate_qa"]:
                    options = command_args[1:]
                    allowed_flags = {
                        "--document-id", "--max-pages", "--max-ocr-pages", "--ocr-timeout-seconds",
                    }
                    if len(options) % 2 or any(
                        options[index] not in allowed_flags for index in range(0, len(options), 2)
                    ):
                        raise ValueError("SAPL candidate extraction received unsupported flags")
                    parsed = dict(zip(options[::2], options[1::2], strict=True))
                    if len(parsed) != len(options) // 2 or "--document-id" not in parsed:
                        raise ValueError("SAPL candidate extraction requires one document UUID")
                    try:
                        uuid.UUID(parsed["--document-id"])
                        max_pages = int(parsed.get("--max-pages", "400"))
                        max_ocr_pages = int(parsed.get("--max-ocr-pages", "0"))
                        ocr_timeout = int(parsed.get("--ocr-timeout-seconds", "15"))
                    except ValueError as exc:
                        raise ValueError("SAPL candidate extraction parameters are invalid") from exc
                    if parsed["--document-id"] not in {
                        "be73504c-64c1-4ced-b430-319679f5af8a",
                        "00c841d2-4b08-42a3-80b1-f018b1e86d43",
                        "396947b8-5153-43cc-83c9-59a7849bf761",
                        "a2334a00-772f-4b38-9153-c88ba13ebe5b",
                        "fe950bad-c738-4404-822b-2214f802f236",
                        "f08cb4c6-41e8-4332-8c4f-2a764ca2f6a6",
                        "4f246b2d-6c49-4c70-9014-5c255f969242",
                    }:
                        raise ValueError("SAPL candidate extraction is restricted to the promulgated QA allowlist")
                    if not 1 <= max_pages <= 500 or not 0 <= max_ocr_pages <= 10 or not 1 <= ocr_timeout <= 30:
                        raise ValueError("SAPL candidate extraction exceeds its bounded QA limits")
                elif command_args[:1] == ["extract_lc261_unlinked_candidate_qa"]:
                    if command_args[1:]:
                        raise ValueError("LC 261 unlinked extraction accepts no arguments")
                elif command_args[:1] == ["resume_archive_ocr_qa"]:
                    options = command_args[1:]
                    allowed_flags = {
                        "--document-id", "--batch-pages", "--dry-run", "--apply",
                        "--pages",
                        "--pick-next", "--pick-unreadable", "--pick-blank", "--retry-unreadable",
                        "--reclassify-blank",
                    }
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("archive OCR resume received an unsupported flag")
                    if options.count("--dry-run") + options.count("--apply") != 1:
                        raise ValueError("archive OCR resume requires exactly one of --dry-run or --apply")
                    selectors = (
                        options.count("--document-id")
                        + options.count("--pick-next")
                        + options.count("--pick-unreadable")
                        + options.count("--pick-blank")
                    )
                    if selectors != 1:
                        raise ValueError("archive OCR resume requires exactly one document selector")
                    if (
                        options.count("--batch-pages") > 1
                        or options.count("--pick-next") > 1
                        or options.count("--pick-unreadable") > 1
                        or options.count("--pick-blank") > 1
                        or options.count("--pages") > 1
                        or options.count("--retry-unreadable") > 1
                    ):
                        raise ValueError("archive OCR resume options must not be repeated")
                    if {"--pick-next", "--pick-unreadable", "--pick-blank"}.intersection(options) and "--apply" in options:
                        raise ValueError("archive OCR pick selectors are read-only and require --dry-run")
                    if "--pick-next" in options and "--retry-unreadable" in options:
                        raise ValueError("archive OCR --pick-next cannot select unreadable pages")
                    if "--pick-unreadable" in options and "--retry-unreadable" in options:
                        raise ValueError("archive OCR --pick-unreadable already selects unreadable pages")
                    if "--pick-blank" in options and (
                        "--document-id" in options
                        or "--retry-unreadable" in options
                        or "--reclassify-blank" in options
                    ):
                        raise ValueError("archive OCR --pick-blank must be a standalone dry-run selector")
                    if "--reclassify-blank" in options and (
                        "--document-id" not in options
                        or {"--pick-next", "--pick-unreadable", "--pick-blank", "--retry-unreadable"}.intersection(options)
                    ):
                        raise ValueError("blank-page reclassification requires one explicit document and no retry selector")
                    if "--pages" in options:
                        pages_index = options.index("--pages")
                        if "--document-id" not in options or (
                            {"--pick-next", "--pick-unreadable", "--pick-blank", "--reclassify-blank"}
                            .intersection(options)
                        ):
                            raise ValueError(
                                "explicit OCR pages require one document and cannot combine with batch or blank-reclassification selectors"
                            )
                        page_tokens = []
                        for token in options[pages_index + 1 :]:
                            if token.startswith("--"):
                                break
                            page_tokens.append(token)
                        if not 1 <= len(page_tokens) <= 10 or any(not token.isdecimal() for token in page_tokens):
                            raise ValueError("explicit OCR pages must contain 1–10 positive integers")
                        if len(set(page_tokens)) != len(page_tokens) or any(int(token) < 1 for token in page_tokens):
                            raise ValueError("explicit OCR page numbers must be positive and unique")
                        batch_pages = 10
                        if "--batch-pages" in options:
                            batch_index = options.index("--batch-pages")
                            if batch_index + 1 >= len(options) or not options[batch_index + 1].isdecimal():
                                raise ValueError("archive OCR resume requires an integer batch size")
                            batch_pages = int(options[batch_index + 1])
                        if len(page_tokens) > batch_pages:
                            raise ValueError("explicit OCR page count cannot exceed --batch-pages")
                    if "--document-id" in options:
                        document_index = options.index("--document-id")
                        if document_index + 1 >= len(options):
                            raise ValueError("archive OCR resume requires a document UUID")
                        try:
                            uuid.UUID(options[document_index + 1])
                        except ValueError as exc:
                            raise ValueError("--document-id must be a valid UUID") from exc
                    if "--batch-pages" in options:
                        batch_index = options.index("--batch-pages")
                        if batch_index + 1 >= len(options) or not options[batch_index + 1].isdecimal():
                            raise ValueError("archive OCR resume requires an integer batch size")
                        if not 1 <= int(options[batch_index + 1]) <= 10:
                            raise ValueError("archive OCR resume batch size must be between 1 and 10")
                elif command_args[:1] == ["extract_archive_candidates_batch_qa"]:
                    options = command_args[1:]
                    allowed_flags = {
                        "--dry-run", "--apply", "--batch-size", "--resume",
                        "--publication-order", "--all-publication-order", "--new-snapshot",
                    }
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("archive batch extraction received an unsupported flag")
                    if options.count("--apply") + options.count("--dry-run") != 1:
                        raise ValueError("archive batch extraction requires exactly one of --apply or --dry-run")
                    if (
                        options.count("--resume") > 1
                        or options.count("--batch-size") > 1
                        or options.count("--publication-order") > 1
                        or options.count("--all-publication-order") > 1
                        or options.count("--new-snapshot") > 1
                    ):
                        raise ValueError("archive batch extraction options must not be repeated")
                    if {"--publication-order", "--all-publication-order"}.issubset(options):
                        raise ValueError("archive batch extraction ordering modes are mutually exclusive")
                    if "--new-snapshot" in options and "--all-publication-order" not in options:
                        raise ValueError("archive batch extraction --new-snapshot requires --all-publication-order")
                    if "--resume" in options and not ({"--apply", "--dry-run"} & set(options)):
                        raise ValueError("archive batch extraction --resume requires --apply or --dry-run")
                    if "--batch-size" in options:
                        index = options.index("--batch-size")
                        if index + 1 >= len(options) or not options[index + 1].isdecimal():
                            raise ValueError("archive batch extraction requires an integer batch size")
                        if not 1 <= int(options[index + 1]) <= 10:
                            raise ValueError("archive batch extraction batch size must be between 1 and 10")
                elif command_args[:1] == ["extract_archive_relation_candidates_qa"]:
                    options = command_args[1:]
                    allowed_flags = {
                        "--dry-run", "--apply", "--batch-size", "--max-batches", "--resume"
                    }
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("archive relation extraction received an unsupported flag")
                    if options.count("--apply") + options.count("--dry-run") != 1:
                        raise ValueError("archive relation extraction requires exactly one mode")
                    if any(options.count(flag) > 1 for flag in (
                        "--resume", "--batch-size", "--max-batches"
                    )):
                        raise ValueError("archive relation extraction options must not be repeated")
                    for flag in ("--batch-size", "--max-batches"):
                        if flag not in options:
                            continue
                        index = options.index(flag)
                        if index + 1 >= len(options) or not options[index + 1].isdecimal():
                            raise ValueError("archive relation extraction requires integer batch limits")
                        if not 1 <= int(options[index + 1]) <= 10:
                            raise ValueError("archive relation extraction batch limits must be between 1 and 10")
                elif command_args[:1] == ["inspect_archive_relation_target_coverage_qa"]:
                    if command_args != ["inspect_archive_relation_target_coverage_qa"]:
                        raise ValueError("archive relation target coverage inspection accepts no options")
                elif command_args[:1] == ["inspect_ctm_article20_timeline_qa"]:
                    if command_args != ["inspect_ctm_article20_timeline_qa"]:
                        raise ValueError("CTM Art. 20 timeline inspection accepts no options")
                elif command_args[:1] == ["inspect_pgm_demo_readiness_qa"]:
                    if command_args != ["inspect_pgm_demo_readiness_qa"]:
                        raise ValueError("PGM demo readiness inspection accepts no options")
                elif command_args[:1] == ["adopt_ai_pilot_review_qa"]:
                    expected_package = Path(
                        r"L:\temp\jurix-document-review-20261018\package-v2"
                    ).resolve()
                    if command_args != [
                        "adopt_ai_pilot_review_qa",
                        "--package-root",
                        str(expected_package),
                    ]:
                        raise ValueError(
                            "AI pilot adoption import is restricted to the frozen, hash-pinned review package"
                        )
                elif command_args[:1] == ["restore_missing_archive_blobs_qa"]:
                    options = command_args[1:]
                    allowed_flags = {"--archive", "--manifest", "--limit", "--dry-run", "--apply"}
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("archive blob restore received an unsupported flag")
                    if options.count("--dry-run") + options.count("--apply") != 1:
                        raise ValueError("archive blob restore requires exactly one mode")
                    if "--apply" in options:
                        raise ValueError(
                            "host QA runner cannot restore blobs: its TEMP storage may differ from the Docker volume"
                        )
                    for required in ("--archive", "--manifest"):
                        if options.count(required) != 1:
                            raise ValueError("archive blob restore requires one archive and manifest path")
                        index = options.index(required)
                        if index + 1 >= len(options):
                            raise ValueError("archive blob restore path is missing")
                    archive_path = Path(options[options.index("--archive") + 1]).resolve()
                    manifest_path = Path(options[options.index("--manifest") + 1]).resolve()
                    qa_root_value = os.environ.get("JURIX_QA_ROOT")
                    if not qa_root_value:
                        raise ValueError("archive blob restore requires JURIX_QA_ROOT")
                    qa_root = Path(qa_root_value).resolve()
                    if not manifest_path.is_relative_to(qa_root) or manifest_path == qa_root:
                        raise ValueError("archive blob restore manifest must stay inside JURIX_QA_ROOT")
                    if archive_path.is_relative_to(qa_root):
                        raise ValueError("archive blob restore source ZIP must be outside JURIX_QA_ROOT")
                    if "--limit" in options:
                        if options.count("--limit") != 1:
                            raise ValueError("archive blob restore limit must not be repeated")
                        index = options.index("--limit")
                        if index + 1 >= len(options) or not options[index + 1].isdecimal():
                            raise ValueError("archive blob restore limit must be an integer")
                        if not 1 <= int(options[index + 1]) <= 10:
                            raise ValueError("archive blob restore limit must be between 1 and 10")
                elif command_args[:1] == ["inspect_archive_extraction_coverage_qa"]:
                    if command_args != ["inspect_archive_extraction_coverage_qa"]:
                        raise ValueError("archive extraction coverage inspection accepts no options")
                elif command_args == ["diagnose_archive_transition_retrieval_qa"]:
                    # Read-only, fixed-scenario trace of title-based transition
                    # retrieval against the isolated QA archive. It emits only
                    # act identity, article labels, extraction status and
                    # predicate matches—not extracted legal text or file paths.
                    pass
                elif command_args[:1] == ["stage_lc55_official_candidate_qa"]:
                    options = command_args[1:]
                    if "--pdf-path" not in options:
                        raise ValueError("LC 55 candidate staging requires --pdf-path")
                    if any(item.startswith("--") and item not in {"--pdf-path", "--apply"} for item in options):
                        raise ValueError("LC 55 candidate staging accepts only --pdf-path and --apply")
                    if options.count("--apply") > 1 or options.count("--pdf-path") != 1:
                        raise ValueError("LC 55 candidate staging flags are invalid")
                    path_index = options.index("--pdf-path")
                    if path_index + 1 >= len(options) or options[path_index + 1].startswith("--"):
                        raise ValueError("--pdf-path requires a value")
                    pdf_path = Path(options[path_index + 1]).resolve()
                    qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                    allowed_root = (qa_root / "evidence" / "lc55-2004").resolve()
                    if not pdf_path.is_relative_to(allowed_root) or pdf_path.name != "lc55-codigo-obras-consolidado-julho-2019.pdf":
                        raise ValueError("LC 55 PDF must stay in its exact QA evidence directory")
                elif command_args[:1] == ["stage_lc55_original_candidate_qa"]:
                    expected_pdf = "/app/data/normative-qa/evidence/lc55-2004/lc55-original-2004.pdf"
                    if command_args[1:] not in (["--pdf-path", expected_pdf], ["--pdf-path", expected_pdf, "--apply"]):
                        raise ValueError("LC 55 original staging is restricted to its fixed QA evidence PDF")
                elif command_args[:1] == ["stage_lc208_unlinked_sapl_candidate_qa"]:
                    if command_args[1:] not in ([], ["--apply"]):
                        raise ValueError("LC 208 unlinked staging accepts only optional --apply")
                elif command_args[:1] == ["stage_lc261_unlinked_sapl_candidate_qa"]:
                    if command_args[1:] not in ([], ["--apply"]):
                        raise ValueError("LC 261 unlinked staging accepts only optional --apply")
                elif command_args[:1] == ["stage_bvn_4566_1992_candidate_qa"]:
                    options = command_args[1:]
                    if "--pdf-path" not in options or options.count("--pdf-path") != 1:
                        raise ValueError("BVN 4.566/1992 staging requires one --pdf-path")
                    if any(item.startswith("--") and item not in {"--pdf-path", "--apply"} for item in options):
                        raise ValueError("BVN 4.566/1992 staging accepts only --pdf-path and --apply")
                    if options.count("--apply") > 1:
                        raise ValueError("BVN 4.566/1992 staging accepts --apply at most once")
                    path_index = options.index("--pdf-path")
                    if path_index + 1 >= len(options) or options[path_index + 1].startswith("--"):
                        raise ValueError("--pdf-path requires a value")
                    pdf_path = Path(options[path_index + 1]).resolve()
                    qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                    allowed_root = (qa_root / "evidence" / "lc258-4566-1992").resolve()
                    if not pdf_path.is_relative_to(allowed_root) or pdf_path.name != "lei_4.566.pdf":
                        raise ValueError("BVN PDF must stay in its exact QA evidence directory")
                elif command_args[:1] == ["stage_lp275_2009_candidate_qa"]:
                    options = command_args[1:]
                    if "--pdf-path" not in options or options.count("--pdf-path") != 1:
                        raise ValueError("LP 275/2009 staging requires one --pdf-path")
                    if options.count("--apply") > 1 or any(
                        item.startswith("--") and item not in {"--pdf-path", "--apply"}
                        for item in options
                    ):
                        raise ValueError("LP staging accepts only --pdf-path and --apply")
                    path_index = options.index("--pdf-path")
                    if path_index + 1 >= len(options) or options[path_index + 1].startswith("--"):
                        raise ValueError("LP --pdf-path requires a value")
                    pdf_path = Path(options[path_index + 1]).resolve()
                    qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                    allowed_root = (qa_root / "evidence" / "lp275-2009").resolve()
                    if (
                        not pdf_path.is_relative_to(allowed_root)
                        or pdf_path.name != "lei-promulgada-0275-2009-oficial.pdf"
                    ):
                        raise ValueError("LP PDF must stay in its exact QA evidence directory")
                elif command_args[:1] == ["stage_ctm_3882_consolidation_qa"]:
                    options = command_args[1:]
                    if "--pdf-path" not in options:
                        raise ValueError("CTM consolidation staging requires --pdf-path")
                    if any(
                        item.startswith("--") and item not in {"--pdf-path", "--apply"}
                        for item in options
                    ):
                        raise ValueError("CTM staging accepts only --pdf-path and --apply")
                    if options.count("--apply") > 1 or options.count("--pdf-path") != 1:
                        raise ValueError("CTM staging flags are invalid")
                    path_index = options.index("--pdf-path")
                    if path_index + 1 >= len(options) or options[path_index + 1].startswith("--"):
                        raise ValueError("--pdf-path requires a value")
                    pdf_path = Path(options[path_index + 1]).resolve()
                    qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                    allowed_root = (qa_root / "evidence" / "ctm-3882-1989").resolve()
                    if (
                        not pdf_path.is_relative_to(allowed_root)
                        or pdf_path.name not in {
                            "lei3882-1989-consolidado-exercicio-2021.pdf",
                            "lei3882-1989-consolidado-exercicio-2022.pdf",
                            "lei3882-1989-consolidado-exercicio-2024.pdf",
                        }
                    ):
                        raise ValueError("CTM PDF must stay in its exact QA evidence directory")
                elif command_args[:1] == ["stage_lc271_ctm_amendment_qa"]:
                    options = command_args[1:]
                    if "--pdf-path" not in options or options.count("--pdf-path") != 1:
                        raise ValueError("LC 271 staging requires one exact PDF path")
                    if options.count("--apply") > 1 or any(
                        item.startswith("--") and item not in {"--pdf-path", "--apply"}
                        for item in options
                    ):
                        raise ValueError("LC 271 staging accepts only --pdf-path and --apply")
                    path_index = options.index("--pdf-path")
                    if path_index + 1 >= len(options) or options[path_index + 1].startswith("--"):
                        raise ValueError("LC 271 --pdf-path requires a value")
                    pdf_path = Path(options[path_index + 1]).resolve()
                    qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                    allowed_root = (qa_root / "evidence" / "lc-271-2025").resolve()
                    if (
                        not pdf_path.is_relative_to(allowed_root)
                        or pdf_path.name != "lei_complementar_no_271_2025.pdf"
                    ):
                        raise ValueError("LC 271 PDF must stay in its exact QA evidence directory")
                elif command_args[:1] == ["inspect_archive_candidate_retrieval_qa"]:
                    options = command_args[1:]
                    expected_queries = {
                        (
                            "f4a5c8f6-7ca2-4b5c-935e-033572a33510",
                            "Quais critérios de elegibilidade e limites de acumulação devo verificar para a Gratificação de Vigilância Sanitária de um servidor da saúde? Responda em poucas frases com base nos PDFs recuperados e diga o que a documentação não comprova.",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "O que dispõe o Art. 262 da Lei Complementar nº 258/2024?",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "Quais exigências de acessibilidade para edificações aparecem no Código de Obras de Natal? Resuma apenas o que os dispositivos recuperados dizem, cite cada artigo e explique o que ainda não se pode concluir sobre uma obra específica.",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "Na triagem de uma obra municipal, quais dispositivos da LC nº 258/2024 tratam do objeto do Código, de complementações ou notificações e de processos antigos sem despacho? Explique em poucas frases as regras distintas, cite cada artigo e diga o que um PDF extraído e pendente não confirma sobre aplicação ao caso e alterações posteriores.",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "Para um processo de licenciamento municipal, posso citar o Art. 59 da Lei Complementar nº 258/2024 como redação atual? Verifique se houve alteração posterior do dispositivo e diferencie lei aprovada de proposição em tramitação.",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "Resuma a relação entre o Art. 262 (regra transitória) e o Art. 266 (vigência) da Lei Complementar nº 258/2024. Cite os dois dispositivos separadamente e não calcule a data em calendário.",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "E qual artigo define a data de entrada em vigor? (contexto normativo: Lei Complementar nº 258/2024)",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "E quando a lei passou a vigorar? (contexto normativo: Lei Complementar nº 258/2024)",
                        ),
                        (
                            "eaa13513-6cfc-4edf-8027-c6a7cc6d70b7",
                            "Em que data entrou em vigor? (contexto normativo: Lei Complementar nº 258/2024)",
                        ),
                        (
                            "cb810b42-ecea-4cbc-870a-b2581c30df6c",
                            "O que prevê o Art. 1º da Lei Complementar nº 271/2025?",
                        ),
                        (
                            "cb810b42-ecea-4cbc-870a-b2581c30df6c",
                            "Compare o texto do Art. 20 da Lei nº 3.882/1989 na consolidação municipal de 2024 com a redação substitutiva transcrita no Art. 1º da LC nº 271/2025. Mostre apenas as fontes e diferenças textuais, sem concluir vigência atual.",
                        ),
                        (
                            "6b025442-7977-4f27-96f2-2318d2c714be",
                            "O que dispõe o Art. 21 da Lei Complementar nº 55/2004?",
                        ),
                        (
                            "6b025442-7977-4f27-96f2-2318d2c714be",
                            "Em um processo protocolado antes da entrada em vigor da LC 258/2024 e ainda sem despacho decisório, como devo verificar se a regra do Art. 21 da LC 55/2004 ainda pode ser aplicada? Considere também o Art. 260, IV, e o Art. 262 da LC 258/2024. Separe o que os PDFs comprovam do que permanece inconclusivo.",
                        ),
                        (
                            "6b025442-7977-4f27-96f2-2318d2c714be",
                            "Em uma fundamentação hipotética, foi citado o art. 21 da Lei Complementar nº 55/2004. O que o art. 260, inciso IV, da LC nº 258/2024 diz sobre essa lei, e as fontes disponíveis permitem afirmar qual redação do art. 21 estava vigente em 2024?",
                        ),
                        (
                            "c452bfe5-1138-4962-a3f2-c4cc9b662007",
                            "A Lei Complementar nº 258/2024, Art. 260, inciso V, revoga expressamente o Art. 21 da Lei Promulgada nº 275/2009? O que os documentos disponíveis permitem afirmar e o que permanece pendente de confirmação jurídica?",
                        ),
                        (
                            "9ab26a81-3747-4b4e-b1a0-64b2e86e0530",
                            "O que foi alterado e revogado pela Lei Complementar nº 219/2023?",
                        ),
                        (
                            "f4a5c8f6-7ca2-4b5c-935e-033572a33510",
                            "A Lei Complementar Municipal nº 120/2010, Art. 18, foi alterada ou revogada? Compare a redação original e a atual, diga o que o acervo permite afirmar e cite as fontes.",
                        ),
                    }
                    generate = options[-1:] == ["--generate"]
                    query_options = options[:-1] if generate else options
                    if len(query_options) != 4 or query_options[0] != "--document-id" or query_options[2] != "--question":
                        raise ValueError("retrieval diagnosis requires one approved candidate and question")
                    query = (query_options[1], query_options[3])
                    if query not in expected_queries:
                        raise ValueError("retrieval diagnosis is restricted to the authorized public QA candidates and exact questions")
                    live_generation_queries = {
                        (
                            "6b025442-7977-4f27-96f2-2318d2c714be",
                            "Em um processo protocolado antes da entrada em vigor da LC 258/2024 e ainda sem despacho decisório, como devo verificar se a regra do Art. 21 da LC 55/2004 ainda pode ser aplicada? Considere também o Art. 260, IV, e o Art. 262 da LC 258/2024. Separe o que os PDFs comprovam do que permanece inconclusivo.",
                        ),
                        (
                            "c452bfe5-1138-4962-a3f2-c4cc9b662007",
                            "A Lei Complementar nº 258/2024, Art. 260, inciso V, revoga expressamente o Art. 21 da Lei Promulgada nº 275/2009? O que os documentos disponíveis permitem afirmar e o que permanece pendente de confirmação jurídica?",
                        ),
                        (
                            "cb810b42-ecea-4cbc-870a-b2581c30df6c",
                            "Compare o texto do Art. 20 da Lei nº 3.882/1989 na consolidação municipal de 2024 com a redação substitutiva transcrita no Art. 1º da LC nº 271/2025. Mostre apenas as fontes e diferenças textuais, sem concluir vigência atual.",
                        ),
                    }
                    if generate and query not in live_generation_queries:
                        raise ValueError("live generation is restricted to the exact public PGM QA scenario")
                elif command_args[:1] == ["build_pgm_pilot_qa"]:
                    if command_args[1:] not in ([], ["--fetch-missing"]):
                        raise ValueError("pilot build only accepts its fixed source selection in isolated QA")
                elif command_args[:1] == ["reconcile_targets"]:
                    if command_args[1:] not in (
                        ["--dry-run", "--limit", "50000"],
                        ["--dry-run", "--limit", "50000", "--details"],
                    ):
                        raise ValueError(
                            "QA target reconciliation is restricted to a read-only dry-run capped at 50000 events; details are sanitized"
                        )
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
        elif args == ["scripts/profile_archive_search_qa.py"]:
            # Fixed public thematic query; the profiler enforces a read-only
            # transaction and emits timing/plan shape without SQL or evidence.
            pass
        elif args[:1] == ["scripts/collect_normative_rag_experiment.py"]:
            allowed_flags = {
                "--cases", "--project-gold", "--output", "--max-cases", "--temperature", "--max-sources",
                "--no-warm-cache",
            }
            options = args[1:]
            if options == ["--help"]:
                pass
            elif any(item.startswith("--") and item not in allowed_flags for item in options):
                raise ValueError("RAG experiment collector received an unsupported flag")
            else:
                has_cases = "--cases" in options
                has_project_gold = "--project-gold" in options
                if has_cases == has_project_gold or "--output" not in options:
                    raise ValueError("RAG collector requires exactly one explicit reference and output")
                reference_flag = "--cases" if has_cases else "--project-gold"
                if options.index(reference_flag) + 1 >= len(options) or options.index("--output") + 1 >= len(options):
                    raise ValueError("RAG experiment reference/output path option has no value")
                reference_path = Path(options[options.index(reference_flag) + 1]).resolve()
                output_path = Path(options[options.index("--output") + 1]).resolve()
                cases_root = (ROOT / "benchmarks" / "corpus" / "municipal_natal").resolve()
                qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
                if not reference_path.is_relative_to(cases_root):
                    raise ValueError("RAG experiment reference must be inside the municipal QA benchmark directory")
                if not output_path.is_relative_to(qa_root) or output_path == qa_root:
                    raise ValueError("RAG experiment output must stay inside JURIX_QA_ROOT")
        elif args[:1] == ["scripts/evaluate_pgm_project_gold_archive.py"]:
            allowed_flags = {"--gold", "--limit", "--output"}
            options = args[1:]
            if any(item.startswith("--") and item not in allowed_flags for item in options):
                raise ValueError("archive gold evaluation received an unsupported flag")
            if options.count("--output") != 1 or options.count("--gold") > 1 or options.count("--limit") > 1:
                raise ValueError("archive gold evaluation requires one output and accepts one gold/limit")
            if "--gold" in options:
                gold_index = options.index("--gold")
                if gold_index + 1 >= len(options):
                    raise ValueError("archive gold --gold requires a value")
                gold_path = Path(options[gold_index + 1]).resolve()
            else:
                gold_path = (ROOT / "benchmarks/corpus/municipal_natal/project-gold.v1.json").resolve()
            expected_gold = (ROOT / "benchmarks/corpus/municipal_natal/project-gold.v1.json").resolve()
            if gold_path != expected_gold:
                raise ValueError("archive gold evaluation accepts only the adopted project gold")
            output_index = options.index("--output")
            if output_index + 1 >= len(options):
                raise ValueError("archive gold --output requires a value")
            output_path = Path(options[output_index + 1]).resolve()
            qa_root = Path(os.environ["JURIX_QA_ROOT"]).resolve()
            if not output_path.is_relative_to(qa_root) or output_path == qa_root:
                raise ValueError("archive gold report output must stay inside JURIX_QA_ROOT")
            if "--limit" in options:
                limit_index = options.index("--limit")
                if limit_index + 1 >= len(options):
                    raise ValueError("archive gold --limit requires a value")
                try:
                    limit = int(options[limit_index + 1])
                except ValueError as exc:
                    raise ValueError("archive gold limit must be an integer") from exc
                if not 1 <= limit <= 48:
                    raise ValueError("archive gold limit must be between 1 and 48")
        elif args[:1] == ["scripts/inventory_normative_archive.py"]:
            if len(args) != 5 or args[1] != "--archive" or args[3] != "--output":
                raise ValueError("inventory command requires --archive and --output only")
        elif args == [
            "scripts/run_qa_sapl_incremental.py",
            "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "1",
        ]:
            # One resumable page from the official Natal SAPL API. The
            # dedicated QA runner pins the database; the script itself
            # rechecks QA settings before it can write catalog metadata.
            pass
        elif args == [
            "scripts/run_qa_sapl_incremental.py",
            "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "4",
            "--metadata-only",
        ]:
            # Exact four-page maximum (40 metadata records) metadata-only SAPL
            # run. The service disables PDF fingerprints/downloads; bounded
            # overlap is needed to certify a safe incremental stop.
            pass
        elif args == [
            "scripts/run_qa_sapl_incremental.py",
            "--repair-checkpoint-page", "--tipo", "1", "--ano", "2026", "--limit", "10",
        ]:
            # Replay only the exact persisted cursor page after the runner
            # validates its scope and local pending-row identity anchors.
            pass
        else:
            raise ValueError("Python script is not on the QA allowlist")
        return [sys.executable, *args]
    if executable in {"npm", "npm.cmd"} and args == ["test", "--prefix", "tests/js"]:
        return ["npm.cmd", *args]
    if executable == "node" and args == ["tests/js/normative-product-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-rag-live-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/pgm-workflow-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/pgm-law8201-dom-source.browser.smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/pgm-sapl-related-matter-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/pgm-article-currentness-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-admin-review.browser.test.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/foundation-check.browser.smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/document-review-candidate.browser.smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-collections.browser.test.mjs"]:
        return ["node.exe", *args]
    raise ValueError("command is not on the QA allowlist")


def _command_environment(env: dict[str, str], command: list[str]) -> dict[str, str]:
    """Scope QA-only credentials and pin read-only SAPL diagnostics to Natal."""
    scoped = env.copy()
    scoped.pop("JURIX_QA_REVIEWER_PASSWORD", None)
    scoped.pop("JURIX_QA_REVIEWER_USERNAME", None)
    parts = command[1:] if command[:1] == ["--"] else command
    if parts == [
        "python", "manage.py", "diagnose_sapl", "--limit", "10", "--max-pages", "4"
    ]:
        scoped["SAPL_BASE_URL"] = "https://sapl.natal.rn.leg.br/api"
    elif parts[:3] == ["python", "manage.py", "audit_archive_sapl_crosswalk_qa"]:
        scoped["SAPL_BASE_URL"] = "https://sapl.natal.rn.leg.br/api"
    elif parts == [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "1",
    ]:
        scoped["SAPL_BASE_URL"] = "https://sapl.natal.rn.leg.br/api"
    elif parts == [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "4",
        "--metadata-only",
    ]:
        scoped["SAPL_BASE_URL"] = "https://sapl.natal.rn.leg.br/api"
    elif parts == [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--repair-checkpoint-page", "--tipo", "1", "--ano", "2026", "--limit", "10",
    ]:
        scoped["SAPL_BASE_URL"] = "https://sapl.natal.rn.leg.br/api"
    elif (
        parts[:2] == ["python", "manage.py"]
        and parts[2:3] == ["seed_normative_qa"]
        and os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
    ):
        scoped["JURIX_QA_REVIEWER_PASSWORD"] = os.environ["JURIX_QA_REVIEWER_PASSWORD"]
    elif (
        parts[:3] == ["python", "manage.py", "provision_pgm_qa_reviewer"]
        and "--disable" not in parts[3:]
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
    elif parts == ["node", "tests/js/foundation-check.browser.smoke.mjs"]:
        password = os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
        username = os.environ.get("JURIX_QA_REVIEWER_USERNAME", "")
        if (
            not password
            or len(password) < 24
            or not re.fullmatch(r"jurix-pgm-preview-[0-9a-f]{8}", username)
        ):
            raise ValueError("authenticated foundation-check browser smoke requires a temporary QA reviewer credential")
        scoped["JURIX_QA_REVIEWER_PASSWORD"] = password
        scoped["JURIX_QA_REVIEWER_USERNAME"] = username
        scoped["JURIX_QA_BASE_URL"] = "http://127.0.0.1:8287"
    elif parts == ["node", "tests/js/document-review-candidate.browser.smoke.mjs"]:
        password = os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
        username = os.environ.get("JURIX_QA_REVIEWER_USERNAME", "")
        if not password or len(password) < 24 or not re.fullmatch(
            r"jurix-pgm-preview-[0-9a-f]{8}", username
        ):
            raise ValueError("candidate-review browser smoke requires a temporary QA reviewer credential")
        scoped["JURIX_QA_REVIEWER_PASSWORD"] = password
        scoped["JURIX_QA_REVIEWER_USERNAME"] = username
        scoped["JURIX_QA_BASE_URL"] = "http://127.0.0.1:8287"
    return scoped


def _container_storage_command(command: list[str]) -> list[str] | None:
    """Run file-backed corpus operations in the app container's QA volume."""
    parts = command[1:] if command[:1] == ["--"] else command
    if (
        parts[:3] == ["python", "manage.py", "extract_archive_candidates_batch_qa"]
        and (
            "--publication-order" in parts
            or "--all-publication-order" in parts
        )
    ):
        # These modes require the host QA archive mirror and host-side SAPL
        # crosswalk checkpoint; standard UUID-order mode stays container-backed.
        return None
    if (
        len(parts) >= 3
        and parts[:3] == ["python", "manage.py", "extract_archive_candidate_qa"]
    ):
        try:
            document_index = parts.index("--document-id", 3)
            document_id = parts[document_index + 1]
        except (ValueError, IndexError):
            document_id = None
        if document_id in HOST_STORAGE_QA_DOCUMENTS:
            return None
    if len(parts) >= 3 and parts[2] == "resume_archive_ocr_qa":
        try:
            document_index = parts.index("--document-id", 3)
            document_id = parts[document_index + 1]
        except (ValueError, IndexError):
            document_id = None
        if document_id in HOST_STORAGE_SAPL_CANDIDATES:
            return None
    if (
        len(parts) < 3
        or parts[0].lower() not in {"python", "python.exe"}
        or parts[1:2] != ["manage.py"]
        or parts[2] not in CONTAINER_STORAGE_COMMANDS
    ):
        return None
    return [
        "docker",
        "compose",
        "-p",
        "jurix-normative-qa",
        "-f",
        str(ROOT / "docker-compose.audit.yml"),
        "exec",
        "-T",
        "web",
        "python",
        "manage.py",
        *parts[2:],
    ]


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
        container_command = _container_storage_command(options.run)
        if container_command is not None:
            command = container_command
        command_env = _command_environment(env, options.run)
        return subprocess.run(command, cwd=ROOT, env=command_env, check=False).returncode
    except (ValueError, OSError) as exc:
        print(f"QA guard: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
