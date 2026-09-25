# Production hardening checklist

Use this checklist on every release candidate.

## Source and CI

- [ ] `ruff check src/` passes.
- [ ] `ruff format --check src/` passes.
- [ ] `python manage.py check --deploy` passes.
- [ ] `python manage.py makemigrations --check --dry-run` passes.
- [ ] Full pytest suite passes with a real PostgreSQL/pgvector service.
- [ ] Frontend XSS tests pass.
- [ ] No generated artifacts or secrets are committed.

## Configuration

- [ ] `DEBUG=False`.
- [ ] `DJANGO_SECRET_KEY` is private and rotated outside source control.
- [ ] `ALLOWED_HOSTS` is explicit.
- [ ] `POSTGRES_PASSWORD` is not a development fallback.
- [ ] Redis cache is enabled.
- [ ] `OLLAMA_MODEL` and `OLLAMA_EMBEDDING_MODEL` are pinned.
- [ ] `SAPL_OCR_MAX_PAGES` is within the supported range.
- [ ] Storage backend matches the deployment topology.

## Storage

- [ ] PostgreSQL backup exists and has been restore-tested.
- [ ] Local attachment storage is on durable disk, or S3 is used.
- [ ] Attachment audit with hashes succeeds.
- [ ] Expired records are understood and retention policy is documented.

## Ingestion

- [ ] Remote downloads have size/time limits.
- [ ] OCR has page/time limits.
- [ ] Parser subprocesses have resource limits.
- [ ] A failed external integration does not mark partial data as complete.

## RAG

- [ ] Reviewed benchmark corpus is versioned.
- [ ] Benchmark hash matches the manifest.
- [ ] Baseline metrics are tied to the same models.
- [ ] Regression checker passes.
- [ ] Unanswerable cases are represented.
- [ ] Citation and grounding checks are monitored separately from similarity.

## Runtime

- [ ] Readiness fails when required dependencies are unavailable.
- [ ] Celery queues are monitored.
- [ ] Long-running tasks have sane worker recycling/limits.
- [ ] Logs avoid secrets and raw session identifiers.
- [ ] Health endpoints are reachable from the orchestrator.

## UX and accessibility

- [ ] Keyboard-only flow works.
- [ ] Focus state is visible.
- [ ] Error states are actionable.
- [ ] Streaming interruption is recoverable.
- [ ] Source citations are inspectable.
- [ ] Uncertainty is not presented as legal certainty.
