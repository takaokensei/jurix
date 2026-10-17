"""Bounded asynchronous tasks for the authenticated legislation workspace."""

from __future__ import annotations

import uuid
from datetime import date

from celery import shared_task
from django.core.cache import cache

from src.apps.legislation.foundation_jobs import (
    FOUNDATION_JOB_TTL_SECONDS,
    foundation_job_key,
    foundation_payload_key,
    foundation_result_key,
)
from src.processing.foundation_check import FoundationCheckCancelled, check_foundation
from src.processing.foundation_reference_parser import FoundationReference


@shared_task(
    name="legislation.check_foundation",
    ignore_result=True,
    acks_late=True,
    reject_on_worker_lost=True,
    soft_time_limit=300,
    time_limit=330,
)
def check_foundation_task(job_id: str) -> None:
    """Run one short-lived check using citation metadata, never pasted prose."""
    try:
        normalized_job_id = str(uuid.UUID(str(job_id)))
    except (TypeError, ValueError, AttributeError):
        return

    status_key = foundation_job_key(normalized_job_id)
    payload_key = foundation_payload_key(normalized_job_id)
    payload = cache.get(payload_key)
    state = cache.get(status_key)
    if not isinstance(payload, dict) or not isinstance(state, dict):
        return
    if payload.get("owner_id") != state.get("owner_id"):
        return
    if state.get("status") == "cancelling":
        state.update(status="cancelled")
        cache.set(status_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        cache.delete(payload_key)
        return

    state.update(status="running")
    cache.set(status_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)

    def should_cancel():
        current = cache.get(status_key) or {}
        return (
            current.get("owner_id") == payload.get("owner_id")
            and current.get("status") == "cancelling"
        )

    def on_progress(completed, total):
        current = cache.get(status_key) or {}
        if current.get("owner_id") != payload.get("owner_id"):
            return
        current.update(completed=completed, total=total)
        if current.get("status") != "cancelling":
            current["status"] = "running"
        cache.set(status_key, current, timeout=FOUNDATION_JOB_TTL_SECONDS)

    try:
        references = [FoundationReference(**item) for item in payload.get("references", [])]
        result = check_foundation(
            references=references,
            from_date=date.fromisoformat(payload["from_date"]),
            to_date=date.fromisoformat(payload["to_date"]),
            should_cancel=should_cancel,
            on_progress=on_progress,
        )
    except FoundationCheckCancelled:
        state = cache.get(status_key) or {}
        if state.get("owner_id") == payload.get("owner_id"):
            state["status"] = "cancelled"
            cache.set(status_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        cache.delete(payload_key)
        return
    except Exception as exc:
        state = cache.get(status_key) or {}
        if state.get("owner_id") == payload.get("owner_id"):
            state.update(status="failed", error_code=type(exc).__name__)
            cache.set(status_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        cache.delete(payload_key)
        return

    state = cache.get(status_key) or {}
    if state.get("owner_id") != payload.get("owner_id"):
        cache.delete(payload_key)
        return
    if state.get("status") == "cancelling":
        state["status"] = "cancelled"
        cache.set(status_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)
        cache.delete(payload_key)
        return

    cache.set(foundation_result_key(normalized_job_id), result, timeout=FOUNDATION_JOB_TTL_SECONDS)
    state.update(
        status="completed",
        completed=state.get("total", 0),
        total=state.get("total", 0),
    )
    cache.set(status_key, state, timeout=FOUNDATION_JOB_TTL_SECONDS)
    cache.delete(payload_key)
