# Relatório de Reorganização para Desenvolvimento Autônomo (`chore/agent-readiness`)

- **Repositório / Worktree**: `L:\Jurix-agent-readiness` (branch `chore/agent-readiness` a partir de `main` em `1ac3ab753dacb779e5b7b5a0fe99beae74ed6ac3`)
- **Artefatos externos de baseline e pós-reorganização**: `L:\jurix-reorg\baseline\` e `L:\jurix-reorg\post\`
- **Ambiente Python isolado**: `L:\jurix-venv` (Python 3.12.10, `ruff 0.8.4`, `pytest 9.1.1`)
- **Arquivos apagados (`--diff-filter=D`)**: `0`

---

## 1. Métricas Antes vs. Depois

| Métrica | Antes (`main` @ `1ac3ab75`) | Depois (`chore/agent-readiness`) | Variação / Meta |
| :--- | :--- | :--- | :--- |
| **Entradas rastreadas na raiz (`git ls-tree`)** | 30 | 33 (`-2` diários `GOAL.md`/`FRONTEND_LOG.md`, `+5` governança: `AGENTS.md`, `STATE.md`, `CLAUDE.md`, `.graphifyignore`, `.agents/`) | `0` diários na raiz |
| **Arquivos `.md` ativos fora de `docs/archive/` (total)** | 104 | 56 (`55` movidos para `docs/archive/`, `+7` novos de governança) | `-48` `.md` ativos fora do arquivo morto |
| **Arquivos `.md` em `docs/` fora de `docs/archive/`** | 92 | 42 | `-50` `.md` soltos em `docs/` |
| **Documentos com sufixo `v2`–`v6` fora de `docs/archive/`** | 28 (`.md`, `.sql`, `.env.example`) | 3 protegidos por contrato (`docs/rag-quality-contract-v2.md`, `docs/environment-hardening-v2.env.example`, `docs/postgresql-diagnostics-v2.sql`) | `25` duplicatas versionadas `.md` arquivadas |
| **Leitura padrão do agente (linhas)** | ~6.800+ linhas (`README.md` + `GOAL.md` + `FRONTEND_LOG.md` + diários) | **186 linhas** (`AGENTS.md` 60 + `STATE.md` 60 + `docs/mvp.md` 38 + `T-009` 28; ou **343 linhas** lendo `docs/backlog.md` inteiro) | **Meta $\le 400$ linhas atingida** |
| **Leitura padrão do agente (bytes)** | ~3.080 KB (`NORMATIVE_IMPLEMENTATION_PROGRESS.md` 2,2 MB + `PGM_PILOT_DELIVERY.md` 592 KB + `FRONTEND_LOG.md` 209 KB + `README.md` 47 KB + `GOAL.md` 15 KB) | **15,5 KB** (`15.498` bytes com `T-009`; ou **22,2 KB** / `22.705` bytes com `docs/backlog.md` inteiro) | **Meta $\le 25\text{ KB}$ atingida** (`0` diários) |
| **Grafo Graphify (nós / relatório)** | Sem filtro: `10.691` nós / `136 KB` | Escopo `src/` configurado via `.graphifyignore`: `~4.510` nós / `40 KB` (CLI `graphify` ausente no host local; não executado) | Escopo isolado em `.graphifyignore` |
| **Contratos (`validate_*_contract.py`)** | `3/3` PASS (código `0`) | `3/3` PASS (código `0`) | Sem regressão |
| **Django `check` e `makemigrations --check`** | `0` issues / código `0` | `0` issues / código `0` | Sem regressão |
| **Python `pytest` pós-`collectstatic` (`USE_SQLITE=True`)** | `2.264` coletados: `2.226` pass, `29` fail, `9` skipped | `2.264` coletados: `2.227` pass, `28` fail, `9` skipped (`0` novas falhas; subconjunto estrito do baseline) | Sem regressão (`T-006`) |
| **JS por arquivo (`23` arquivos nos gates)** | `20` código `0` (`3` 100% skipped), `3` código `1` (`?v=`) | `20` código `0` (`3` 100% skipped), `3` código `1` (`?v=`); `npm test` sem `ENOENT` após C1 | Sem regressão (`T-005`, `T-008`) |

---

## 2. Economia de Contexto e Contagem de Leitura (1.678 Arquivos)

Para construir `docs/agents/reorg-manifest.csv` (1.678 linhas de arquivos rastreados):

- **Lidos por inteiro (`read_full`)**: **7 arquivos** (`tests/js/run-tests.mjs`, `.github/workflows/ci.yml`, `.gitignore`, `pyproject.toml`, `scripts/validate_documentation_contract.py`, `scripts/validate_release_contract.py`, `scripts/validate_staging_contract.py`, além da inspeção focal de `src/tests/test_consolidation_engine.py` para `T-009`).
- **Lidos apenas cabeçalhos/primeiras linhas (`read_headings_only`)**: **94 arquivos** (`.md` fora de `docs/archive` e `docs/ui-audit`).
- **Classificados apenas por metadados/caminho (`read_metadata_only`)**: **1.577 arquivos** (incluindo os 751 binários, `docs/ui-audit/`, `docs/archive/` e código-fonte).

---

## 3. Commits Executados e Reverts

Nenhum `git revert` foi necessário (todos os gates passaram de primeira em cada lote):

1. `c13b5cd2` — `chore(docs): archive progress diaries` (Lote 1: 7 diários movidos para `docs/archive/progress/` + atualização de links em `README.md` e `docs/current-status.md`).
2. `770e6c50` — `chore(docs): archive historical status and versioned duplicates` (Lote 2: 48 relatórios antigos e duplicatas versionadas `v2`–`v6` movidos para `docs/archive/status/` + atualização de links em `README.md`).
3. `996f87cb` — `docs: add agent entrypoint, state, mvp, and backlog` (Lote 3: criação de `AGENTS.md`, `STATE.md`, `docs/mvp.md`, `docs/backlog.md`, `docs/README.md` e `docs/agents/reorg-manifest.csv`).
4. `9921b73e` & `cbb03d71` — `chore(config): add agent rules and ignore rules` / `chore(config): add missing ignore rules to gitignore` (Lote 4: criação de `CLAUDE.md`, `.agents/rules/jurix.md`, `.graphifyignore` e adição de `coverage.xml`, `node_modules/` e `graphify-out/` ao `.gitignore`).
5. `a6eef9a3` — `fix(ci): use fileURLToPath in js runner and collectstatic in ci` (Lote 5: correções autorizadas C1 em `tests/js/run-tests.mjs` e C2 em `.github/workflows/ci.yml`).

---

## 4. Resumo das Decisões do Manifesto (`docs/agents/reorg-manifest.csv`)

- **`MANTER`: 770 arquivos** — Código em `src/`, testes em `src/tests/` e `tests/js/`, scripts operacionais, configurações e contratos ativos em `docs/` (`current-status.md`, `production-readiness.md`, `rag-quality-contract-v2.md`, `security-production-matrix.md`, `production-validation.md`, `research/PGM_GOLD_ADJUDICATION.md`, etc.).
- **`ARQUIVAR`: 55 arquivos** — Movidos via `git mv` sem perda de histórico:
  - **Em `docs/archive/progress/` (7 arquivos)**: `GOAL.md`, `FRONTEND_LOG.md`, `NORMATIVE_IMPLEMENTATION_PROGRESS.md`, `PGM_PILOT_DELIVERY.md`, `NORMATIVE_GRAPH_DELIVERY.md`, `JURIX_NORMATIVE_GRAPH_IMPLEMENTATION_PLAN.md`, `JURIX_NORMATIVE_GRAPH_TEST_RUNBOOK.md`.
  - **Em `docs/archive/status/` (48 arquivos)**: `PIBIC_RELATORIO_FINAL_ESBOCO.md`, `PGM_USABILITY_RESULTS.md`, `PGM_USABILITY_RUNBOOK.md`, `JURIX_PGM_IMPLEMENTATION_PLAN.md`, `JURIX_PGM_READINESS_ASSESSMENT_2026-10-07.md`, `JURIX_REVIEW_AND_ROADMAP_2026-10-17.md`, 11 relatórios em `docs/audit/`, `docs/frontend/visual-audit-2026-09.md`, `docs/release/v1.2-production-acceptance.md`, `docs/runbooks/temporal-rag-v4.md` e 28 documentos versionados/planos antigos de `docs/` (`api-contract-v2.md`, `architecture-boundaries-v2.md`, `architecture-contract-v2.md`, `audit-fixes-2026-09.md`, `benchmark-review-template-v2.md`, `ci-gates-v2.md`, `disaster-recovery-v2.md`, `engineering-assurance-ledger-v4.md`, `engineering-checklist-v3.md`, `hardening-v3-ui-and-suggestions.md`, `ingestion-safety-v2.md`, `jurix-2-0-phase2-phase3-v4.md`, `jurix-patch-5-temporal-rag-suggestions.md`, `migration-gate-v2.md`, `norma-ui-and-dynamic-suggestions-v3.md`, `operational-runbook-v2.md`, `operations-runbook-v2.md`, `operator-faq-v2.md`, `pibic-gap-plan.md`, `production-artifact-contract-v2.md`, `rag-evaluation-v2.md`, `release-checklist-v2.md`, `release-v1.2-plan.md`, `security-threat-model-v2.md`, `slo-and-observability-v2.md`, `test-strategy-v3.md`, `threat-model-v2.md`, `v6-postmortem-v2.md`).
- **`INDICAR`: 853 arquivos** — Mantidos onde estão nesta passada, indicados para limpeza futura (`T-002`): 751 binários (`docs/ui-audit/**/*.png`, `docs/research/screenshots/*.png`, PDFs de auditoria) e 102 JSON/JSONL/evidências de execução QA em `docs/ui-audit/`, `docs/audit/` e `docs/research/evidence/`.
- **`REVISAR`: 0 arquivos**.

---

## 5. Referências Quebradas Pré-existentes (Reportadas, Não Alteradas)

1. **`.dockerignore:36`**: Referencia `!docs/production-final-assurance-v4.md`, porém o arquivo já residia em `docs/archive/production-final-assurance-v4.md` antes desta passada.
2. **`src/tests/test_deployment_config.py:54`**: Referencia `docs/relatorio.pdf` em comentário/asserção de exclusão Docker, arquivo inexistente na árvore rastreada.

---

## 6. Sobreposição de Workflows GitHub Actions (Decisão D3)

Nenhum workflow foi removido nesta passada (consolidar em `T-007`). Os 8 arquivos em `.github/workflows/` apresentam sobreposição direta:

1. **`ci.yml`**: Dispara em `main` e no branch inexistente `develop`; executa migrações, `collectstatic` (C2), `pytest`, `ruff` e `bandit`.
2. **`production-gates.yml`**, **`production-assurance-v2.yml`**, **`production-hardening-v2.yml`** e **`final-production-assurance-v5.yml`**: 4 workflows sobrepostos que validam contratos de release/staging, settings de produção e gates operacionais em versões sucessivas (`v2` a `v5`).
3. **`security-hardening-v2.yml`**: Sobrepõe checagens de segurança/CSP/contratos já presentes nos workflows de assurance e no `ci.yml`.
4. **`rag-release-gate-v2.yml`** e **`rag-benchmark.yml`**: Sobrepõem validações do contrato RAG (`docs/rag-quality-contract-v2.md`) e suítes de avaliação.

---

## 7. Credenciais e Helpers de Escrita (Decisão D5)

- **Helpers configurados no Git (somente nomes, sem valores)**:
  - Escopo `system`: `credential.helper=manager`
  - Escopo `global`: `credential.helper=wincred`
- **Varredura de segredos em arquivos rastreados**: `0` ocorrências de chaves privadas ou tokens (`AKIA`, `ghp_`, `sk-`, `AIza`, `PRIVATE KEY`). Arquivos `.env` locais não foram abertos nem impressos.

---

## 8. Desvios Fatuais e Limitações de Ambiente Registradas

1. **Isolamento via `git worktree` (`L:\Jurix-agent-readiness`)**: O diretório `L:\Jurix` continha 83 itens não commitados. Para preservar integralmente o trabalho em andamento e cumprir a exigência de árvore limpa em `chore/agent-readiness` a partir de `main`, a passada foi executada em worktree limpa dedicada.
2. **Docker / PostgreSQL / Redis inativos no host**: Conforme previsto na Seção 6.1, na ausência de Postgres/Redis ativos, `pytest` rodou com `USE_SQLITE=True`.
3. **Arquivos `v2` protegidos por contrato**: Além de `docs/rag-quality-contract-v2.md`, `docs/environment-hardening-v2.env.example` e `docs/postgresql-diagnostics-v2.sql` foram mantidos em `docs/` porque `scripts/validate_release_contract.py` exige sua presença literal.
4. **`real.browser.test.mjs` e testes `skipped`**: Executado uma vez isoladamente e excluído dos gates por depender de Chromium/servidor externo; 3 arquivos JS (`jurix.audit-regressions.test.mjs`, `normative-admin-review.browser.test.mjs`, `normative-collections.browser.test.mjs`) saem com código `0` tendo 100% dos testes `skipped` (registrado para alerta em `T-008`).
