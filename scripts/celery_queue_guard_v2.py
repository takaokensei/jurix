#!/usr/bin/env python3
"""Operational guard for Celery queues via the native `celery inspect` CLI."""
from __future__ import annotations

import argparse
import json
import subprocess
import sys


def run(command: list[str]) -> tuple[int, str]:
    completed = subprocess.run(command, text=True, capture_output=True, check=False)
    return completed.returncode, (completed.stdout + "\n" + completed.stderr).strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--app", default="config")
    parser.add_argument("--timeout", type=int, default=5)
    args = parser.parse_args()

    commands = {
        "ping": [sys.executable, "-m", "celery", "-A", args.app, "inspect", "ping", "--timeout", str(args.timeout)],
        "stats": [sys.executable, "-m", "celery", "-A", args.app, "inspect", "stats", "--timeout", str(args.timeout)],
        "active": [sys.executable, "-m", "celery", "-A", args.app, "inspect", "active", "--timeout", str(args.timeout)],
    }

    results = {}
    for name, command in commands.items():
        code, output = run(command)
        results[name] = {"returncode": code, "output_tail": output[-5000:]}

    passed = all(item["returncode"] == 0 for item in results.values())
    print(json.dumps({"passed": passed, "results": results}, ensure_ascii=False, indent=2))
    return 0 if passed else 2


if __name__ == "__main__":
    raise SystemExit(main())
