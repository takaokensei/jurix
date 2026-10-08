from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

from src.apps.ingestion.management.commands.diagnose_qa_archive_overview import (
    _answer_shape_metrics,
    _validation_shape_metrics,
)

MODULE_PATH = Path(__file__).resolve().parents[2] / "scripts" / "normative_qa.py"
SPEC = importlib.util.spec_from_file_location("normative_qa_helper", MODULE_PATH)
qa = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(qa)


def test_accepts_only_dedicated_audit_targets():
    qa._validate_target(qa.DATABASE_URL, qa.REDIS_URL, qa.CACHE_REDIS_URL)


def test_qa_runner_allows_only_the_fixed_normative_api_benchmark_command():
    command = ["python", "scripts/benchmark_normative_api_qa.py"]
    assert qa._allowed_command(command) == [
        qa.sys.executable,
        "scripts/benchmark_normative_api_qa.py",
    ]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["--database", "production"])


def test_qa_runner_confines_archive_overview_diagnostic_to_qa_output(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    output = str(qa_root / "overview-metrics.json")
    command = ["python", "manage.py", "diagnose_qa_archive_overview", "--output", output]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="output must stay"):
        qa._allowed_command(
            ["python", "manage.py", "diagnose_qa_archive_overview", "--output", str(tmp_path / "outside.json")]
        )
    with pytest.raises(ValueError, match="exactly one"):
        qa._allowed_command(command + ["--model", "other"])


def test_archive_diagnostic_records_only_grounding_shape_not_claim_text():
    metrics = _validation_shape_metrics(
        {
            "grounded": False,
            "source_only": True,
            "grounding": {
                "score": 0.5,
                "claims": [
                    {
                        "claim": "segredo jurídico [[1]]",
                        "supported": False,
                        "evidence": [],
                        "rejected_matches": [
                            {
                                "lexical_overlap": 0.4,
                                "lexical_ok": False,
                                "numeric_ok": True,
                                "negation_ok": True,
                                "citation_ok": True,
                                "certainty_ok": True,
                            }
                        ],
                    },
                    {
                        "claim": "outra afirmação [[2]]",
                        "supported": False,
                        "evidence": [],
                        "rejected_matches": [
                            {
                                "lexical_overlap": 0.8,
                                "lexical_ok": True,
                                "numeric_ok": False,
                                "negation_ok": True,
                                "citation_ok": True,
                                "certainty_ok": True,
                            }
                        ],
                    },
                    {"claim": "claim sem citação", "supported": False, "evidence": []},
                    {"claim": "afirmação aceita [[1]]", "supported": True, "evidence": [{"id": 1}]},
                ],
                "failed_claims": ["segredo jurídico", "outra afirmação", "claim sem citação"],
            },
        },
        sources=[
            {"citation_index": 1, "evidence_text": "texto do excerto selecionado"},
            {"citation_index": 2, "evidence_text": ""},
        ],
        answer="Texto jurídico que não deve ser persistido. [[1]]",
    )

    assert metrics["failed_claim_count"] == 3
    assert metrics["failed_claim_records"] == 3
    assert metrics["failed_records_without_evidence"] == 3
    assert metrics["failed_records_with_evidence"] == 0
    assert metrics["failed_records_without_citation_marker"] == 1
    assert metrics["failed_records_citing_unsampled_evidence"] == 1
    assert metrics["failed_records_citing_sampled_evidence_without_match"] == 1
    assert metrics["closest_rejection_failures"] == {
        "lexical": 1,
        "numeric": 1,
        "negation": 0,
        "citation": 0,
        "certainty": 0,
        "no_candidate": 1,
    }
    assert metrics["candidate_answer_shape"]["distinct_citation_marker_count"] == 1
    assert metrics["candidate_answer_shape"]["repeated_citation_marker_count"] == 0
    assert metrics["candidate_answer_shape"]["meets_partial_overview_breadth"] is True
    assert metrics["candidate_answer_shape"]["has_redundant_content_phrase"] is False
    assert "failure_shapes" not in metrics
    assert "segredo jurídico" not in str(metrics)
    assert "Texto jurídico que não deve ser persistido" not in str(metrics)


def test_archive_diagnostic_records_answer_shape_without_answer_text():
    metrics = _answer_shape_metrics(
        "Síntese sobre o tema. [[1]]\n\nA amostra consultada cobre 30 de 39 artigos."
    )

    assert metrics["citation_marker_count"] == 1
    assert metrics["heading_count"] == 0
    assert metrics["paragraph_count"] == 2
    assert metrics["has_partial_coverage_note"] is True
    assert metrics["has_generic_partial_notice"] is False
    assert "Síntese sobre o tema" not in str(metrics)


def test_qa_runner_confines_live_rag_experiment_to_versioned_cases_and_qa_output(
    tmp_path, monkeypatch
):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    cases = "benchmarks/corpus/municipal_natal/rag-experiment-smoke.v1.jsonl"
    output = str(qa_root / "rag-smoke.jsonl")
    command = [
        "python", "scripts/collect_normative_rag_experiment.py",
        "--cases", cases, "--output", output,
    ]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="output must stay"):
        qa._allowed_command(command[:-1] + [str(tmp_path / "outside.jsonl")])
    with pytest.raises(ValueError, match="cases must be inside"):
        qa._allowed_command([
            "python", "scripts/collect_normative_rag_experiment.py",
            "--cases", str(tmp_path / "external.jsonl"), "--output", output,
        ])


def test_qa_runner_allows_collector_help_without_relaxing_experiment_paths():
    command = ["python", "scripts/collect_normative_rag_experiment.py", "--help"]

    assert qa._allowed_command(command) == [qa.sys.executable, *command[1:]]
    with pytest.raises(ValueError, match="requires explicit cases and output"):
        qa._allowed_command([
            "python", "scripts/collect_normative_rag_experiment.py", "--no-warm-cache",
        ])


def test_qa_runner_allows_only_the_live_rag_browser_smoke():
    command = ["node", "tests/js/normative-rag-live-smoke.mjs"]
    assert qa._allowed_command(command) == ["node.exe", *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])


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


def test_temporary_reviewer_credential_is_scoped_to_synthetic_seed(monkeypatch):
    secret = "qa-reviewer-secret-never-print-this"
    monkeypatch.setenv("JURIX_QA_REVIEWER_PASSWORD", secret)
    base = {"JURIX_QA_ONLY": "1"}
    seed_env = qa._command_environment(base, ["python", "manage.py", "seed_normative_qa", "--output", "qa.json"])
    review_env = qa._command_environment(base, ["node", "tests/js/normative-admin-review.browser.test.mjs"])
    collections_env = qa._command_environment(
        base, ["node", "tests/js/normative-collections.browser.test.mjs"]
    )
    check_env = qa._command_environment(base, ["python", "manage.py", "check"])
    assert seed_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert review_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert collections_env["JURIX_QA_REVIEWER_PASSWORD"] == secret
    assert "JURIX_QA_REVIEWER_PASSWORD" not in check_env


def test_qa_runner_allows_only_the_authenticated_synthetic_review_browser_test():
    command = ["node", "tests/js/normative-admin-review.browser.test.mjs"]
    assert qa._allowed_command(command) == ["node.exe", *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])


def test_qa_runner_allows_only_the_authenticated_synthetic_collections_browser_test():
    command = ["node", "tests/js/normative-collections.browser.test.mjs"]
    assert qa._allowed_command(command) == ["node.exe", *command[1:]]
    with pytest.raises(ValueError):
        qa._allowed_command(command + ["https://example.com"])


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
    isolated_verification_port = ["python", "manage.py", "runserver", "127.0.0.1:8010", "--noreload"]
    assert qa._allowed_command(isolated_verification_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8010",
        "--noreload",
    ]
    isolated_streaming_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8011", "--noreload"
    ]
    assert qa._allowed_command(isolated_streaming_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8011",
        "--noreload",
    ]
    isolated_link_verification_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8012", "--noreload"
    ]
    assert qa._allowed_command(isolated_link_verification_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8012",
        "--noreload",
    ]
    isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8013", "--noreload"
    ]
    assert qa._allowed_command(isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8013",
        "--noreload",
    ]
    second_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8014", "--noreload"
    ]
    assert qa._allowed_command(second_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8014",
        "--noreload",
    ]
    third_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8015", "--noreload"
    ]
    assert qa._allowed_command(third_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8015",
        "--noreload",
    ]
    fourth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8016", "--noreload"
    ]
    assert qa._allowed_command(fourth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8016",
        "--noreload",
    ]
    fifth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8017", "--noreload"
    ]
    assert qa._allowed_command(fifth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8017",
        "--noreload",
    ]
    sixth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8018", "--noreload"
    ]
    assert qa._allowed_command(sixth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8018",
        "--noreload",
    ]
    seventh_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8019", "--noreload"
    ]
    assert qa._allowed_command(seventh_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8019",
        "--noreload",
    ]
    eighth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8020", "--noreload"
    ]
    assert qa._allowed_command(eighth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8020",
        "--noreload",
    ]
    ninth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8021", "--noreload"
    ]
    assert qa._allowed_command(ninth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8021",
        "--noreload",
    ]
    tenth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8022", "--noreload"
    ]
    assert qa._allowed_command(tenth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8022",
        "--noreload",
    ]
    eleventh_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8023", "--noreload"
    ]
    assert qa._allowed_command(eleventh_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8023",
        "--noreload",
    ]
    twelfth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8024", "--noreload"
    ]
    assert qa._allowed_command(twelfth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8024",
        "--noreload",
    ]
    thirteenth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8025", "--noreload"
    ]
    assert qa._allowed_command(thirteenth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8025",
        "--noreload",
    ]
    fourteenth_isolated_fresh_code_port = [
        "python", "manage.py", "runserver", "127.0.0.1:8026", "--noreload"
    ]
    assert qa._allowed_command(fourteenth_isolated_fresh_code_port) == [
        qa.sys.executable,
        "manage.py",
        "runserver",
        "127.0.0.1:8026",
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


def test_pilot_manifest_requires_output_inside_the_isolated_qa_root(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    accepted = [
        "python", "manage.py", "build_pilot_manifest", "--schema-version", "2",
        "--output", str(qa_root / "pilot.jsonl"),
    ]
    assert qa._allowed_command(accepted)[0] == qa.sys.executable
    with pytest.raises(ValueError, match="inside JURIX_QA_ROOT"):
        qa._allowed_command([
            "python", "manage.py", "build_pilot_manifest", "--schema-version", "2",
            "--output", str(tmp_path / "outside.jsonl"),
        ])
    with pytest.raises(ValueError, match="explicit output path"):
        qa._allowed_command(["python", "manage.py", "build_pilot_manifest", "--schema-version", "2"])


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


def test_corpus_staging_command_requires_allowlisted_flags_and_qa_manifest(tmp_path, monkeypatch):
    qa_root = tmp_path / "qa"
    qa_root.mkdir()
    monkeypatch.setenv("JURIX_QA_ROOT", str(qa_root))
    accepted = [
        "python", "manage.py", "stage_normative_corpus",
        "--archive", str(tmp_path / "source.zip"),
        "--manifest", str(qa_root / "inventory.jsonl"),
        "--batch-size", "10", "--byte-budget", "1000000",
        "--time-budget-seconds", "60", "--apply",
    ]
    assert qa._allowed_command(accepted)[0] == qa.sys.executable
    with pytest.raises(ValueError, match="inside JURIX_QA_ROOT"):
        qa._allowed_command(accepted[:accepted.index("--manifest") + 1] + [str(tmp_path / "outside.jsonl")])
    with pytest.raises(ValueError, match="not on the QA allowlist"):
        qa._allowed_command(accepted + ["--max-sources", "999"])
    assert qa._allowed_command(accepted[:-1] + ["--dry-run"])[0] == qa.sys.executable
    with pytest.raises(ValueError, match="explicit archive and manifest"):
        qa._allowed_command(["python", "manage.py", "stage_normative_corpus", "--apply"])


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
