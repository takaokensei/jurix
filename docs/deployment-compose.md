# Docker Compose — matriz canônica

Há três arquivos Compose por intenção. Não use os três simultaneamente.

| Arquivo | Intenção | Uso |
|---|---|---|
| `docker-compose.yml` | base/canonical | referência comum e desenvolvimento simples |
| `docker-compose.dev.yml` | desenvolvimento | bind mounts, debug e ciclo rápido |
| `docker-compose.prod.yml` | produção | serviços/configuração de produção |

## Regra

Mudanças compartilhadas devem começar no `docker-compose.yml`. Os arquivos `dev` e `prod`
devem conter apenas diferenças específicas do ambiente.

Para produção, siga também `docs/production-readiness.md` e valide o ambiente com os gates
do CI; um Compose válido não é evidência de readiness operacional.
