"""Validation for parsed, not-yet-persisted legal-device parent trees."""

from __future__ import annotations


def validate_hierarchy(rows: list[dict]) -> None:
    """Raise ValueError before persistence when indexes or parent links are unsafe."""
    by_index: dict[int, dict] = {}
    for row in rows:
        index = row.get("index")
        if not isinstance(index, int) or index in by_index:
            raise ValueError("Hierarquia contém índice ausente ou duplicado.")
        by_index[index] = row

    parents: dict[int, int | None] = {}
    for index, row in by_index.items():
        parent = row.get("parent_index")
        if parent is not None and (parent not in by_index or parent == index):
            raise ValueError("Hierarquia contém pai ausente ou autorreferente.")
        parents[index] = parent

    complete: set[int] = set()
    for start in parents:
        path: set[int] = set()
        current: int | None = start
        while current is not None and current not in complete:
            if current in path:
                raise ValueError("Hierarquia contém um ciclo de dispositivos.")
            path.add(current)
            current = parents[current]
        complete.update(path)
