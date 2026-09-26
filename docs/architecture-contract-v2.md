# Jurix Architecture Contract v2

## Dependency direction

The preferred dependency flow is:

```text
HTTP/views
  -> application services
  -> domain/data models

background tasks
  -> application services
  -> domain/data models

RAG
  -> retrieval
  -> policy/grounding
  -> LLM transport

infrastructure
  -> storage/cache/database/telemetry
```

Web handlers should not become the only place where business policy lives.

## Size budgets

The initial budgets are deliberately advisory but visible:

| Module | Budget |
| --- | ---: |
| `api_views.py` | 900 |
| `tasks.py` | 1100 |
| `rag_service.py` | 850 |
| `sapl_client.py` | 550 |

The goal is not to punish large files. The goal is to trigger a deliberate
refactor before another integration wave creates an opaque hotspot.

## RAG boundary

The RAG implementation must preserve:

1. source retrieval;
2. evidence formatting;
3. LLM invocation;
4. deterministic grounding;
5. release policy;
6. cache eligibility.

Do not bypass the evidence policy from a new API endpoint.

## Ingestion boundary

SAPL client code should only know how to communicate with SAPL. Transformation
belongs to application services. Celery tasks should remain orchestration
units rather than becoming HTTP clients plus parsers plus persistence layers.

## Change review

A feature that changes answer semantics requires:

- benchmark impact;
- cache behavior review;
- source/citation review;
- migration review if models change;
- operational runbook update if a new dependency appears.
