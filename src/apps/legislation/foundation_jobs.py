"""Ephemeral cache keys for authenticated foundation-check jobs."""

FOUNDATION_JOB_TTL_SECONDS = 900


def foundation_job_key(job_id):
    return f"jurix:foundation-check:{job_id}"


def foundation_payload_key(job_id):
    return f"jurix:foundation-check:{job_id}:payload"


def foundation_result_key(job_id):
    return f"jurix:foundation-check:{job_id}:result"
