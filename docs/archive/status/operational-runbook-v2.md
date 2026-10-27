# Jurix Operational Runbook v2

## Health triage

### Web is down

```text
docker compose ps
docker compose logs web
python manage.py production_preflight_v2 --strict
```

### RAG returns fallback answers

Check, in order:

```text
Ollama -> vector health -> corpus freshness -> strict grounding -> model logs
```

### Ingestion queue is stalled

```text
python scripts/celery_queue_guard_v2.py
```

Inspect worker heartbeats, active tasks and repeated failures before retrying the
same workload.

### Attachment audit reports missing objects

Do not delete database rows automatically.

First:

1. identify the storage backend;
2. compare the storage key;
3. verify retention policy;
4. inspect recent deploy/storage volume changes;
5. restore the object if a valid backup exists.

## Release procedure

```text
git status
ruff
pytest
production_preflight_v2 --strict
check_corpus_integrity_v2 --strict
check_vector_health_v2 --strict
security_audit_v2
architecture_budget_v2
RAG benchmark
staging smoke
backup verification
```

Record all gate outputs with the release candidate.

## Rollback procedure

Disable traffic, stop new ingestion, snapshot the current state, revert code,
validate migrations, restart workers, then repeat the smoke and integrity gates.
