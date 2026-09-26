#!/usr/bin/env python3
"""Detect architectural hotspots before they become another refactor wave."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

DEFAULT_BUDGETS = {
    "src/apps/legislation/api_views.py": 900,
    "src/apps/ingestion/tasks.py": 1100,
    "src/processing/rag_service.py": 850,
    "src/clients/sapl/sapl_client.py": 550,
}


def module_stats(path: Path) -> dict[str, int]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text, filename=str(path))
    functions = sum(isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) for node in ast.walk(tree))
    classes = sum(isinstance(node, ast.ClassDef) for node in ast.walk(tree))
    imports = sum(isinstance(node, ast.Import | ast.ImportFrom) for node in ast.walk(tree))
    return {
        "lines": len(text.splitlines()),
        "functions": functions,
        "classes": classes,
        "imports": imports,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()

    root = args.root.resolve()
    findings = []
    for relative, budget in DEFAULT_BUDGETS.items():
        path = root / relative
        if not path.exists():
            continue
        stats = module_stats(path)
        if stats["lines"] > budget:
            findings.append(
                {
                    "path": relative,
                    "budget": budget,
                    "lines": stats["lines"],
                    "over_by": stats["lines"] - budget,
                    "functions": stats["functions"],
                    "classes": stats["classes"],
                    "imports": stats["imports"],
                }
            )

    report = {"findings": findings, "passed": not findings}
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.json:
        args.json.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0 if not findings else 1


if __name__ == "__main__":
    raise SystemExit(main())
