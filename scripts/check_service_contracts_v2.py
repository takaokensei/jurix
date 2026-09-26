#!/usr/bin/env python3
"""Static contract checks for endpoints and operational entrypoints."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

EXPECTED_FILES = (
    "src/apps/legislation/api_urls.py",
    "src/apps/legislation/api_views.py",
    "src/clients/sapl/sapl_client.py",
    "src/processing/rag_service.py",
    "src/processing/grounding_service.py",
    "src/processing/strict_grounding.py",
)


def names_in_module(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            names.add(node.name)
    return names


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("."))
    args = parser.parse_args()

    root = args.root.resolve()
    missing_files = [item for item in EXPECTED_FILES if not (root / item).is_file()]
    report = {"missing_files": missing_files, "modules": {}}

    for relative in EXPECTED_FILES:
        path = root / relative
        if path.is_file():
            report["modules"][relative] = sorted(names_in_module(path))

    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 2 if missing_files else 0


if __name__ == "__main__":
    raise SystemExit(main())
