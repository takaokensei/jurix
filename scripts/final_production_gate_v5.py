from __future__ import annotations

import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYTHON = sys.executable


def run(label: str, args: list[str]) -> None:
    print(f"=== {label} ===")
    r = subprocess.run(args, cwd=ROOT, env=os.environ.copy(), check=False)
    if r.returncode:
        raise SystemExit(r.returncode)


def main() -> None:
    run("INGESTION REFACTOR", [PYTHON, "scripts/verify_ingestion_refactor_v5.py"])
    run("VECTOR PRODUCTION GATE", [PYTHON, "scripts/vector_production_gate_v5.py", "--strict"])
    run("LEGAL BENCHMARK", [PYTHON, "scripts/run_legal_benchmark_v1.py", "--strict"])
    print("FINAL PRODUCTION GATE PASSED")


if __name__ == "__main__":
    main()
