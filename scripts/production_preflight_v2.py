#!/usr/bin/env python3
"""Repository-level preflight runner for production candidate builds."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


@dataclass
class StepResult:
    name: str
    returncode: int
    output: str

    @property
    def passed(self) -> bool:
        return self.returncode == 0


def run_step(name: str, command: list[str], cwd: Path) -> StepResult:
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        capture_output=True,
        check=False,
    )
    output = (completed.stdout + "\n" + completed.stderr).strip()
    return StepResult(name, completed.returncode, output)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--strict", action="store_true")
    parser.add_argument("--skip-pytest", action="store_true")
    parser.add_argument("--skip-ruff", action="store_true")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    python = sys.executable
    results: list[StepResult] = []

    results.append(
        run_step(
            "django-preflight",
            [python, "manage.py", "production_preflight_v2", "--strict"],
            root,
        )
    )
    results.append(
        run_step(
            "corpus-integrity",
            [python, "manage.py", "check_corpus_integrity_v2", "--strict"],
            root,
        )
    )
    results.append(
        run_step(
            "vector-health",
            [python, "manage.py", "check_vector_health_v2", "--strict"],
            root,
        )
    )

    if not args.skip_ruff:
        results.append(run_step("ruff", [python, "-m", "ruff", "check", "."], root))

    if not args.skip_pytest:
        results.append(run_step("pytest", [python, "-m", "pytest"], root))

    report = {
        "passed": all(item.passed for item in results),
        "steps": [
            {
                "name": item.name,
                "returncode": item.returncode,
                "passed": item.passed,
                "output_tail": item.output[-4000:],
            }
            for item in results
        ],
        "environment": {
            "ci": bool(os.getenv("CI")),
            "git_ref": os.getenv("GITHUB_SHA") or os.getenv("GIT_COMMIT"),
        },
    }

    payload = json.dumps(report, ensure_ascii=False, indent=2)
    print(payload)
    if args.json:
        args.json.write_text(payload, encoding="utf-8")

    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
