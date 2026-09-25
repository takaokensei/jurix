# Estado atual do projeto

Esta página é a fonte de status de engenharia. Roadmaps históricos no README não
devem contradizer esta página.

## Infraestrutura

- Django: implementado.
- PostgreSQL/pgvector: implementado.
- Redis/Celery: implementado.
- Ollama: implementado.
- Storage local/S3: implementado.
- Gates de produção: implementados.

## Qualidade RAG

- Retrieval híbrido: implementado.
- Grounding determinístico original: implementado.
- Grounding estrito v2: implementado neste hardening.
- Benchmark jurídico revisado: **pendente de dados e aprovação humana**.

## Performance

- Cache de embeddings/respostas: implementado.
- Índice vetorial: deve ser verificado/criado com `ensure_vector_index`.
- Benchmark operacional de pgvector: disponível.

## Operação

- Auditoria de storage: read-only.
- Limpeza de anexos expirados: comando separado, dry-run por padrão.
- Configuração de produção: validada por checks Django.

## UX

A interface existente deve ser validada manualmente em teclado, leitor de tela,
mobile, erro de dependência e streaming interrompido. Este repositório não deve
atribuir conformidade WCAG sem evidência de auditoria.
