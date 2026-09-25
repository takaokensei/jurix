"""Deployment guards (audit P1.1 / P1.2): cheap tests that keep infra regressions out."""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def _dockerfile_cmd():
    text = (ROOT / "docker" / "Dockerfile").read_text()
    text = re.sub(r"\\\s*\n\s*", " ", text)  # join continuation lines
    return json.loads(re.search(r"^CMD (\[.*\])\s*$", text, re.M).group(1))


def _flag(cmd, name):
    return cmd[cmd.index(name) + 1]


def test_gunicorn_uses_threaded_workers_so_sse_streams_do_not_block_the_site():
    cmd = _dockerfile_cmd()
    assert cmd[0] == "gunicorn"
    assert _flag(cmd, "--worker-class") == "gthread"
    assert int(_flag(cmd, "--threads")) >= 4


def test_gunicorn_timeout_is_explicit_and_covers_a_slow_generation():
    assert int(_flag(_dockerfile_cmd(), "--timeout")) >= 60


def test_coverage_gate_is_configured_and_ignores_test_files():
    rc = (ROOT / ".coveragerc").read_text()
    assert re.search(r"^fail_under\s*=\s*\d+", rc, re.M)
    assert "src/tests/*" in rc  # tests must not inflate the number they are judged by


def _git_ignored(path):
    import shutil
    import subprocess

    if shutil.which("git") is None or not (ROOT / ".git").exists():
        import pytest

        pytest.skip("not a git checkout")
    return subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT).returncode == 0


def test_gitignore_hides_downloaded_data_but_not_legitimate_json_or_pdf():
    assert _git_ignored("data/raw/norma_1.pdf")
    assert _git_ignored("data/exports/dump.json")
    # A bare '*.json' / '*.pdf' rule used to hide these too:
    assert not _git_ignored("src/tests/fixtures/sample.json")
    assert not _git_ignored("package.json")
    assert not _git_ignored("docs/relatorio.pdf")


def test_pull_request_descriptions_do_not_live_in_the_repo_tree_root_of_github():
    assert not list((ROOT / ".github").glob("pr_*.md"))
