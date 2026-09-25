# Production validation

This document covers the checks that can be automated without fabricating a
legal benchmark or depending on a specific hosting provider.

## Attachment integrity

Audit database metadata against the configured local/S3/MinIO backend:

```bash
python manage.py audit_attachment_storage
python manage.py audit_attachment_storage --verify-hash --fail-on-missing
```

`--verify-hash` reads the original object and compares it with the SHA-256
stored in PostgreSQL. The command is read-only.

Expired records are reported separately. Actual expiration remains owned by
the existing Celery cleanup task.

## RAG quality regression

The repository now contains a standalone regression comparator:

```bash
python scripts/check_rag_regression.py \
  --baseline benchmarks/rag/baseline.json \
  --current benchmarks/rag/current.json \
  --max-regression 0.03
```

The GitHub Actions workflow runs this check only after an expert-reviewed
gold corpus and baseline are versioned. Until then, the workflow exits
successfully without pretending that benchmark coverage exists.

## HTTP smoke/load

For a deployed instance:

```bash
python scripts/http_load_smoke.py \
  --url http://127.0.0.1:8000/api/v1/health/live/ \
  --requests 50 \
  --concurrency 8 \
  --max-p95-ms 500
```

The same utility can exercise a staging POST endpoint:

```bash
python scripts/http_load_smoke.py \
  --url https://staging.example.com/api/v1/search/answer/ \
  --method POST \
  --body '{"question":"Qual o prazo para recurso?","k":5}' \
  --requests 10 \
  --concurrency 2 \
  --timeout 30 \
  --max-p95-ms 15000
```

This is deliberately a smoke probe, not a substitute for sustained capacity
testing. Production capacity decisions should be based on measured CPU,
memory, PostgreSQL, Redis and Ollama utilization.

## What remains data-dependent

The legal benchmark itself is still external to the repository. It requires
expert-reviewed expected devices/citations and an accepted baseline before
CI can enforce quality thresholds. The repository does not manufacture those
labels.
