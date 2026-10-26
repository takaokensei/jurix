# Backlog de Engenharia (Agentes Autônomos)

Tarefas pequenas, independentes e verificáveis, ordenadas por prioridade de execução.

---

## T-009 — Testes fim a fim do motor de consolidação e regra *fail-closed*

- **ID**: `T-009`
- **Status**: PRONTA (Primeira tarefa para agente)
- **Objetivo**: Ampliar `src/tests/test_consolidation_engine.py` (que hoje já testa `REVOGA`, `ALTERA`, `ADICIONA` posicional/não-posicional e `REGULAMENTA` em casos unitários separados nas classes `TestConsolidationEngine`, `TestConsolidationAdditionsAndHonestStats` e `TestAddedTextExtraction`) adicionando um teste integrado fim a fim que aplique, sobre uma mesma norma-base, eventos `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` em ordem cronológica estrita, além de validar explicitamente a regra *fail-closed* quando houver evento com `validado=False` na cadeia modificadora.
- **Arquivos prováveis**:
  - `src/tests/test_consolidation_engine.py`
  - `src/processing/consolidation_engine.py` (somente leitura para referência; não alterar comportamento na tarefa de teste)
- **Comando de verificação**:
  ```bash
  pytest src/tests/test_consolidation_engine.py -q -p no:cacheprovider --tb=short
  ruff check src/tests/test_consolidation_engine.py
  ```
- **Critério de pronto**:
  1. Novo teste fim a fim cobre simultaneamente `REVOGA`, `ALTERA`, `ADICIONA` e `SUBSTITUI` ordenados por `data_publicacao` das normas modificadoras.
  2. Asserção explícita comprova que um evento com `validado=False` não é aplicado silenciosamente como texto vigente (*fail-closed*) e que os contadores do resultado (` ConsolidationResult`) permanecem determinísticos.
  3. Todos os testes de `src/tests/test_consolidation_engine.py` passam com código `0` e `ruff check` limpo no arquivo tocado.
- **Dependências**: Nenhuma.

---

## T-010 — Endpoint/view somente leitura de norma consolidada (*fail-closed*)

- **ID**: `T-010`
- **Status**: PRONTA (após `T-009`)
- **Objetivo**: Expor endpoint ou view somente leitura que retorne a norma consolidada estruturada por dispositivo com seu estado (`VIGENTE`, `ALTERADO`, `REVOGADO`, `NAO_VERIFICADO`) e metadados da fonte oficial (DOM), recusando exibir como `VIGENTE` qualquer dispositivo cuja extração ou cadeia de eventos não esteja integralmente validada (`validado=True`).
- **Arquivos prováveis**:
  - `src/legal_docs/views.py` (ou módulo de views/API correspondente)
  - `src/legal_docs/urls.py`
  - `src/processing/consolidation_engine.py`
  - `src/tests/test_consolidation_view.py` (novo)
- **Comando de verificação**:
  ```bash
  pytest src/tests/test_consolidation_engine.py src/tests/test_consolidation_view.py -q -p no:cacheprovider
  ```
- **Critério de pronto**:
  1. Resposta inclui estado individual por dispositivo e metadados da fonte oficial.
  2. Quando a norma ou evento modificador não está validado por humano, o estado retornado é `NAO_VERIFICADO` (nunca `VIGENTE`).
  3. Testes cobrem norma validada, norma com evento pendente (`validado=False`) e norma inexistente (`404`).
- **Dependências**: `T-009`.

---

## T-005 — Corrigir 3 testes JS quebrados por asserção literal de `?v=`

- **ID**: `T-005`
- **Status**: PRONTA
- **Objetivo**: Atualizar as asserções dos 3 testes JS que falham por cobrar query string estática antiga (`?v=`) em templates/assets, alinhando-os ao versionamento atual de estáticos sem afrouxar a verificação do caminho do asset.
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
- **Critério de pronto**: Os 3 arquivos saem com código `0` e `0` falhas.
- **Dependências**: Nenhuma.

---

## T-006 — Corrigir ou isolar falhas de `pytest` pós-`collectstatic`

- **ID**: `T-006`
- **Status**: PRONTA
- **Objetivo**: Diagnosticar e corrigir as falhas da suíte `pytest` listadas no baseline (`STATE.md` / `pytest_failures.txt`) após `collectstatic`, separando o que depende de serviços externos (Postgres/pgvector/Redis) do que é expectativa desatualizada de template/estático.
- **Arquivos prováveis**:
  - `src/tests/` (arquivos listados em `STATE.md`)
- **Comando de verificação**:
  ```bash
  python manage.py collectstatic --noinput
  pytest src/tests/ -q -p no:cacheprovider --tb=line -rfE
  ```
- **Critério de pronto**: Zero falhas em testes unitários/de contrato com `collectstatic` gerado.
- **Dependências**: Nenhuma.

---

## T-007 — Consolidar workflows do GitHub Actions e remover branch `develop`

- **ID**: `T-007`
- **Status**: PRONTA
- **Objetivo**: Consolidar os workflows sobrepostos (`production-assurance-v2.yml`, `production-hardening-v2.yml`, `final-production-assurance-v5.yml`, `production-gates.yml`, `security-hardening-v2.yml`, `rag-release-gate-v2.yml`) e remover a referência ao branch inexistente `develop` em `.github/workflows/ci.yml`.
- **Arquivos prováveis**:
  - `.github/workflows/*.yml`
- **Comando de verificação**:
  ```bash
  python scripts/validate_release_contract.py
  python scripts/validate_staging_contract.py
  ```
- **Critério de pronto**: Workflows sem duplicidade de versão no nome, `ci.yml` apontando apenas para branches reais e contratos de release verdes.
- **Dependências**: Aprovação do dono sobre a decisão D3.

---

## T-008 — Separar testes E2E de browser (`real.browser.test.mjs`) e alertar `skipped`

- **ID**: `T-008`
- **Status**: PRONTA
- **Objetivo**: Separar `tests/js/real.browser.test.mjs` (e outros `*.browser.test.mjs` que dependem de Chromium/servidor) em um script `npm run test:e2e`, mantendo `npm test` exclusivo para testes unitários rápidos, e fazer `tests/js/run-tests.mjs` emitir aviso explícito quando um arquivo terminar com 100% dos testes `skipped`.
- **Arquivos prováveis**:
  - `tests/js/run-tests.mjs`
  - `tests/js/package.json`
- **Comando de verificação**:
  ```bash
  cd tests/js && npm test
  ```
- **Critério de pronto**: `npm test` executa apenas testes determinísticos sem Chromium e alerta arquivos com todos os testes pulados.
- **Dependências**: Nenhuma.

---

## T-004 — Formatação global `ruff` em `src/` em PR dedicado

- **ID**: `T-004`
- **Status**: PRONTA (executar isoladamente)
- **Objetivo**: Aplicar `ruff format src/` (204 arquivos) e corrigir os avisos de `ruff check src/` em um branch/PR exclusivo, registrando o hash em `.git-blame-ignore-revs`.
- **Arquivos prováveis**:
  - `src/**/*.py`
  - `.git-blame-ignore-revs`
- **Comando de verificação**:
  ```bash
  ruff check src/
  ruff format --check src/
  ```
- **Critério de pronto**: Ambos os comandos saem com código `0` e sem alterações funcionais.
- **Dependências**: Nenhuma.

---

## T-001 — Reescrever `README.md` da raiz (de 47 KB para ~150 linhas)

- **ID**: `T-001`
- **Status**: PRONTA
- **Objetivo**: Substituir o `README.md` monolítico de 47 KB por um guia enxuto (~150 linhas) com visão do produto, setup rápido, arquitetura resumida e links para `docs/README.md`, arquivando o texto antigo caso necessário.
- **Arquivos prováveis**:
  - `README.md`
- **Comando de verificação**:
  ```bash
  wc -l README.md
  python scripts/validate_documentation_contract.py
  ```
- **Critério de pronto**: `README.md` com $\le 150$ linhas e contratos de documentação passando.
- **Dependências**: Nenhuma.

---

## T-002 — Limpeza física de binários no histórico Git (`git filter-repo`)

- **ID**: `T-002`
- **Status**: BLOQUEADA (Requer janela combinada e autorização do dono)
- **Objetivo**: Remover do histórico `.git` (162 MB) e da árvore os 751 binários históricos de QA (`docs/ui-audit/*.png`, PDFs de auditoria) marcados como `INDICAR` em `docs/agents/reorg-manifest.csv`.
- **Arquivos prováveis**:
  - `docs/ui-audit/**` e demais itens `INDICAR` em `docs/agents/reorg-manifest.csv`
- **Comando de verificação**:
  ```bash
  git count-objects -vH
  ```
- **Critério de pronto**: Redução de `.git` e blobs rastreados sem quebrar contratos, executada em janela coordenada com reclone.
- **Dependências**: Autorização explícita do dono (proibido em sessões normais de agentes).

---

## T-003 — Adjudicação humana do Corpus Ouro da PGM

- **ID**: `T-003`
- **Status**: BLOQUEADA POR HUMANO (PGM / Jurídico)
- **Objetivo**: Realizar a validação e adjudicação humana das extrações e consolidações do Corpus Ouro junto à PGM Natal, conforme protocolo em [`docs/research/PGM_GOLD_ADJUDICATION.md`](research/PGM_GOLD_ADJUDICATION.md).
- **Arquivos prováveis**:
  - `docs/research/PGM_GOLD_ADJUDICATION.md`
  - `docs/current-status.md`
- **Comando de verificação**:
  ```bash
  python scripts/validate_documentation_contract.py
  ```
- **Critério de pronto**: Dispositivos e eventos do lote piloto validados por procurador responsável (`validado=True`) com ata registrada.
- **Dependências**: Disponibilidade da equipe jurídica da PGM Natal.
