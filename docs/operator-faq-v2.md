# Jurix Operator FAQ v2

## Can I use the local filesystem in production?

Only for a deliberate single-host deployment with a persistent volume. A
multi-host deployment should use object storage.

## Can Redis be flushed to invalidate RAG answers?

Not when Celery and cache share a Redis deployment. Use corpus-version bumping
or the application cache contract instead.

## Why does the RAG answer become a fallback?

The release policy is intentionally conservative. A fallback can indicate a
retrieval miss, a citation mismatch, a numeric mismatch, a certainty mismatch,
or another strict grounding failure.

## Does a green retrieval benchmark prove legal correctness?

No. It shows benchmark-specific retrieval and answer-contract behavior. Human
review remains necessary for release datasets.

## Should the audit command delete orphaned objects?

No. Audit and deletion are intentionally separated. A deletion workflow must
have an explicit retention policy and dry-run mode.

## What should be monitored after a corpus refresh?

Vector coverage, ingestion failures, strict-grounding rejection rate, cache
version, attachment audit state and queue backlog.
