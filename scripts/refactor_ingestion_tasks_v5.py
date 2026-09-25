#!/usr/bin/env python3
from __future__ import annotations

import argparse
import ast
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src/apps/ingestion"
TASKS = PKG / "tasks.py"
LEGACY = PKG / "tasks_legacy.py"

GROUPS = {
    "download_tasks.py": ("download", "fetch", "sync", "ingest", "bulk"),
    "ocr_tasks.py": ("ocr", "pdf", "tesseract"),
    "segmentation_tasks.py": ("segment", "chunk"),
    "ner_tasks.py": ("ner", "entity"),
    "consolidation_tasks.py": ("consolid", "patch", "article"),
    "embedding_tasks.py": ("embedding", "vector", "index"),
}


def task_names(source: str) -> list[str]:
    tree = ast.parse(source)
    out = []
    for n in tree.body:
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and any(
            "task" in ast.unparse(d).lower() for d in n.decorator_list
        ):
            out.append(n.name)
    return out


def group_for(name: str) -> str:
    low = name.lower()
    for f, tokens in GROUPS.items():
        if any(x in low for x in tokens):
            return f
    return "core_tasks.py"


def apply() -> None:
    if not TASKS.exists():
        raise SystemExit(f"missing {TASKS}")
    if LEGACY.exists():
        raise SystemExit("tasks_legacy.py already exists")
    source = TASKS.read_text(encoding="utf-8")
    names = task_names(source)
    if len(names) < 6:
        raise SystemExit(f"expected >=6 Celery tasks, found {len(names)}")
    shutil.move(TASKS, LEGACY)
    buckets: dict[str, list[str]] = {x: [] for x in GROUPS}
    buckets["core_tasks.py"] = []
    for name in names:
        buckets[group_for(name)].append(name)
    for filename, members in buckets.items():
        if not members:
            continue
        imports = "\n".join(f"from .tasks_legacy import {name}" for name in sorted(members))
        body = f'"""Compatibility facade for ingestion tasks."""\n\n{imports}\n\n__all__ = {sorted(members)!r}\n'
        (PKG / filename).write_text(body, encoding="utf-8")
    exports = "\n".join(f"from .{group_for(n)[:-3]} import {n}" for n in sorted(names))
    all_exports = sorted(set(names) | {"ingest_normas_bulk_task"})
    TASKS.write_text(
        '"""Stable public ingestion task API."""\n\nfrom __future__ import annotations\n\n'
        'import sys\nfrom typing import Any\n\nfrom . import tasks_legacy\nfrom .tasks_legacy import *  # noqa: F403,F401\n\n'
        f"{exports}\n\ningest_normas_bulk_task = bulk_ingest_normas_task\n\n"
        f"__all__ = {all_exports!r}\n\n\n"
        "class _TasksModule(sys.modules[__name__].__class__):\n"
        "    def __getattr__(self, name: str) -> Any:\n"
        "        return getattr(tasks_legacy, name)\n\n"
        "    def __setattr__(self, name: str, value: Any) -> None:\n"
        "        super().__setattr__(name, value)\n"
        '        if hasattr(tasks_legacy, name) or name.startswith("_") or name == "logger":\n'
        "            setattr(tasks_legacy, name, value)\n\n\n"
        "sys.modules[__name__].__class__ = _TasksModule\n",
        encoding="utf-8",
    )
    print(f"Ingestion facade created with {len(names)} public tasks.")


def check() -> int:
    if not TASKS.exists() or not LEGACY.exists():
        print("FAIL: run scripts/refactor_ingestion_tasks_v5.py --apply")
        return 1
    lines = len(TASKS.read_text(encoding="utf-8").splitlines())
    if lines > 180:
        print(f"FAIL: tasks.py is {lines} lines")
        return 1
    print(f"PASS: public tasks.py is {lines} lines")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if a.apply:
        apply()
    else:
        raise SystemExit(check())
