# Engineering Assurance Ledger v4

| Initial finding | v4 control |
|---|---|
| RAG grounding contract could be bypassed | strict-only policy plus final `rag_assurance` boundary |
| Streaming showed provisional generated text | provisional streaming disabled by default and final-only event |
| Vector index was only inspected | explicit ANN index command + EXPLAIN plan command |
| Production gate could omit staging prerequisites | staging contract gate |
| Ingestion module remained a hot spot | public-task contract protects future split without breaking Celery names |
| RAG benchmark lacked deterministic execution | contract benchmark runner and versioned engineering cases |
| Release/runbook requirements were scattered | final assurance document and checklist |

Expert legal validation remains a separate data-governance requirement and is intentionally not fabricated by this patch.
