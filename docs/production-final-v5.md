# Production final v5

Este pacote fecha os três pontos restantes de assurance:

1. benchmark jurídico baseado em legislação federal real e fontes oficiais;
2. gate bloqueante que inspeciona índice pgvector e `EXPLAIN` real;
3. refatoração de superfície do pipeline de ingestão, com facade pública estável.

## Benchmark jurídico

Os casos de `benchmarks/rag/legal/v1/cases.jsonl` apontam para fontes oficiais do Planalto e incluem perguntas sobre CPC, Constituição, CDC, ECA, ação civil pública e Estatuto da Advocacia. A avaliação é de engenharia; revisão jurídica humana continua sendo requisito de release.

Execute contra staging com `JURIX_BENCHMARK_URL`.

## Vector gate

`vector_production_gate_v5.py --strict` descobre colunas pgvector, exige HNSW ou IVFFlat com `vector_cosine_ops` e confirma via `EXPLAIN (FORMAT JSON)` que a consulta de vizinhança realmente usa índice. Qualquer falha retorna código diferente de zero.

## Ingestion refactor

Execute uma vez:

```powershell
python scripts/refactor_ingestion_tasks_v5.py --apply
python scripts/verify_ingestion_refactor_v5.py
```

O módulo grande vira `tasks_legacy.py`; `tasks.py` passa a ser uma fachada compatível e as tasks ficam expostas por módulos de domínio. A implementação interna não é reescrita mecanicamente, reduzindo risco de regressão sem alterar nomes Celery existentes.

## Gate final

```powershell
python scripts/final_production_gate_v5.py
```
