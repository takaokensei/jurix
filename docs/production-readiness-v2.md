# Jurix production readiness contract

This document defines the operational bar for the current repository. It is
intentionally stricter than “the test suite is green”.

## 1. Repository integrity

Before release, all of the following must pass:

```text
ruff check src/
ruff format --check src/
python manage.py check --deploy
python manage.py makemigrations --check --dry-run
pytest src/tests/
```

The release gate also checks that production Compose requires the Django secret,
contains no literal database password, persists `/app/data` for single-host local
storage, and documents the required environment variables.

## 2. Secrets and Django security

Production must use:

- `DEBUG=False`;
- a private `DJANGO_SECRET_KEY`;
- explicit `ALLOWED_HOSTS`;
- non-development PostgreSQL credentials;
- Redis-backed cache rather than `LocMemCache`;
- HTTPS and secure cookies when served over HTTPS;
- an explicit CSRF trusted-origin policy where needed.

The Django system check in `src/apps/operations/checks.py` exists to make these
invariants executable instead of leaving them as documentation only.

## 3. Attachment durability

`AttachmentRecord` metadata is stored in PostgreSQL while bytes are stored via
the configured storage backend.

For a single Compose host, local storage must live below the persistent
`jurix_data` volume. For multi-host or horizontally scaled deployments, use S3 or
another shared object store. Do not assume a container filesystem is durable.

Run the existing attachment audit periodically:

```text
python manage.py audit_attachment_storage --verify-hash --fail-on-missing
```

The audit is intentionally read-only. Cleanup should be a separate, reviewed
operation rather than an implicit side effect of an integrity check.

## 4. OCR resource bounds

Every external-document path must have resource limits. The current SAPL OCR
worker is protected by `SAPL_OCR_MAX_PAGES`; the default production value is 200.
A document above the configured limit is marked for review instead of consuming
unbounded worker resources.

Any new parser or OCR path must add equivalent limits for:

- bytes downloaded;
- pages or records processed;
- wall-clock time;
- subprocess CPU/memory where applicable.

## 5. LLM configuration

The generation service must use `settings.OLLAMA_MODEL` when the caller does not
provide a model explicitly. Production should pin both generation and embedding
models, because changing either one can change retrieval or answer quality.

The endpoint protections are treated as defense in depth:

```text
question length
k limit
model allow-list
rate limit
retrieval limits
source validation
claim grounding
```

None of these controls alone is a proof of legal correctness.

## 6. RAG quality gate

The RAG release gate requires a reviewed benchmark contract. The repository does
not invent legal test cases because that would create false confidence.

The benchmark must pin:

1. a corpus hash;
2. embedding model;
3. generation model;
4. minimum case count;
5. protected metrics;
6. baseline metrics.

At minimum, protect retrieval recall, MRR, citation precision/recall and
claim-level groundedness.

A regression checker is already present in the repository. The new manifest
validator prevents a baseline from being silently reused with a different corpus
or model.

## 7. Grounding interpretation

The current grounding service is a deterministic lexical/structural heuristic:
claim tokens, numeric tokens and citation references are checked against retrieved
evidence. It is useful as an audit signal, but it must not be described as a
semantic proof or a calibrated legal-confidence score.

Future semantic evaluation should be added as a benchmark layer rather than
changing this invariant silently.

## 8. Release workflow

The recommended release order is:

```text
CI green
  -> production config check
  -> migrations check
  -> storage audit
  -> RAG benchmark contract
  -> RAG regression
  -> performance smoke
  -> staging deploy
  -> health/readiness checks
  -> release tag
```

The new `Production Gates` workflow is intentionally triggered manually and on
version tags. It is a release gate, not a replacement for ordinary pull-request
CI.

## 9. Architecture debt tracking

Large Python modules are reported by `scripts/check_hotspots.py`. The check is
informational so that splitting a module does not become a risky drive-by rewrite.
For each refactor, preserve behavior with focused tests before moving code.

## 10. Operational SLOs to establish

Before a public production launch, record measured targets for:

- HTTP availability;
- p95 search latency;
- p95 first-token RAG latency;
- p95 complete-response latency;
- Celery queue age;
- OCR failure rate;
- SAPL synchronization failure rate;
- attachment audit failures;
- RAG grounding failure rate.

The application already has observability dependencies and health endpoints. The
next step is to connect those signals to dashboards and alerts owned by the
runtime environment.
