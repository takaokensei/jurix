"""Read-only Celery worker visibility for the normative QA queue."""

from __future__ import annotations


def get_normative_worker_health(*, inspect_factory=None, timeout: float = 1.0) -> dict:
    """Check whether at least one responding worker consumes `normative_qa`.

    The response intentionally excludes worker hostnames and exception details.
    """
    if timeout <= 0 or timeout > 5:
        raise ValueError("timeout must be between 0 and 5 seconds")
    if inspect_factory is None:
        from config.celery import app

        inspect_factory = app.control.inspect
    try:
        inspector = inspect_factory(timeout=timeout)
        active_queues = inspector.active_queues()
    except Exception:
        active_queues = None

    if active_queues is None:
        return {"status": "unavailable", "responding_workers": 0, "queue_workers": 0}

    queue_workers = sum(
        any(
            isinstance(queue, dict) and queue.get("name") == "normative_qa"
            for queue in (queues or [])
        )
        for queues in active_queues.values()
    )
    return {
        "status": "current" if queue_workers else "queue_missing",
        "responding_workers": len(active_queues),
        "queue_workers": queue_workers,
    }
