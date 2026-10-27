# Checklist de engenharia v3

## Aplicação

- [ ] settings de produção carregam secrets sem defaults inseguros
- [ ] ALLOWED_HOSTS explícito
- [ ] cache Redis
- [ ] Ollama configurado
- [ ] allowlist de modelos
- [ ] rate limit atrás de proxy configurado

## Banco

- [ ] migrations aplicadas
- [ ] pgvector instalado
- [ ] HNSW presente
- [ ] EXPLAIN ANALYZE arquivado
- [ ] pool de conexão dimensionado

## Storage

- [ ] backend conhecido
- [ ] volume persistente ou S3
- [ ] audit sem missing
- [ ] hash check periódico
- [ ] prune dry-run antes de executar

## Ingestão

- [ ] limite de páginas
- [ ] limite de bytes
- [ ] timeout de download
- [ ] retry com backoff
- [ ] filas separadas
- [ ] tarefas idempotentes

## RAG

- [ ] retrieval híbrido
- [ ] filtro temporal/status
- [ ] grounding estrito
- [ ] no-answer testado
- [ ] benchmark revisado
- [ ] cache só após aceitação

## Frontend

- [ ] teclado
- [ ] leitor de tela
- [ ] foco visível
- [ ] erro de API legível
- [ ] streaming interrompido
- [ ] mobile

## Observabilidade

- [ ] métricas
- [ ] tracing
- [ ] logs estruturados
- [ ] alertas
- [ ] dashboards

## Release

- [ ] CI verde
- [ ] production validation verde
- [ ] docker build
- [ ] staging
- [ ] backup
- [ ] rollback
