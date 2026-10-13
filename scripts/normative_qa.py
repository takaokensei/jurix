"""Guarded command runner for the isolated normative-graph QA environment."""

from __future__ import annotations

import argparse
import os
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
                elif command_args[:1] == ["check_source_sync_health"]:
                    options = command_args[1:]
                    if len(options) % 2:
                        raise ValueError("source health options require values")
                    parsed = {}
                    for index in range(0, len(options), 2):
                        flag, value = options[index : index + 2]
                        if flag not in {"--source", "--max-age-hours"} or flag in parsed:
                            raise ValueError("source health option is not on the QA allowlist")
                        parsed[flag] = value
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
                    if len(options) != 2 or options[0] != "--document-id":
                        raise ValueError("single-document QA extraction requires one --document-id")
                    try:
                        uuid.UUID(options[1])
                    except ValueError as exc:
                        raise ValueError("--document-id must be a valid UUID") from exc
                elif command_args[:1] == ["resume_archive_ocr_qa"]:
                    options = command_args[1:]
                    allowed_flags = {
                        "--document-id", "--batch-pages", "--dry-run", "--apply",
                        "--pick-next", "--pick-unreadable", "--retry-unreadable",
                        "--reclassify-blank",
                    }
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("archive OCR resume received an unsupported flag")
                    if options.count("--dry-run") + options.count("--apply") != 1:
                        raise ValueError("archive OCR resume requires exactly one of --dry-run or --apply")
                    selectors = options.count("--document-id") + options.count("--pick-next") + options.count("--pick-unreadable")
                    if selectors != 1:
                        raise ValueError("archive OCR resume requires exactly one document selector")
                    if (
                        options.count("--batch-pages") > 1
                        or options.count("--pick-next") > 1
                        or options.count("--pick-unreadable") > 1
                        or options.count("--retry-unreadable") > 1
                    ):
                        raise ValueError("archive OCR resume options must not be repeated")
                    if {"--pick-next", "--pick-unreadable"}.intersection(options) and "--apply" in options:
                        raise ValueError("archive OCR pick selectors are read-only and require --dry-run")
                    if "--pick-next" in options and "--retry-unreadable" in options:
                        raise ValueError("archive OCR --pick-next cannot select unreadable pages")
                    if "--pick-unreadable" in options and "--retry-unreadable" in options:
                        raise ValueError("archive OCR --pick-unreadable already selects unreadable pages")
                    if "--reclassify-blank" in options and (
                        "--document-id" not in options
                        or {"--pick-next", "--pick-unreadable", "--retry-unreadable"}.intersection(options)
                    ):
                        raise ValueError("blank-page reclassification requires one explicit document and no retry selector")
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
                    allowed_flags = {"--dry-run", "--apply", "--batch-size", "--resume"}
                    if any(item.startswith("--") and item not in allowed_flags for item in options):
                        raise ValueError("archive batch extraction received an unsupported flag")
                    if options.count("--apply") + options.count("--dry-run") != 1:
                        raise ValueError("archive batch extraction requires exactly one of --apply or --dry-run")
                    if options.count("--resume") > 1 or options.count("--batch-size") > 1:
                        raise ValueError("archive batch extraction options must not be repeated")
                    if "--resume" in options and not ({"--apply", "--dry-run"} & set(options)):
                        raise ValueError("archive batch extraction --resume requires --apply or --dry-run")
                    if "--batch-size" in options:
                        index = options.index("--batch-size")
                        if index + 1 >= len(options) or not options[index + 1].isdecimal():
                            raise ValueError("archive batch extraction requires an integer batch size")
                        if not 1 <= int(options[index + 1]) <= 10:
                            raise ValueError("archive batch extraction batch size must be between 1 and 10")
                elif command_args[:1] == ["inspect_archive_extraction_coverage_qa"]:
                    if command_args != ["inspect_archive_extraction_coverage_qa"]:
                        raise ValueError("archive extraction coverage inspection accepts no options")
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
                            "9ab26a81-3747-4b4e-b1a0-64b2e86e0530",
                            "O que foi alterado e revogado pela Lei Complementar nº 219/2023?",
                        ),
                        (
                            "f4a5c8f6-7ca2-4b5c-935e-033572a33510",
                            "A Lei Complementar Municipal nº 120/2010, Art. 18, foi alterada ou revogada? Compare a redação original e a atual, diga o que o acervo permite afirmar e cite as fontes.",
                        ),
                    }
                    if len(options) != 4 or options[0] != "--document-id" or options[2] != "--question":
                        raise ValueError("retrieval diagnosis requires one approved candidate and question")
                    if (options[1], options[3]) not in expected_queries:
                        raise ValueError("retrieval diagnosis is restricted to the authorized public QA candidates and exact questions")
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
    if executable == "node" and args == ["tests/js/pgm-sapl-related-matter-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/pgm-article-currentness-smoke.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-admin-review.browser.test.mjs"]:
        return ["node.exe", *args]
    if executable == "node" and args == ["tests/js/normative-collections.browser.test.mjs"]:
        return ["node.exe", *args]
    raise ValueError("command is not on the QA allowlist")


def _command_environment(env: dict[str, str], command: list[str]) -> dict[str, str]:
    """Scope QA-only credentials and pin read-only SAPL diagnostics to Natal."""
    scoped = env.copy()
    scoped.pop("JURIX_QA_REVIEWER_PASSWORD", None)
    parts = command[1:] if command[:1] == ["--"] else command
    if parts == [
        "python", "manage.py", "diagnose_sapl", "--limit", "10", "--max-pages", "4"
    ]:
        scoped["SAPL_BASE_URL"] = "https://sapl.natal.rn.leg.br/api"
    elif parts == [
        "python", "scripts/run_qa_sapl_incremental.py",
        "--tipo", "1", "--ano", "2026", "--limit", "10", "--max-pages", "1",
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
