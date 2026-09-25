from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "src/apps/ingestion/tasks.py"
LEGACY = ROOT / "src/apps/ingestion/tasks_legacy.py"

if not PUBLIC.exists() or not LEGACY.exists():
    raise SystemExit(
        "FAIL: ingestion facade not applied; run refactor_ingestion_tasks_v5.py --apply"
    )
if len(PUBLIC.read_text(encoding="utf-8").splitlines()) > 180:
    raise SystemExit("FAIL: public ingestion facade is too large")

tree = ast.parse(LEGACY.read_text(encoding="utf-8"))
names = [
    n.name
    for n in tree.body
    if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef)
    and any("task" in ast.unparse(d).lower() for d in n.decorator_list)
]
if len(names) < 6:
    raise SystemExit(f"FAIL: expected >=6 tasks, found {len(names)}")

text = "\n".join(p.read_text(encoding="utf-8") for p in PUBLIC.parent.glob("*_tasks.py"))
missing = [n for n in names if n not in text]
if missing:
    raise SystemExit("FAIL: missing task facade exports: " + ", ".join(missing))

print(f"PASS: ingestion facade exposes {len(names)} Celery tasks")
