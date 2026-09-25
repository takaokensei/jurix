# SAPL e produção

## Sincronização incremental

O agendamento `ingestion.incremental_sync_sapl_task` continua rodando pelo
Celery Beat, mas agora possui um checkpoint persistente por escopo de consulta.
O cursor é atualizado depois de cada página processada.

O algoritmo não considera a média de similaridade nem qualquer heurística de
RAG para decidir se uma norma mudou. A decisão de alteração vem do hash
SHA-256 do payload SAPL normalizado.

O ponto seguro de parada ocorre quando:

1. a API retorna uma página vazia;
2. a página contém menos registros do que o limite solicitado; ou
3. todos os registros de uma página têm exatamente o mesmo hash já persistido.

Quando o limite de páginas é atingido antes de um ponto seguro, o cursor fica
persistido e a próxima execução continua daquele ponto.

## Sincronização completa

Para verificar desaparecimentos remotos sem apagar dados locais:

```python
from src.apps.ingestion.tasks import full_sync_sapl_task
full_sync_sapl_task.delay(limit=100)
```

Ao concluir uma varredura completa, normas locais com `sapl_id` que não foram
observadas no SAPL recebem `needs_review=True` e uma mensagem explícita em
`processing_error`. Nenhuma norma é apagada automaticamente.

## Concorrência

Cada escopo possui um lease persistido em PostgreSQL. Uma segunda execução
enquanto o lease está válido retorna `busy` e não inicia outra varredura.

## Produção Docker

O compose de produção está em:

```text
docker-compose.prod.yml
```

Ele exige explicitamente `POSTGRES_PASSWORD`, `DJANGO_SECRET_KEY`,
`ALLOWED_HOSTS` e `OLLAMA_BASE_URL`, executa Gunicorn com `gthread`, não
faz bind-mount do código da aplicação e não usa o volume do Beat.

Inicialização:

```bash
cp .env.production.example .env
# edite os secrets antes de iniciar
docker compose --env-file .env -f docker-compose.prod.yml up -d --build
```

Validação:

```bash
docker compose --env-file .env -f docker-compose.prod.yml config
docker compose --env-file .env -f docker-compose.prod.yml ps
```

O `config` deve ser executado antes do deploy para detectar variáveis
obrigatórias ausentes.
