"""Validate repository-level staging promotion prerequisites."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED = {
    "docker-compose.prod.yml": ("web:", "worker:", "beat:", "jurix_data:"),
    "docs/production-final-assurance-v4.md": ("staging", "backup", "rollback"),
    ".github/workflows/production-assurance-v2.yml": (
        "Production gate",
        "Vector query plan contract",
    ),
}


def main() -> int:
    failures = []
    for relative, markers in REQUIRED.items():
        path = ROOT / relative
        if not path.is_file():
            failures.append(f"missing file: {relative}")
            continue
        text = path.read_text(encoding="utf-8")
        failures.extend(
            f"{relative}: missing {marker!r}" for marker in markers if marker not in text
        )
    if failures:
        for item in failures:
            print(f"[FAIL] {item}")
        return 1
    print("Staging contract passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
