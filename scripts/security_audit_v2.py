#!/usr/bin/env python3
"""
Static security audit for the Jurix repository.

The scanner is intentionally conservative: findings are categorized as BLOCK,
REVIEW or INFO rather than pretending regex can prove a vulnerability. It is
designed to catch accidental regressions in pull requests.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Finding:
    severity: str
    path: str
    line: int
    rule: str
    message: str


RULES = (
    ("BLOCK", "hardcoded-secret", re.compile(r"""(?:SECRET_KEY|PASSWORD|TOKEN|API_KEY)\s*=\s*["'][^"']{12,}["']""")),
    ("BLOCK", "shell-true", re.compile(r"""\bshell\s*=\s*True\b""")),
    ("REVIEW", "unsafe-eval", re.compile(r"""\b(?:eval|exec)\s*\(""")),
    ("REVIEW", "raw-innerhtml", re.compile(r"""\.innerHTML\s*=""")),
    ("REVIEW", "dangerous-subprocess", re.compile(r"""\bsubprocess\.(?:run|Popen|call)\s*\(""")),
    ("INFO", "todo-production", re.compile(r"""\bTODO\b.*(?:production|security|release)""", re.IGNORECASE)),
)

IGNORE_PARTS = {
    ".git",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    "staticfiles",
    ".pytest_cache",
}


def iter_files(root: Path):
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_PARTS for part in path.parts):
            continue
        if path.suffix.lower() not in {".py", ".js", ".mjs", ".ts", ".html", ".yml", ".yaml", ".env", ".toml"}:
            continue
        yield path


def scan(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    for path in iter_files(root):
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        is_test_file = "tests" in path.parts or path.name.startswith("test_")
        for line_number, line in enumerate(text.splitlines(), start=1):
            for severity, rule, pattern in RULES:
                if pattern.search(line):
                    if rule == "hardcoded-secret" and (is_test_file or "_DEV_" in line or "_DEV" in line):
                        continue
                    findings.append(
                        Finding(
                            severity=severity,
                            path=str(path.relative_to(root)),
                            line=line_number,
                            rule=rule,
                            message=line.strip()[:300],
                        )
                    )
    return findings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", type=Path)
    parser.add_argument("--fail-on-review", action="store_true")
    args = parser.parse_args()

    findings = scan(args.root.resolve())
    payload = {
        "findings": [item.__dict__ for item in findings],
        "counts": {
            "BLOCK": sum(item.severity == "BLOCK" for item in findings),
            "REVIEW": sum(item.severity == "REVIEW" for item in findings),
            "INFO": sum(item.severity == "INFO" for item in findings),
        },
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    if args.json:
        args.json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    if payload["counts"]["BLOCK"]:
        return 2
    if args.fail_on_review and payload["counts"]["REVIEW"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
