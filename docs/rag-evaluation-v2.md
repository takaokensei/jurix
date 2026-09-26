# RAG Evaluation v2

## Scope

The Jurix RAG stack combines:

- pgvector retrieval;
- Ollama embeddings;
- Ollama generation;
- strict deterministic grounding;
- citation and numeric checks;
- corpus-versioned caching.

The evaluation contract measures retrieval and answer integrity separately.

## Retrieval metrics

### recall@1

The proportion of cases where at least one expected source appears in the first
retrieved result.

### recall@3

The proportion of cases where at least one expected source appears in the first
three retrieved results.

### MRR

Mean reciprocal rank of the first expected source.

A high recall score does not imply that the generated answer is correct. It only
says that relevant material was retrieved.

## Citation metrics

Citation precision measures the fraction of generated citation references that
are actually expected for the reviewed case.

Citation recall measures the fraction of expected references that were preserved
in the generated response.

## Groundedness

Groundedness is calculated from the strict deterministic evidence report. The
report verifies:

- lexical overlap;
- numeric consistency;
- citation presence;
- negation compatibility;
- certainty/condition compatibility.

This is deliberately not marketed as semantic entailment.

## Test categories

Every reviewed benchmark should target several categories.

### Direct lookup

The answer should map cleanly to one or more exact provisions.

### Cross-reference

The answer should identify a source that references another provision.

### Negative answer

The correct behavior is to decline when the corpus lacks sufficient support.

### Temporal question

The answer must not silently substitute a current rule for a historical one.

### Numeric constraint

A claim containing a date, amount, percentage or period must be supported by the
retrieved evidence.

### Citation integrity

The generated reference should resolve to the retrieved source.

### Adversarial phrasing

The user wording should not change the evidence boundary.

## Release rule

Do not publish a model/corpus combination merely because one metric improved.
Record the full metric vector and compare against the previous release.

A release should be rejected when any non-negotiable metric falls below the
baseline tolerance or when a new safety regression appears.
