#!/usr/bin/env python3
"""Fail release validation when application modules exceed maintainability budgets."""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

DEFAULT_LIMIT = 800


def longest_function(tree: ast.AST) -> tuple[str, int]:
    best = ("<module>", 0)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            size = (node.end_lineno or node.lineno) - node.lineno + 1
            if size > best[1]:
                best = (node.name, size)
    return best


def inspect(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    tree = ast.parse(text)
    fn, fn_lines = longest_function(tree)
    return {"path": str(path), "lines": len(text.splitlines()), "largest_function": fn, "largest_function_lines": fn_lines}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=DEFAULT_LIMIT)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1] / "src"
    rows = [inspect(path) for path in root.rglob("*.py") if "migrations" not in path.parts]
    violations = [row for row in rows if row["lines"] > args.limit]
    if args.json:
        import json
        print(json.dumps({"violations": violations, "count": len(violations)}, ensure_ascii=False, indent=2))
    else:
        for row in sorted(rows, key=lambda item: int(item["lines"]), reverse=True)[:20]:
            print(f"{row['lines']:4} {row['path']} | largest function: {row['largest_function']} ({row['largest_function_lines']} lines)")
    return 2 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
