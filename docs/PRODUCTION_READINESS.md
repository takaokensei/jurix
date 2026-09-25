# Jurix — Production Readiness

This document is the canonical acceptance checklist for the production
remediation work.

## CI gate

- `pytest` runs with real Django migrations.
- pgvector is present before the test database is used.
- `ruff check src/` returns zero errors.
- `ruff format --check src/` passes.
- frontend unit tests pass.
- real browser tests run in Chromium in CI.

## Streaming

The Ollama generator is now forwarded chunk-by-chunk through SSE. The full
answer is retained only for persistence and final validation.

SSE event contract:

```text
session
sources
chunk*
done
```

`confidence` is intentionally not a probability. The canonical retrieval
signal is `source_relevance`; a calibrated answer confidence must be introduced
only together with a labeled validation set.

## Grounding

The deterministic grounding guard checks that factual/legal claims are tied to
retrieved evidence through citations or meaningful lexical overlap. This is a
safety guard, not a proof of legal correctness and not a calibrated probability.

The next acceptance gate is a versioned benchmark corpus stored outside the
application source tree when licensing permits it. Each case should record:

```text
question
expected_norms
expected_devices
expected_citations
```

and the benchmark should publish Recall@K, Precision@K, MRR, citation precision,
citation recall and groundedness.

## Runtime

`/api/v1/health/live/` checks only process liveness.
`/api/v1/health/ready/` checks PostgreSQL, pgvector, Redis, migrations and
Ollama. `/api/v1/health/` remains as the compatibility readiness endpoint.

The default `docker-compose.yml` is production-oriented. Development uses:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev.yml up --build
```

## SAPL

The incremental task performs a bounded newest-page scan and skips records whose
payload fingerprint has not changed. This is intentionally not described as a
vendor-provided `updated_since` API because SAPL deployments differ.

## Legal consolidation

Target resolution now supports article descendants (paragraph, inciso, alínea
and item) through the materialized `dispositivo_pai` hierarchy. Ambiguous paths
remain unresolved and set the existing review workflow rather than being guessed.

## Remaining data-dependent gate

No source tree patch can manufacture a legally valid 100–500 question benchmark.
Before declaring RAG quality production-ready, populate the benchmark with a
licensed/authorized legal evaluation corpus and run it against each retriever
change.
