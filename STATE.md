# STATE.md — Estado Real do Sistema Jurix

> Última atualização: 2026-10-26 (Branch `chore/agent-readiness`, base `1ac3ab75`)

tarefa_atual: T-009

## 1. Estado Real por Subsistema

| Subsistema | Localização Principal | Estado Operacional | Observação Factual |
| :--- | :--- | :--- | :--- |
| **Motor de Consolidação** | `src/processing/consolidation_engine.py` | Funcional em código / Sem saída pública validada | Aplica `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` em ordem cronológica das normas modificadoras, com suporte posicional (`2º-A`) e seção de adicionados. Ainda não há normas consolidadas publicadas para a PGM. |
| **Extrator Normativo / DOM** | `src/processing/`, `src/clients/dom_natal/` | Funcional em código / Zero extrações aceitas | Pipeline de ingestão do Diário Oficial de Natal e extração de eventos implementado; faltam adjudicação humana (`validado=True`) e homologação jurídica. |
| **RAG / Busca Normativa** | `src/llm_engine/` | Funcional / Fora do MVP inicial | Busca híbrida (pgvector + léxica), reranking e citações ancoradas operam em código, mas dependem de corpus validado e ficam fora do escopo do MVP (`docs/mvp.md`). |
| **UI e Views (Django/HTMX)** | `src/apps/legislation/`, `src/apps/core/` | Funcional / Parcialmente acoplada a chat | Interfaces web e workspaces administrativos existem; falta endpoint/view enxuto dedicado ao MVP de consulta consolidada *fail-closed* (`T-010`). |
| **Banco de Dados e Filas** | PostgreSQL 16 (`pgvector`) + Redis + Celery | Requer containers ou `USE_SQLITE=True` | Em desenvolvimento/CI sem Docker ativo, a suíte roda com `USE_SQLITE=True`. Operação real requer Postgres com extensão `vector` e Redis. |
| **Contratos de Governança** | `scripts/validate_*_contract.py` | **PASSANDO (Código 0)** | Os 3 contratos (`documentation`, `release`, `staging`) e `manage.py check` / `makemigrations --check` passam integralmente. |
| **CI (GitHub Actions)** | `.github/workflows/` | 8 workflows com sobreposição | `ci.yml` corrigido nesta passada para rodar `collectstatic` antes do `pytest` (C2); persiste referência ao branch `develop` inexistente e 6 workflows de assurance/hardening sobrepostos (`T-007`). |

## 2. Baseline de Qualidade e Testes (Contrato de Não Regressão)

Medido sobre `1ac3ab753dacb779e5b7b5a0fe99beae74ed6ac3` (artefatos completos em `../jurix-reorg/baseline/`):

- **Repositório**: 1.678 arquivos rastreados, 113,5 MB em blobs (`git ls-files`), `.git` com 162,3 MB.
- **Contratos (`scripts/`)**:
  - `validate_documentation_contract.py`: `0` (PASS)
  - `validate_release_contract.py`: `0` (PASS)
  - `validate_staging_contract.py`: `0` (PASS)
- **Django Check & Migrações**:
  - `python manage.py check`: `0` (0 issues)
  - `python manage.py makemigrations --check --dry-run`: `0` (No changes detected)
  - `python manage.py collectstatic --noinput`: `0` (184 copiados, 548 pós-processados)
- **Ruff (`ruff 0.8.4`)**:
  - `ruff check src/`: código `1` (avisos pré-existentes; corrigir apenas em `T-004`)
  - `ruff format --check src/`: código `1` (204 arquivos a reformatar, 227 já formatados; `T-004`)
- **Python (`pytest src/tests/` pós-`collectstatic`, `USE_SQLITE=True`)**:
  - Total coletado: **2.264 testes**
  - Resultado do baseline: **2.226 passaram, 29 falharam, 9 pulados (skipped)** em 425,8s (código `1`).
  - As falhas concentram-se em dependências de banco/serviço externo e asserções a serem isoladas em `T-006`.
- **JavaScript (`tests/js/`, execução isolada por arquivo com `node --test`)**:
  - Total avaliado nos gates: **23 arquivos** (excluído `real.browser.test.mjs`, instável por depender de Chromium).
  - **20 arquivos saem com código `0`** (sendo 3 com 100% dos testes `skipped`).
  - **3 arquivos saem com código `1`** por asserção literal de `?v=` (`T-005`): `norma_ui_v3.test.mjs`, `session-created-toast.test.mjs` e `sidebar.unification.test.mjs`.

## 3. Bloqueadores Externos Ativos

1. **Adjudicação Humana do Corpus Ouro (PGM Natal)** (`T-003`): Sem validação por procuradores nos termos de `docs/research/PGM_GOLD_ADJUDICATION.md`, nenhuma extração ou consolidação pode ser marcada como vigente em produção (*fail-closed*). Tarefa exclusiva de humanos, fora do escopo de agentes.
2. **Serviços Docker Locais (Postgres 16 + pgvector / Redis)**: Quando o daemon Docker não está ativo no host, os testes rodam contra SQLite (`USE_SQLITE=True`).
3. **Limpeza Física de Binários Git (`T-002`)**: Bloqueada aguardando autorização expressa do dono e janela coordenada com reclone.

## 4. Tarefa Atual e Próxima Recomendada

- **`tarefa_atual`**: `T-009` em [`docs/backlog.md`](docs/backlog.md): *Testes fim a fim do motor de consolidação (`src/processing/consolidation_engine.py`) cobrindo `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` em ordem cronológica, mais a regra fail-closed para evento não validado.*

## 5. Como Atualizar Este Arquivo ao Fechar uma Tarefa

1. Atualize a linha correspondente na tabela da Seção 1 caso o estado de um subsistema mude.
2. Atualize os contadores da Seção 2 com o novo resultado real dos testes/contratos.
3. Em `docs/backlog.md`, marque a tarefa concluída e atualize o campo `tarefa_atual` acima com a próxima tarefa pronta da fila.
4. Mantenha `STATE.md` sempre com **no máximo 150 linhas** e sem histórico narrativo.
