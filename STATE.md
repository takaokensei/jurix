# STATE.md — Estado Real do Sistema Jurix

> Última atualização: 2026-10-26 (Branch `chore/agent-readiness`, base `1ac3ab75`)

## 1. Estado Real por Subsistema

| Subsistema | Localização Principal | Estado Operacional | Observação Factual |
| :--- | :--- | :--- | :--- |
| **Motor de Consolidação** | `src/processing/consolidation_engine.py` | Funcional em código / Sem saída pública validada | Aplica `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` em ordem cronológica das normas modificadoras, com suporte posicional (`2º-A`) e seção de adicionados. Ainda não há normas consolidadas publicadas para a PGM. |
| **Extrator Normativo / DOM** | `src/processing/` | Funcional em código / Zero extrações aceitas | Pipeline de ingestão do Diário Oficial de Natal e extração de eventos implementado; faltam adjudicação humana (`validado=True`) e homologação jurídica. |
| **RAG / Busca Normativa** | `src/rag/` | Funcional / Fora do MVP inicial | Busca híbrida (pgvector + léxica), reranking e citações ancoradas operam em código, mas dependem de corpus validado e ficam fora do escopo do MVP (`docs/mvp.md`). |
| **UI e Views (Django/HTMX)** | `src/legal_docs/`, `src/templates/`, `src/static/` | Funcional / Parcialmente acoplada a chat | Interfaces web e workspaces administrativos existem; falta endpoint/view enxuto dedicado ao MVP de consulta consolidada *fail-closed* (`T-010`). |
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
  - As 29 falhas pré-existentes concentram-se em 13 arquivos de teste (`test_api_security.py`, `test_collections_workspace.py`, `test_dom_sync.py`, `test_event_review_permissions.py`, `test_foundation_check_workspace.py`, `test_normative_impact_queue.py`, `test_temporal_timeline_v5.py`, `test_corpus_reconciliation.py`, `test_normative_projection.py`, `test_pgm_qa_reviewer_provision.py`, `test_grounded_citations.py`, `test_llm_provider.py`, `test_normative_qa_guard.py`, `test_qa_archive_rag.py`, `test_strict_grounding.py`) — registradas para tratamento em `T-006`.
- **JavaScript (`tests/js/`, execução isolada por arquivo com `node --test`)**:
  - Total avaliado nos gates: **23 arquivos** (excluído `real.browser.test.mjs`, classificado como instável/ambiente por exigir Chromium/servidor).
  - **20 arquivos saem com código `0`** (sendo 3 com 100% dos testes `skipped`: `jurix.audit-regressions.test.mjs`, `normative-admin-review.browser.test.mjs`, `normative-collections.browser.test.mjs`).
  - **3 arquivos saem com código `1`** por asserção literal de `?v=` (`T-005`):
    - `norma_ui_v3.test.mjs` (51 testes, 50 pass, 1 fail)
    - `session-created-toast.test.mjs` (1 teste, 0 pass, 1 fail)
    - `sidebar.unification.test.mjs` (7 testes, 6 pass, 1 fail)

## 3. Bloqueadores Externos Ativos

1. **Adjudicação Humana do Corpus Ouro (PGM Natal)** (`T-003`): Sem validação por procuradores nos termos de `docs/research/PGM_GOLD_ADJUDICATION.md`, nenhuma extração ou consolidação pode ser marcada como vigente em produção (*fail-closed*).
2. **Serviços Docker Locais (Postgres 16 + pgvector / Redis)**: Quando o daemon Docker não está ativo no host, os testes rodam contra SQLite (`USE_SQLITE=True`). Validações específicas de índice vetorial HNSW/IVFFlat exigem container PostgreSQL ativo.
3. **Limpeza Física de Binários Git (`T-002`)**: Os 751 binários históricos em `docs/` (especialmente `docs/ui-audit/`) permanecem rastreados (`INDICAR`) até janela autorizada de `git filter-repo`.

## 4. Próxima Tarefa Recomendada

- **`T-009`** em [`docs/backlog.md`](docs/backlog.md): *Testes fim a fim do motor de consolidação (`src/processing/consolidation_engine.py`) cobrindo `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` em ordem cronológica, mais a regra fail-closed para evento não validado.*

## 5. Como Atualizar Este Arquivo ao Fechar uma Tarefa

1. Atualize a linha correspondente na tabela da Seção 1 caso o estado de um subsistema mude.
2. Atualize os contadores da Seção 2 com o novo resultado real dos testes/contratos.
3. Em `docs/backlog.md`, marque a tarefa concluída e aponte a Seção 4 deste arquivo para a próxima tarefa pronta da fila.
4. Mantenha `STATE.md` sempre com **no máximo 150 linhas** e sem histórico narrativo (não transforme em diário).
