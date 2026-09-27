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

### Auditoria parcial de contraste — tema escuro

Em 2026-09-27 foram calculados os pares dos tokens principais do workspace
contra suas superfícies: `#F8FAFC`/`#081220` = 17,96:1,
`#94A3B8`/`#081220` = 7,33:1, `#60A5FA`/`#081220` = 7,39:1 e
`#3B82F6`/`#081220` = 5,11:1. O uso de `#64748B` como texto pequeno tinha
3,95:1 e foi substituído pelo token de texto muted no workspace.

Essa medição cobre tokens e componentes auditados nesta etapa; não constitui
uma declaração de conformidade WCAG da aplicação inteira. Permanecem pendentes
os componentes legados, estados claros/escuros alternativos e uma auditoria
automatizada de todas as combinações efetivamente renderizadas.
