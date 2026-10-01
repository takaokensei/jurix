# Stack descartável de integração

Esta stack existe somente para testes de integração isolados com PostgreSQL/pgvector,
Redis e Celery. Ela não lê `.env`, não monta `data/`, não inicia Celery Beat e não
usa os nomes de volume/contêiner da stack normal. As portas publicadas são
PostgreSQL `127.0.0.1:55432` e Redis `127.0.0.1:16380`; confira ambas antes de iniciar.

Os valores de senha e `DJANGO_SECRET_KEY` no Compose são fixtures locais sem valor
fora desta stack descartável. Não os reutilize em qualquer ambiente compartilhado.

## Verificar antes de iniciar

Na raiz do repositório, examine os serviços e mounts efetivos:

```powershell
docker compose -p jurix-audit -f docker-compose.audit.yml config --quiet
docker ps --format "table {{.Names}}\t{{.Ports}}"
Get-NetTCPConnection -State Listen -LocalPort 55432,16380 -ErrorAction SilentlyContinue
```

Se qualquer porta estiver ocupada, não inicie. Não altere a stack normal para
liberar portas.

## Iniciar e verificar

```powershell
docker compose -p jurix-audit -f docker-compose.audit.yml up -d db redis worker
docker compose -p jurix-audit -f docker-compose.audit.yml ps
```

O projeto Compose `jurix-audit` prefixa recursos e o volume persistente de teste.
O worker tem concorrência 1 e nenhum scheduler. Testes host devem apontar
explicitamente a `127.0.0.1:55432/jurix_audit`; nunca herdar `DATABASE_URL` de
`.env`. Se executar migrations, imprima apenas nome do banco/host não sensíveis
para confirmar o destino.

## Parar e preservar

Depois dos testes, pare somente os serviços audit:

```powershell
docker compose -p jurix-audit -f docker-compose.audit.yml stop
```

Não use `down -v`, `docker volume prune` ou remoção manual de volumes. Para apagar
dados de auditoria futuramente, identifique primeiro o nome completo do volume
`jurix-audit_audit_pgdata` com `docker volume inspect` e peça autorização explícita.
