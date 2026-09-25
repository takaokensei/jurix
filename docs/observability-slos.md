# Observabilidade e SLOs

## Métricas

### HTTP

- requests por rota;
- erros 4xx/5xx;
- latência p50/p95/p99;
- conexões SSE abertas e encerradas.

### RAG

- retrieval latency;
- generation latency;
- cache hit/miss;
- grounding accepted/rejected;
- `no_retrieval`;
- número de fontes;
- tamanho de contexto.

### Celery

- tamanho das filas;
- idade da tarefa mais antiga;
- duração por tipo;
- retries;
- falhas permanentes.

### Storage

- bytes armazenados;
- objetos expirados;
- missing objects;
- hash mismatch.

## Alertas

Um alerta deve apontar para uma ação operacional. Evite alertas com base em
valores absolutos sem considerar o tráfego. Para RAG, especialmente, uma queda
na groundedness deve disparar investigação do corpus/modelo e não ser mascarada
por um fallback silencioso.
