# Jurix Disaster Recovery v2

## Recovery objectives

Define and record:

- RPO for PostgreSQL;
- RPO for object storage;
- target recovery time;
- acceptable temporary loss of generated cache state.

Redis cache contents are disposable. PostgreSQL legal metadata and object storage
attachments are not.

## Recovery order

```text
infrastructure
 -> PostgreSQL
 -> object storage
 -> Redis
 -> Django web
 -> Celery workers
 -> Ollama
 -> corpus/vector checks
```

## Restore checklist

1. Restore PostgreSQL backup.
2. Validate migration state.
3. Restore object storage.
4. Run attachment reconciliation.
5. Start Redis.
6. Start web and worker services.
7. Run vector health.
8. Run corpus integrity.
9. Verify SAPL connectivity.
10. Run the staging smoke test.
11. Record the backup hash and restore timestamp.

## Cache invalidation

Corpus-changing operations should bump the corpus version. Do not flush the
Redis database when cache and Celery share the same Redis deployment.

## Rollback

Rollback code and rollback data are different operations.

A code rollback must not blindly restore a stale database unless the migration
plan explicitly supports it.

## Drill policy

Perform a restore drill periodically. Record:

- backup identifier;
- start/end time;
- restore outcome;
- vector rebuild duration;
- unresolved findings.

A backup without a tested restore path is an unverified backup.
