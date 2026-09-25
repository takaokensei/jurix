# Plano de release 1.2

## Critérios de entrada

- branch principal verde;
- testes Python e JS verdes;
- production gate verde;
- benchmark RAG revisado disponível;
- storage audit sem missing objects;
- índice pgvector presente;
- configuração de produção sem warnings críticos.

## Critérios de saída

- tag assinada;
- changelog atualizado;
- backup do PostgreSQL validado;
- staging smoke test executado;
- rollback documentado;
- métricas e alertas ativos.

## Rollback

O rollback precisa preservar migrações compatíveis e não remover objetos de
storage. Limpeza de anexos não faz parte de um rollback automático.
