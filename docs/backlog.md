# Backlog de Engenharia (Agentes Autônomos)

Tarefas pequenas, independentes e verificáveis com status explícito.

---

## T-009 — Testes fim a fim do motor de consolidação e regra *fail-closed*

- **ID**: `T-009`
- **Status**: PRONTA (Primeira tarefa para agente / `tarefa_atual`)
- **Objetivo**: Ampliar `src/tests/test_consolidation_engine.py` (que hoje testa `REVOGA`, `ALTERA`, `ADICIONA` e `REGULAMENTA` em classes separadas) adicionando um teste integrado fim a fim que aplique, sobre uma mesma norma-base, eventos `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` em ordem cronológica estrita, além de validar explicitamente a regra *fail-closed* quando houver evento com `validado=False` na cadeia modificadora.
- **Arquivos prováveis**:
  - `src/tests/test_consolidation_engine.py`
  - `src/processing/consolidation_engine.py` (somente leitura; não alterar comportamento na tarefa de teste)
- **Comando de verificação**:
  ```bash
  pytest src/tests/test_consolidation_engine.py -q -p no:cacheprovider --tb=short
  ruff check src/tests/test_consolidation_engine.py
  ```
- **Critério de pronto**:
  1. Novo teste fim a fim cobre simultaneamente `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` ordenados por `data_publicacao`.
  2. Asserção explícita comprova que evento com `validado=False` não é aplicado silenciosamente como texto vigente (*fail-closed*).
  3. Todos os testes de `src/tests/test_consolidation_engine.py` passam com código `0`.
- **Dependências**: Nenhuma.

---

## T-001 — Reescrever `README.md` da raiz (~150 linhas)

- **ID**: `T-001`
- **Status**: PRONTA
- **Objetivo**: Substituir o `README.md` monolítico de 47 KB por um documento conciso (~150 linhas) com visão de produto, comandos essenciais e links para `docs/README.md`.
- **Arquivos prováveis**:
  - `README.md`
- **Comando de verificação**:
  ```bash
  wc -l README.md
  python scripts/validate_documentation_contract.py
  ```
- **Critério de pronto**: `README.md` com $\le 150$ linhas e contratos de documentação passando com código `0`.
- **Dependências**: Nenhuma.

---

## T-002 — Limpeza física de binários no histórico Git (`git filter-repo`)

- **ID**: `T-002`
- **Status**: BLOQUEADA (Requer janela combinada e autorização expressa do dono; não executável por agentes autônomos. Texto completo em `docs/agents/blocked/T-002.md`).

---

## T-003 — Adjudicação humana do Corpus Ouro da PGM

- **ID**: `T-003`
- **Status**: BLOQUEADA POR HUMANO (PGM / Jurídico — tarefa exclusiva de validação institucional humana, excluída de qualquer lista de escolha de trabalho para agentes autônomos).
- **Objetivo**: Conduzir a homologação jurídica das normas-piloto conforme `docs/research/PGM_GOLD_ADJUDICATION.md`.
- **Arquivos prováveis**:
  - `docs/research/PGM_GOLD_ADJUDICATION.md`
- **Comando de verificação**:
  ```bash
  python scripts/validate_documentation_contract.py
  ```
- **Critério de pronto**: Validação protocolada por procuradores da PGM (`validado=True`).
- **Dependências**: Equipe jurídica da PGM.

---

## T-004 — Formatação global `ruff` em `src/` em PR dedicado

- **ID**: `T-004`
- **Status**: AGUARDA APROVAÇÃO DO DONO
- **Objetivo**: Aplicar `ruff format src/` (204 arquivos) e sanear avisos de `ruff check src/` em PR exclusivo, registrando o commit em `.git-blame-ignore-revs`.
- **Arquivos prováveis**:
  - `src/**/*.py`
  - `.git-blame-ignore-revs`
- **Comando de verificação**:
  ```bash
  ruff check src/
  ruff format --check src/
  ```
- **Critério de pronto**: `ruff check src/` e `ruff format --check src/` saem com código `0`.
- **Dependências**: Aprovação do dono.

---

## T-005 — Corrigir 3 testes JS quebrados por asserção literal de `?v=`

- **ID**: `T-005`
- **Status**: PRONTA
- **Objetivo**: Atualizar as asserções dos 3 testes JS que falham por cobrar query string estática desatualizada (`?v=`), mantendo estritamente a verificação do valor exato de `?v=` e recusando asserções afrouxadas como `includes('?v=')`.
- **Arquivos prováveis**:
  - `tests/js/norma_ui_v3.test.mjs`
  - `tests/js/session-created-toast.test.mjs`
  - `tests/js/sidebar.unification.test.mjs`
- **Comando de verificação**:
  ```bash
  node --test --test-concurrency=1 tests/js/norma_ui_v3.test.mjs
  node --test --test-concurrency=1 tests/js/session-created-toast.test.mjs
  node --test --test-concurrency=1 tests/js/sidebar.unification.test.mjs
  ```
- **Critério de pronto**: Os 3 arquivos saem com código `0`, validando o valor específico da versão sem usar verificação genérica do tipo `includes('?v=')`.
- **Dependências**: Nenhuma.

---

## T-006 — Corrigir ou isolar falhas de `pytest` pós-`collectstatic`

- **ID**: `T-006`
- **Status**: PRONTA
- **Objetivo**: Diagnosticar e sanear as falhas de `pytest` do baseline, separando falhas de serviço externo (Postgres/pgvector/Redis ausentes em dev), que devem ser anotadas com `pytest.mark.skip(reason="...")` explícito, de falhas reais de expectativa ou regressão em código/templates, que devem ser corrigidas.
- **Arquivos prováveis**:
  - `src/tests/` (arquivos listados em `STATE.md`)
- **Comando de verificação**:
  ```bash
  python manage.py collectstatic --noinput
  pytest src/tests/ -q -p no:cacheprovider --tb=line -rfE
  ```
- **Critério de pronto**: Zero falhas nos testes com SQLite/CI; falhas que exigem Postgres/Redis explicitamente marcadas com motivo claro de skip.
- **Dependências**: Nenhuma.

---

## T-007 — Consolidar workflows do GitHub Actions e remover branch `develop`

- **ID**: `T-007`
- **Status**: BLOQUEADA até aprovação e verificação de develop com git ls-remote --heads origin develop
- **Objetivo**: Eliminar os workflows duplicados em `.github/workflows/` e remover a referência ao branch inexistente `develop` de `.github/workflows/ci.yml`.
- **Arquivos prováveis**:
  - `.github/workflows/*.yml`
- **Comando de verificação**:
  ```bash
  git ls-remote --heads origin develop
  python scripts/validate_release_contract.py
  python scripts/validate_staging_contract.py
  ```
- **Critério de pronto**: Workflows consolidados, ausência de branch fantasma confirmada e contratos de release verdes.
- **Dependências**: Aprovação do dono e verificação via `git ls-remote`.

---

## T-008 — Separar testes E2E de browser (`real.browser.test.mjs`) e alertar `skipped`

- **ID**: `T-008`
- **Status**: PRONTA
- **Objetivo**: Mover `real.browser.test.mjs` para runner dedicado de E2E, implementar aviso em `tests/js/run-tests.mjs` para arquivos 100% pulados e criar um caso de teste próprio para validar o disparo desse alerta.
- **Arquivos prováveis**:
  - `tests/js/run-tests.mjs`
  - `tests/js/package.json`
  - `tests/js/runner_skipped_alert.test.mjs` (novo teste unitário do runner)
- **Comando de verificação**:
  ```bash
  cd tests/js && npm test
  node --test --test-concurrency=1 tests/js/runner_skipped_alert.test.mjs
  ```
- **Critério de pronto**: Suíte unitária JS executa sem dependência de browser ativo e possui caso de teste próprio validando o alerta de arquivo 100% skipped.
- **Dependências**: Nenhuma.

---

## T-010 — Endpoint/view somente leitura de norma consolidada (*fail-closed*)

- **ID**: `T-010`
- **Status**: BLOQUEADA (Depende de T-001 e T-002)
- **Objetivo**: Expor endpoint/view somente leitura que entregue a norma consolidada estruturada por dispositivo (`VIGENTE`, `ALTERADO`, `REVOGADO`, `NAO_VERIFICADO`), recusando exibir como `VIGENTE` qualquer dispositivo não integralmente validado.
- **Arquivos prováveis**:
  - `src/apps/legislation/views.py`
  - `src/apps/legislation/urls.py`
  - `src/processing/consolidation_engine.py`
  - `src/tests/test_consolidation_view.py`
- **Comando de verificação**:
  ```bash
  pytest src/tests/test_consolidation_engine.py src/tests/test_consolidation_view.py -q -p no:cacheprovider
  ```
- **Critério de pronto**: Retorno com status por dispositivo, fonte oficial DOM e bloqueio fail-closed testado.
- **Dependências**: `T-001, T-002`.

---

## T-011 — CI: Automação, linting e manutenção de workflows do GitHub Actions

- **ID**: `T-011`
- **Status**: PRONTA (`tarefa_atual` — CI consultivo até T-011; diagnóstico é a próxima tarefa de organização)
- **Objetivo**: Estabelecer padronização, automações complementares ou linting de workflows do GitHub Actions (`actionlint`/pinning de actions por hash), preservando a regra de que `.github/workflows/` só muda por T-007 ou T-011.
- **Arquivos prováveis**:
  - `.github/workflows/`
- **Comando de verificação**:
  ```bash
  python scripts/validate_release_contract.py
  python scripts/validate_staging_contract.py
  ```
- **Critério de pronto**: Workflows validados e contratos de release e staging sem falhas.
- **Dependências**: Nenhuma.

---

## T-012 — Acessibilidade e tipografia de rótulos e controles em telas estreitas

- **ID**: `T-012`
- **Status**: PRONTA
- **Objetivo**: Adequar contraste, labels e legibilidade de controles e hints de formulário no workspace em 360 px sem overflow horizontal.
- **Arquivos prováveis**:
  - `src/apps/core/static/css/workspace.css`
  - `src/apps/legislation/templates/legislation/`
- **Comando de verificação**:
  ```bash
  python manage.py check
  node --test --test-concurrency=1 tests/js/visual.foundation.test.mjs
  ```
- **Critério de pronto**: Controles legíveis em 360 px sem quebras de layout ou overflow.
- **Dependências**: Nenhuma.

---

## T-013 — Hardening de Content Security Policy (CSP) e integridade de fontes

- **ID**: `T-013`
- **Status**: AGUARDA APROVAÇÃO DO DONO
- **Objetivo**: Condicionar fontes locais e evitar requisições remotas não autorizadas por CSP, com revisão de segurança jurídica e de integridade de ativos.
- **Arquivos prováveis**:
  - `src/apps/core/templates/`
  - `config/settings.py`
  - `tests/js/csp.test.mjs`
  - `tests/js/csp_security.test.js`
- **Comando de verificação**:
  ```bash
  node --test --test-concurrency=1 tests/js/csp.test.mjs tests/js/csp_security.test.js
  python manage.py check
  ```
- **Critério de pronto**: Zero requisições não autorizadas por CSP e fallback de fontes locais íntegro.
- **Dependências**: Aprovação do dono.

---

## T-014 — Otimização de paginação e consulta do histórico de sessões

- **ID**: `T-014`
- **Status**: PRONTA
- **Objetivo**: Garantir busca e paginação eficientes no histórico de sessões sem sobrecarga de memória quando houver mais de 500 registros.
- **Arquivos prováveis**:
  - `src/apps/legislation/workspace_views.py`
  - `src/tests/test_workspace_routes.py`
- **Comando de verificação**:
  ```bash
  pytest src/tests/test_workspace_routes.py -q -p no:cacheprovider
  ```
- **Critério de pronto**: Paginação executada em query SQL delimitada (`limit`/`offset`) sem carregar instâncias excedentes na memória.
- **Dependências**: Nenhuma.
