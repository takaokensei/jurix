# Production readiness v3

## Bloqueadores de release

A release é bloqueada quando qualquer item abaixo falha:

- checks Django de deploy;
- migrations pendentes;
- banco indisponível;
- pgvector ausente;
- índice HNSW não verificado no ambiente alvo;
- storage inconsistente em auditoria;
- credenciais de produção ausentes;
- RAG benchmark abaixo da baseline;
- grounding estrito desligado em produção;
- cobertura mínima do CI não atingida;
- Docker Compose de produção inválido.

## Storage

Single-host pode usar volume persistente local. Ambientes com múltiplas réplicas
ou múltiplos hosts devem usar S3/MinIO. A troca de backend precisa ser acompanhada
de auditoria de objetos antes do cutover.

## Database

O índice HNSW deve ser criado com `python manage.py ensure_vector_index --create`
fora de uma transação durante manutenção. Depois disso, a busca deve ser medida
com o benchmark real do corpus.

## OCR

O número máximo de páginas é apenas a primeira proteção. O download remoto deve
ser limitado em bytes e com timeout; a renderização deve evitar DPI excessivo em
documentos excepcionais; jobs longos devem ficar em uma fila dedicada.

## Observabilidade

SLOs recomendados:

| Sinal | Alvo inicial |
|---|---:|
| HTTP p95 | < 500 ms sem LLM |
| busca vetorial p95 | < 250 ms |
| readiness | 100% em horário operacional |
| erro Ollama | < 1% |
| falha grounding | acompanhar tendência, não mascarar |
| fila Celery | < 60 s para tarefas interativas |

Os valores acima são critérios operacionais iniciais, não alegações de desempenho
atual do projeto.

## Release checklist

1. `ruff check`;
2. `ruff format --check`;
3. `pytest`;
4. migrations check;
5. `validate_release_contract.py`;
6. auditoria de storage;
7. índice pgvector;
8. benchmark vetorial;
9. benchmark RAG revisado;
10. build Docker;
11. staging;
12. smoke test;
13. tag de release;
14. backup verificado;
15. deploy.
