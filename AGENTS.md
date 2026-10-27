# AGENTS.md — Guia Operacional para Agentes Autônomos (Jurix)

O **Jurix** é o sistema de consulta de normas municipais de Natal/RN em texto consolidado para a Procuradoria-Geral do Município (PGM), com motor determinístico de consolidação (`REVOGA`, `ALTERA`, `ADICIONA`, `SUBSTITUI`) e política *fail-closed*. O escopo e critérios do MVP estão em [`docs/mvp.md`](docs/mvp.md).

Para APIs de Django, Celery, pgvector e HTMX, consulte a documentação oficial da versão fixada em requirements.txt.

## 1. Leitura Obrigatória no Início de Sessão

1. Leia [`STATE.md`](STATE.md) para entender o estado real do sistema, falhas conhecidas e bloqueadores.
2. Identifique o campo `tarefa_atual` no [`STATE.md`](STATE.md). Não leia o backlog inteiro: consulte em [`docs/backlog.md`](docs/backlog.md) apenas a tarefa indicada em `tarefa_atual`.
3. Leia [`docs/mvp.md`](docs/mvp.md) para respeitar os limites do MVP e a regra *fail-closed*.
4. **Não leia** `docs/archive/`, `docs/ui-audit/`, `staticfiles/` ou `node_modules/`.

## 2. Comandos de Validação Rápida

Use o ambiente Python em `../jurix-venv` (`L:\jurix-venv` ou `../jurix-venv/bin/python`):

```bash
python scripts/validate_documentation_contract.py
python scripts/validate_release_contract.py
python scripts/validate_staging_contract.py
python manage.py check
python manage.py makemigrations --check --dry-run
ruff check <arquivos_tocados>
ruff format --check <arquivos_tocados>
pytest src/tests/<arquivo_de_teste>.py -q -p no:cacheprovider --tb=short
node --test --test-concurrency=1 tests/js/<arquivo>.test.mjs
```

Variáveis mínimas para Django/pytest: `DJANGO_SETTINGS_MODULE=config.settings`, `DJANGO_SECRET_KEY=test-secret-key-for-ci`, `DEBUG=False`, `JURIX_SINGLE_HOST=True`.

## 3. Regras Invioláveis de Escopo e Segurança

- **Uma tarefa por branch**: trabalhe apenas no escopo da `tarefa_atual`.
- **Commits atômicos**: use Conventional Commits. Para desfazer um commit seu, use `git revert`. Nunca reescreva histórico (`rebase`, `reset --hard`, `commit --amend`, `filter-repo`).
- **Proibido alterar remoto sem ordem explícita**: nunca execute `git push`, tags ou releases.
- **Segredos e `.env`**: nunca abra, imprima ou altere `.env` (exceto `*.example`), chaves privadas ou tokens.
- **Histórico congelado**: o diretório `docs/archive/` é congelado após a reorganização; nunca edite, adicione ou mova arquivos nele.
- **Workflows protegidos**: `.github/workflows/` só muda pelas tarefas T-007 ou T-011.
- **Binários de QA proibidos**: nunca versione novos screenshots, PDFs ou artefatos binários de teste.
- **Graphify**: nunca rode `graphify <plataforma> install` nem `graphify hook install`; use apenas `graphify update` quando solicitado.
- **Dependências travadas**: não altere `requirements.txt`, `uv.lock`, `package-lock.json` nem `pyproject.toml`.

## 4. Mapa do Repositório

- `src/processing/` — Ingestão de DOM, extração estruturada de eventos normativos e motor `consolidation_engine.py`.
- `src/llm_engine/` — Pipeline de busca vetorial, reranking, contexto e clientes de LLM.
- `src/apps/legislation/` — Modelos centrais de legislação, normas, dispositivos, views e templates HTMX.
- `src/apps/core/` — Configurações compartilhadas da aplicação, rotas base, assets estáticos e templates globais.
- `src/apps/ingestion/` e `src/apps/operations/` — Tasks Celery, pipelines de carga e monitoramento operacional.
- `src/clients/` — Clientes de integração externa com Diário Oficial (`dom_natal`) e catálogo legislativo (`sapl`).
- `src/observability/` — Logging estruturado, métricas e tracing do sistema.
- `src/tests/` — Suíte de testes Python (`pytest`).
- `tests/js/` — Suíte de testes JavaScript (`node --test`).
- `scripts/` — Gates de contrato (`validate_*_contract.py`) e auditorias operacionais.
- `docs/` — Contratos ativos, [`docs/mvp.md`](docs/mvp.md), [`docs/backlog.md`](docs/backlog.md) e índice em [`docs/README.md`](docs/README.md).
