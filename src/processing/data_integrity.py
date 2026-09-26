"""
Read-only integrity checks for Jurix legal corpus and operational metadata.

These checks are safe to run before backups, deployments, or corpus refreshes.
They intentionally do not mutate rows. Any mutation belongs in an explicit,
reviewable command.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class IntegrityIssue:
    code: str
    severity: str
    message: str
    count: int = 1
    details: dict[str, Any] | None = None

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class IntegritySummary:
    checked: int
    issues: tuple[IntegrityIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(item.severity in {"critical", "error"} for item in self.issues)

    def as_dict(self) -> dict[str, Any]:
        return {
            "checked": self.checked,
            "ok": self.ok,
            "issues": [item.as_dict() for item in self.issues],
        }


def check_numeric_range(value: Any, minimum: float, maximum: float, code: str) -> list[IntegrityIssue]:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return [
            IntegrityIssue(
                code=code,
                severity="error",
                message=f"Value {value!r} is not numeric.",
            )
        ]
    if number < minimum or number > maximum:
        return [
            IntegrityIssue(
                code=code,
                severity="error",
                message=f"Value {number} is outside [{minimum}, {maximum}].",
            )
        ]
    return []


def summarize_issues(
    *,
    checked: int,
    issues: list[IntegrityIssue],
) -> IntegritySummary:
    return IntegritySummary(checked=checked, issues=tuple(issues))
