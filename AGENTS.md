# AGENTS.md — Guia Operacional para Agentes Autônomos (Jurix)

O **Jurix** é o sistema de consulta de normas municipais de Natal/RN em texto consolidado para a Procuradoria-Geral do Município (PGM), com motor determinístico de consolidação (`REVOGA`, `ALTERA`, `ADICIONA`, `SUBSTITUI`) e política *fail-closed*. A definição do produto e os critérios do MVP estão em [`docs/mvp.md`](docs/mvp.md).

## 1. Leitura Obrigatória no Início de Sessão

1. Leia [`STATE.md`](STATE.md) para entender o estado real dos subsistemas, falhas conhecidas do baseline e bloqueadores.
2. Leia [`docs/mvp.md`](docs/mvp.md) para respeitar os limites do MVP e a regra *fail-closed*.
3. Leia apenas a **primeira tarefa pronta** em [`docs/backlog.md`](docs/backlog.md) (começando por `T-009`).
4. **Não leia** `docs/archive/`, `docs/ui-audit/`, `staticfiles/` ou `node_modules/`.

## 2. Comandos de Validação Rápida

Use o ambiente Python em `../jurix-venv` (`L:\jurix-venv` ou `../jurix-venv/bin/python`):

```bash
# 1. Contratos obrigatórios de documentação, release e staging (devem sair com 0)
python scripts/validate_documentation_contract.py
python scripts/validate_release_contract.py
python scripts/validate_staging_contract.py

# 2. Check estático do Django e migrações
python manage.py check
python manage.py makemigrations --check --dry-run

# 3. Lint e formatação apenas nos arquivos tocados
ruff check <arquivos_tocados>
ruff format --check <arquivos_tocados>

# 4. Testes unitários Python do módulo tocado
pytest src/tests/<arquivo_de_teste>.py -q -p no:cacheprovider --tb=short

# 5. Teste unitário JS isolado (quando tocar em frontend/JS)
node --test --test-concurrency=1 tests/js/<arquivo>.test.mjs
```

Variáveis mínimas para comandos Django/pytest em ambiente local/CI sem `.env`:
`DJANGO_SETTINGS_MODULE=config.settings`, `DJANGO_SECRET_KEY=test-secret-key-for-ci`, `DEBUG=False`, `JURIX_SINGLE_HOST=True`.

## 3. Regras Invioláveis de Escopo e Segurança

- **Uma tarefa por branch**: crie ou trabalhe apenas no escopo da tarefa selecionada em `docs/backlog.md`.
- **Commits atômicos**: use Conventional Commits (`feat:`, `fix:`, `test:`, `docs:`, `chore:`, `refactor:`). Para desfazer um commit seu, use `git revert`. Nunca reescreva histórico (`rebase`, `reset --hard`, `commit --amend`, `filter-repo`).
- **Proibido publicar ou alterar remoto sem ordem explícita**: nunca execute `git push`, nunca crie/altere/apague tags ou releases e nunca altere configurações do GitHub.
- **Segredos e `.env`**: nunca abra, imprima ou altere `.env` (exceto `*.example`), chaves privadas, tokens ou credenciais.
- **Histórico congelado**: nunca edite nem mova arquivos dentro de `docs/archive/`.
- **Binários de QA proibidos**: nunca versione novos screenshots, PDFs ou artefatos binários de auditoria/QA em `docs/` ou na raiz (decisão D1).
- **Graphify**: nunca rode `graphify <plataforma> install` nem `graphify hook install`; use apenas `graphify update` quando solicitado.
- **Dependências travadas**: não altere `requirements.txt`, `uv.lock`, `package-lock.json` nem `pyproject.toml` sem tarefa explícita.

## 4. Mapa do Repositório

- `src/processing/` — Ingestão de DOM, extração estruturada de eventos normativos e motor `consolidation_engine.py`.
- `src/rag/` — Indexação pgvector, busca híbrida, reranking e gates de citação normativa.
- `src/core/` e `src/legal_docs/` — Modelos centrais, views Django/HTMX, autenticação e APIs.
- `src/templates/` e `src/static/` — Templates HTML/HTMX, CSS e módulos JS do cliente.
- `src/tests/` — Suíte Python/Django (`pytest`).
- `tests/js/` — Suíte JavaScript (`node --test`).
- `scripts/` — Gates de contrato (`validate_*_contract.py`), auditoria e automação operacional.
- `docs/` — Contratos ativos, [`docs/mvp.md`](docs/mvp.md), [`docs/backlog.md`](docs/backlog.md) e índice em [`docs/README.md`](docs/README.md).
