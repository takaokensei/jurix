"""Protect the public Celery task contract while ingestion is being refactored."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TASKS = ROOT / "src/apps/ingestion/tasks.py"
REQUIRED = {
    "ingest_normas_task",
    "ingest_normas_bulk_task",
    "download_pdf_task",
    "ocr_pdf_task",
    "consolidate_norma_task",
    "generate_embedding_task",
}


def main() -> int:
    tree = ast.parse(TASKS.read_text(encoding="utf-8"))
    found = set()
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.add(node.name)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                found.add(alias.asname or alias.name)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found.add(target.id)

    missing = sorted(REQUIRED - found)
    if missing:
        print("[FAIL] missing public ingestion tasks:", ", ".join(missing))
        return 1
    lines = len(TASKS.read_text(encoding="utf-8").splitlines())
    print(f"Ingestion contract passed: {len(REQUIRED)} public tasks; {lines} lines tracked.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
