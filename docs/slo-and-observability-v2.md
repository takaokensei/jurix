# Jurix SLO and Observability v2

## Suggested indicators

### Web

- request count;
- error count;
- median;
- p95;
- p99.

### RAG

- retrieval latency;
- generation latency;
- total answer latency;
- grounding rejection rate;
- source-empty rate;
- cache hit ratio.

### Ingestion

- documents discovered;
- downloads succeeded;
- downloads failed;
- OCR time;
- parse failures;
- embedding backlog.

### Data

- attachment missing count;
- hash mismatch count;
- embedding coverage;
- consolidated-device coverage.

## Alert examples

### High grounding rejection

Alert when grounding rejection remains above the baseline envelope for a
continuous window.

### Missing attachments

Alert on any non-zero missing attachment count in a production audit.

### Vector coverage

Alert when embedding coverage falls below the release threshold after a corpus
refresh.

### Queue stall

Alert when worker heartbeats disappear or the oldest active task exceeds the
expected processing envelope.

## Metrics ownership

Every production metric should have:

- owner;
- dashboard;
- alert threshold;
- runbook reference.
