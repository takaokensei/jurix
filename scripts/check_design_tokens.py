"""Guard the canonical CSS token boundary.

The migration is intentionally incremental: existing legacy hex values are
tracked in a baseline, while any new value or occurrence fails the gate.
Token files are exempt because they are the source of truth by definition.
"""

from __future__ import annotations

import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CSS_ROOT = ROOT / "src" / "apps" / "core" / "static" / "css"
BASELINE_PATH = ROOT / "scripts" / "design-token-baseline.json"
HEX_RE = re.compile(r"#[0-9a-fA-F]{3,8}\b")
TOKEN_FILES = {"jurix-figma.css", "swiss-design-system.css"}


def current_values() -> dict[str, Counter[str]]:
    values: dict[str, Counter[str]] = {}
    for path in sorted(CSS_ROOT.glob("*.css")):
        if path.name in TOKEN_FILES:
            continue
        found = Counter(
            match.group(0).lower() for match in HEX_RE.finditer(path.read_text(encoding="utf-8"))
        )
        if found:
            values[path.name] = found
    return values


def main() -> int:
    baseline = json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    actual = current_values()
    violations: list[str] = []

    for filename, counts in actual.items():
        allowed = Counter(baseline.get(filename, {}))
        for value, count in (counts - allowed).items():
            violations.append(f"{filename}: {value} (+{count})")
    for filename, allowed in baseline.items():
        if filename not in actual and allowed:
            continue
        actual_counts = actual.get(filename, Counter())
        for value, count in (Counter(allowed) - actual_counts).items():
            # Deletions are safe during migration and do not fail the gate.
            if count < 0:
                violations.append(f"{filename}: {value} (invalid baseline)")

    if violations:
        print("Design-token guard failed: new hardcoded CSS colors detected:")
        print("\n".join(f"- {item}" for item in violations))
        print("Move the value to jurix-figma.css or update the migration deliberately.")
        return 1

    total = sum(sum(counter.values()) for counter in actual.values())
    print(f"Design-token guard passed: {total} legacy hex occurrences remain in baseline.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
