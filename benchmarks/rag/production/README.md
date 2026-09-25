# Production RAG benchmark

This directory defines the contract for the benchmark that is allowed to block
a Jurix production release.

The repository intentionally does **not** ship fabricated legal answers. The
production dataset must be built from a reviewed corpus and versioned together
with the model configuration used to create its baseline.

## Case format

Each JSONL row must contain:

- `id`: stable case identifier.
- `question`: reviewed user question.
- `expected_sources`: source identifiers that should be retrievable.
- `answerability`: `answerable` or `unanswerable`.

Additional fields can record expected citation spans, dates, jurisdiction, or
manual evaluator notes, but the stable minimum contract is above.

## Required baseline metadata

`manifest.json` must pin:

- corpus hash;
- embedding model;
- generation model;
- minimum case count;
- protected retrieval and grounding metrics.

Use `scripts/validate_rag_benchmark.py` before publishing a baseline. Then run
`scripts/check_rag_regression.py` against the baseline and current metrics.

A release is not considered production-ready until the reviewed corpus and its
baseline are present. The gate can enforce that requirement with
`--require-rag`.
