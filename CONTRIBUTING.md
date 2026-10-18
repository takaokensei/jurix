# Contributing to Jurix

Jurix is a research prototype for traceable municipal-law discovery and temporal comparison. Changes that affect legal identity, amendments, repeal, effective dates, or consolidated wording must preserve source provenance and must not turn an automated candidate into a reviewed legal conclusion.

## Local development and isolated QA

Use the documented Docker QA profile for an isolated web/database/storage environment. From the repository root in PowerShell:

```powershell
# Identidade visível do build QA (não são credenciais).
$env:JURIX_BUILD_VERSION = 'local-qa'
$env:JURIX_BUILD_REVISION = (git rev-parse --short HEAD).Trim()

docker compose -p jurix-normative-qa -f docker-compose.audit.yml up -d --build db redis web worker
docker compose -p jurix-normative-qa -f docker-compose.audit.yml exec -T web python manage.py migrate --noinput
docker compose -p jurix-normative-qa -f docker-compose.audit.yml ps
Invoke-WebRequest http://127.0.0.1:8287/api/v1/health/ready/
docker compose -p jurix-normative-qa -f docker-compose.audit.yml exec -T web python manage.py check
docker compose -p jurix-normative-qa -f docker-compose.audit.yml exec -T worker celery -A config inspect ping --timeout=5
```

The profile serves `http://127.0.0.1:8287/` and uses its own QA database and named volumes. The ready endpoint should report the database, pgvector, Redis, and migrations as ready; Ollama/corpus may be `skipped` when the corresponding check is not configured. A Celery `pong` confirms worker reachability only, not that a task completed. Do not point this profile at a product database or replace its settings with values copied from a local `.env`. Stop services without deleting QA volumes:

```powershell
docker compose -p jurix-normative-qa -f docker-compose.audit.yml stop
```

For Python development outside Docker, create a virtual environment and install the application's dependencies from `requirements.txt` (the current `pyproject.toml` does not declare those dependencies, so `uv sync --frozen` alone is not an environment setup):

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

The default test suite is configured in `pyproject.toml`; run the narrowest relevant tests first, then the broader suite when practical. The isolated QA database is not a portable fixture or a substitute for a fresh-install test. Its locally staged public PDFs and resulting extractions are not included in a clean checkout. Tests that require PostgreSQL/Django are not equivalent to legal review. If a required service is unavailable, report that flow as untested rather than inferring success.

The reusable page examples are `http://127.0.0.1:8287/assistente/?new=1` (choose **Acervo documental (em revisão)** for local PDF candidates) and `http://127.0.0.1:8287/explorar/demo-consolidacao/` (the LC 258/2024 demonstration). The first route requires candidate documents to have been staged in that QA database; a clean QA volume will not contain the locally held archive. In both flows, an extraction or relation marked as a candidate is not a reviewed legal conclusion.

## Source and review safeguards

- Keep downloaded documents, database files, `.env` files, credentials, and user/process data out of commits.
- Preserve source documents and extraction versions as immutable evidence. Do not overwrite an extraction to hide a correction; create a new version through the application workflow.
- Keep archive, SAPL, and gazette candidates visibly distinct from reviewed documents. Do not approve, link, promote, or describe a candidate as current law without the authorized human review required by the project.
- For every legal-change claim, retain the exact source, provision, target, publication/effective-date evidence, review state, and uncertainty. “Mentioned by a later act” alone is not proof of repeal or current effect.
- Keep projects of law separate from enacted-law retrieval unless the task explicitly concerns proposals.
- Do not run destructive migrations, clear volumes, or use real product data in development checks.

## Pull request notes

Describe the user-visible change, affected routes/modules, source/review implications, and how it was verified. Include only synthetic or redistributable screenshots and sample data. State which checks were not run and why. Never claim legal accuracy from software tests alone.

## Current maturity

The project is not production-ready for legal decisions. The current QA archive contains unreviewed candidate documents; extraction completion is a technical status, not legal validation. Research metrics require an independently reviewed/adjudicated gold set and observed users, as specified in the project’s research plans.
