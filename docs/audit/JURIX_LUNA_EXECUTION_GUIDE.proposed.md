# Jurix — guia de execução para Luna (proposta de 02/10/2026)

Este arquivo **não autoriza implementação nesta auditoria**. O usuário autorizou apenas auditar e planejar. Depois de uma autorização expressa para a próxima etapa, executar uma tarefa por vez. Recomendação editorial: Luna com raciocínio **alto** para backend, dependências e integração; médio pode bastar para CSS isolado. Não é um benchmark de modelos. T-013, T-025 e T-026 exigem revisão humana/Sol do diff antes de liberar continuação.

## Leitura e condição de entrada

1. Ler [auditoria completa](C:/Jurix/docs/audit/JURIX_FULL_AUDIT.proposed.md), [plano mestre](C:/Jurix/docs/audit/JURIX_MASTER_IMPLEMENTATION_PLAN.proposed.md), [design system](C:/Jurix/docs/audit/JURIX_DESIGN_SYSTEM_SPEC.proposed.md) e este guia por completo.
2. Trabalhar no checkout C:/Jurix. Baseline: **main**, HEAD **3d6d428e5a92f9c516418018e21fe6bf11a90d41**, 39 alterações tracked preexistentes e não rastreados descritos no baseline. A auditoria inclui essas alterações. Não mudar para ui/pro-polish por conta própria.
3. Conferir [git-final.json](C:/Jurix/docs/audit/2026-10-02/git-final.json), branch, HEAD, staged e hashes dos arquivos da tarefa. Se o estado diferir, comparar sem descartar nada e pedir revalidação. Não exigir worktree limpo apagando o trabalho existente.
4. Reproduzir o achado antes de editar. Se ele já foi corrigido, registrar evidência, pular somente essa tarefa e seguir após aprovação. Hipóteses do relatório não são tarefas autorizadas.
5. **Esta sequência tem IDs novos. T-014 aqui trata contribuição das fontes; não é a antiga T-014 de ranking de histórico. O ranking do histórico continua fora de escopo. T-016 aqui trata densidade visual, não recência. A ordenação por publicação existente permanece.**
6. Se um arquivo anunciado como novo já existir, ler seu conteúdo e parar para adaptar o plano; nunca sobrescrever.

## Preservação, commits e rollback

- Sem reset, clean, stash, checkout de arquivos, switch, pull, push, merge ou migrations de dados reais.
- Não substituir .env/configs locais, não ler/exibir secrets nos relatórios. Não consumir filas reais nem iniciar workers sobre dados reais.
- Nesta etapa não há autorização para commit. Na implementação, solicitar explicitamente **um commit local por tarefa**, sem push/merge. Só após essa autorização, fazer staging por caminho/hunk, não git add .; não incluir alterações anteriores.
- Guardar diff/base dos arquivos de cada tarefa em diretório QA novo antes de editar, incluindo hunks preexistentes. Se o patch conflitar, parar.
- Rollback com git revert somente do commit da própria tarefa, depois de autorizado e com inspeção de conflitos. Sem commit autorizado: reverter **apenas os próprios hunks** por patch inverso revisado; nunca restaurar o arquivo inteiro da HEAD nem desfazer o trabalho anterior.
- Após cada tarefa: listar diff real, comandos/resultados, regressões e limites; aguardar revisão quando a autorização assim exigir. Falha significa parar e relatar; não baixar assertions, desativar testes ou aumentar limites para passar.

## Ambiente QA e verificações comuns

Comandos abaixo partem de C:/Jurix. Executar em PowerShell, cada comando separadamente. No guia, caminhos src/... são relativos a esse cwd. Comandos node usam caminhos absolutos. npm precisa de cwd C:/Jurix/tests/js (ou sua cópia QA autorizada). Scripts/testes não devem apontar o banco real.

```powershell
git branch --show-current
git rev-parse HEAD
git status --short
git diff --cached --stat
git diff --stat
& 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q
& 'C:/Jurix/.venv/Scripts/python.exe' -m ruff check src config
& 'C:/Jurix/.venv/Scripts/python.exe' manage.py check
& 'C:/Jurix/.venv/Scripts/python.exe' scripts/validate_documentation_contract.py
& 'C:/Jurix/.venv/Scripts/python.exe' scripts/architecture_budget_v2.py
```

Em C:/Jurix/tests/js executar npm test. Baseline real: 805 passed / 6 skipped; npm test exit0; Ruff/check/doc gate passam; arquitetura falha por 867/850 linhas em rag_service.py. Uma falha conhecida não autoriza aumentar orçamento. Depois da T-020 usar o Python QA validado em vez da .venv original nos mesmos comandos.

Banco SQLite real permanece intacto. Para UI/Ollama usar [audit_server.py](C:/Jurix/docs/audit/2026-10-02/audit_server.py), que faz backup para temp e serve **127.0.0.1:8006**. Verificar que o processo existente usa a cópia QA antes de reutilizar; não iniciar outro servidor se a porta estiver ocupada. Se for preciso iniciar, executar:
```powershell
& 'C:/Jurix/.venv/Scripts/python.exe' docs/audit/2026-10-02/audit_server.py
```
Não chamar um manage.py com escrita de dados só por o navegador usar 8006: o manage.py normal ainda pode apontar ao banco real. Para T-027, carregar configuração QA em processo específico, demonstrar o caminho absoluto de DATABASES e hash do original antes/depois. Se isso não estiver garantido, parar antes de qualquer --apply.

Antes/depois de cada tarefa rodar os testes direcionados abaixo; depois rodar as suítes completas quando mexer em RAG/SSE/dependências ou no fechamento da fase. Novos testes entram na lista pós-patch; no baseline executar os testes existentes e demonstrar a falha pela regressão recém-criada antes de implementar a correção. UI: verificar 320/360/768/1280/1920px, claro/escuro, Tab/Escape, foco devolvido, sem dados privados. Screenshots novas em subpasta QA própria, sem sobrescrever as evidências desta auditoria.

## Invariantes de produto e segurança

- Conteúdo jurídico primeiro, evidências estruturadas depois; LLM não gera URL. IDs estáveis ligam claim → dispositivo → norma → URL oficial.
- Referência de lei inteira abre URL oficial sem fragmento; referência de dispositivo pode usar trecho/âncora. Cópia preserva Markdown e links.
- Não substituir ausência de evidência por confiança alta. Similaridade não é probabilidade jurídica.
- Preferência mais recente: fontes/cópia reveladas juntas, suavemente, após validação; sources pode associar IDs internamente antes. Não ressuscitar “rascunho em geração” nem expor texto bruto não validado.
- Não resolver grounding baixando limiar, ignorando números, negação, modalidade ou condição. Falha de overview também continha uma omissão real de condição: ela deve continuar sendo recusada.
- Não migrar framework, não mudar ranking do histórico, não alterar schema/migrations de dados, não introduzir fontes/licenças ou provedores novos neste plano.
- PostgreSQL/Redis/Celery ficaram não testados em runtime: requerem ambiente QA com fila vazia e dados sintéticos. Docker aberto não basta.

## Lista de tarefas atômicas

Cada tarefa a seguir representa uma mudança coerente, revisável em um único commit **se autorizado**. O campo esforço indica P/M/G; não é estimativa de horas. As evidências completas e linha-base estão nos achados ligados.

### Tarefa: T-001

Achados cobertos: UX-A-008, COD-A-002

Objetivo: Impedir perda de texto ao exportar PDF.

Esforço: M

Pré-requisitos: Nenhuma; revalidar depois da T-020. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-008: src/apps/legislation/views.py:312–329; src/tests/test_workspace_routes.py:313; 2026-10-02/export-8206.pdf, export-8206-page1.png, export-8206-page2.png; pdftotext executado; COD-A-002: src/tests/test_workspace_routes.py:313; src/tests/test_legal_diff.py; tests/js/real.browser.test.mjs; coverage.json.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/views.py
- C:/Jurix/src/apps/legislation/norma_pdf.py (novo)
- C:/Jurix/src/tests/test_workspace_routes.py
- C:/Jurix/src/tests/test_norma_pdf.py (novo)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Criar regressão com texto de mais de 52 linhas, incisos, acentos e linha comprida. Abrir response.content com fitz e demonstrar que frases do começo/meio/fim estão ausentes no baseline.
2. Extrair geração para norma_pdf.py. Medir wrapping com fitz.get_text_length usando a mesma fonte/tamanho da inserção; limitar por altura real da caixa, não por 52 linhas nem 96 caracteres.
3. Só consumir linhas depois de insert_textbox retornar valor não negativo. Se houver déficit de espaço, reduzir a página de conteúdo e repetir sem descartar linhas; uma linha impossível gera erro explícito, nunca PDF válido vazio.
4. Manter header/footer e MIME/filename. Não copiar PDF remoto como exportação consolidada.
5. Renderizar todas as páginas de QA com Poppler e extrair texto para conferir integridade.

Critérios de aceite: Art. 1 e último artigo presentes; acentos/negações/números preservados; nenhum corpo de página vazio por overflow; teste antigo permanece verde.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_workspace_routes.py src/tests/test_norma_pdf.py; pdfinfo ARQUIVO_QA; pdftotext ARQUIVO_QA -; pdftoppm -png ARQUIVO_QA PREFIXO_QA

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-002

Achados cobertos: UX-A-003

Objetivo: Restaurar ações secundárias da norma em desktop.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-003: src/apps/core/static/css/jurix-legal-detail.css:37; src/apps/legislation/templates/legislation/norma_detail.html:62; screenshot audit-20261002-normas-3-1920.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/core/static/css/jurix-legal-detail.css
- C:/Jurix/tests/js/norma_ui_v3.test.mjs
- C:/Jurix/tests/js/real.browser.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Adicionar teste browser com o HTML details fechado e CSS reais; a 1280/1920 deve existir summary visível e focável.
2. Remover display:none de .legal-detail-more-actions > summary fora do media query; usar o mesmo disclosure fechado/aberto em todos os tamanhos.
3. Garantir que Tab/Enter abrem as ações e Escape de outros overlays não altere o details.

Critérios de aceite: Comparar, árvore, copiar, PDF e SAPL descobríveis em 360/1280/1920; teclado abre o grupo; nenhum conteúdo acionável escondido sem trigger.

Comandos de verificação: node --test C:/Jurix/tests/js/norma_ui_v3.test.mjs C:/Jurix/tests/js/real.browser.test.mjs; browser /normas/3/

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-003

Achados cobertos: UX-A-004, COD-A-002

Objetivo: Alinhar incisos OCR e consolidado no diff.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-004: src/processing/legal_diff.py:11,50; src/apps/legislation/views.py:235; screenshot audit-20261002-comparison-1280.jpg; COD-A-002: src/tests/test_workspace_routes.py:313; src/tests/test_legal_diff.py; tests/js/real.browser.test.mjs; coverage.json.

Arquivos a alterar:

- C:/Jurix/src/processing/legal_diff.py
- C:/Jurix/src/tests/test_legal_diff.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste “Art.2º...\nI – valorizar...” contra “Art.2º...\nInciso I valorizar...”; esperar mesmas chaves e ausência de remoção falsa.
2. Separar regex do rótulo explícito Inciso do marcador romano seguido de pontuação; aceitar espaço + texto só no rótulo explícito e aplicar limite de palavra/validação romana.
3. Preservar hierarquia artigo/parágrafo, ocorrência e conteúdo. Não retirar não, percentuais ou valores ao normalizar.
4. Cobrir II/IV/VIII, §/parágrafo único, alínea, texto que começa por letra romana mas não é marcador.

Critérios de aceite: Incisos presentes em ambos os lados não aparecem como removed; alteração de negação/valor continua changed.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_legal_diff.py; browser /normas/3/compare/

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-004

Achados cobertos: UX-A-001

Objetivo: Aceitar referências formatadas na biblioteca.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-001: src/apps/legislation/views.py:75,96; src/apps/core/static/js/jurix-norma-list.js (splitNormaIdentifier); screenshot audit-20261002-norm-search-formatted-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/views.py
- C:/Jurix/src/apps/core/static/js/jurix-norma-list.js
- C:/Jurix/src/tests/test_dynamic_suggestions_and_norma_list_v3.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Testar GET /normas/?q=Lei+nº+8.206/2026 e variantes 8206/2026, Lei 8206, Lei Complementar com número/ano e referência ambígua.
2. Usar parse_normative_references no servidor; normalizar número com pontos para compará-lo ao formato real do campo. Quando houver exatamente uma referência suficiente, filtrar campos numero/tipo/ano em vez da frase inteira icontains.
3. Manter busca ementa textual quando não houver referência inequívoca e combinar tipo/ano explícitos sem ampliar o conjunto.
4. Corrigir parser do formulário JS para números pontuados; servidor deve funcionar sem JS. Não alterar order_normas_by_publication.

Critérios de aceite: Busca formatada encontra norma3; norma ausente mostra vazio honesto; filtros e paginação mantidos.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_dynamic_suggestions_and_norma_list_v3.py src/tests/test_normative_reference.py; browser /normas/

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-005

Achados cobertos: IA-A-002

Objetivo: Excluir referências puras da lista de claims sem dispensar fatos.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: IA-A-002: src/processing/grounding_service.py:278–418; 2026-10-02/followup-runtime.json.

Arquivos a alterar:

- C:/Jurix/src/processing/grounding_service.py
- C:/Jurix/src/tests/test_grounding_service.py
- C:/Jurix/src/tests/test_strict_grounding.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Testar extract_claims com uma linha **Lei nº 8206/2026, Art. 7º** seguida de uma proposição legal válida.
2. Usar parser/reconhecimento ancorado para linhas constituídas somente de referência e formatação. Não implementar if '**' then skip nem ignorar headings factuais em geral.
3. Testar que **Art. 7º autoriza despesa sem limite** ainda é claim e é rejeitado contra evidência condicionada; manter citation IDs/negative assertions.
4. Repetir probes exact_article7/context_article7 em banco QA depois dos testes.

Critérios de aceite: Referência pura não causa rejeição; obrigação/condição falsa continua rejeitada; contexto de follow-up não alterado.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_grounding_service.py src/tests/test_strict_grounding.py. No navegador QA perguntar “O que prevê o art. 1º da Lei nº 8206/2026?” e depois “E o artigo 7?”; em outra conversa perguntar o art. 7º explicitamente. Verificar fontes/claims do art. 7º, sem exigir frase LLM idêntica. Registrar nova evidência por tarefa; não sobrescrever followup-runtime.json da auditoria.

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-006

Achados cobertos: IA-A-004

Objetivo: Registrar truncamento real na cobertura do contexto.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: IA-A-004: src/processing/rag_context_builder.py:105–139; 2026-10-02/context-boundary.json.

Arquivos a alterar:

- C:/Jurix/src/processing/rag_context_builder.py
- C:/Jurix/src/tests/test_rag_context_builder.py
- C:/Jurix/src/tests/test_answer_contract.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Reproduzir context-boundary.json com fonte de 38.000 caracteres e budget de 8.000.
2. Adicionar flag/intervalo por fonte para snippet cortado; incluir apenas texto efetivamente enviado na evidência de grounding.
3. Definir complete somente se todos os dispositivos previstos entraram e cada corpo entrou inteiro. Reescrever scope note quando último corpo foi parcial, mesmo se contagem de itens coincide.
4. Testar limite exatamente no boundary e corte em ementa/metadata anexada; coverage deve distinguir seleção de recuperação e contexto enviado.

Critérios de aceite: Probe passa a complete=false; nenhuma promessa de análise integral com snippet parcial; budgets continuam iguais.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_rag_context_builder.py src/tests/test_answer_contract.py

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-007

Achados cobertos: IA-A-005

Objetivo: Distinguir recuperação exata de similaridade.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: IA-A-005: src/apps/legislation/serializers.py:155–169; src/apps/core/static/js/jurix-rag.js:265; screenshot audit-20261002-source-expanded-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/serializers.py
- C:/Jurix/src/apps/core/static/js/jurix-rag.js
- C:/Jurix/src/tests/test_serializers.py
- C:/Jurix/tests/js/streaming.behavior.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Testar source match_kind=explicit_reference,similarity_score=0.
2. Adicionar match_kind ao schema serializado, inclusive dict/cache path; valor ausente continua compatível.
3. Renderizar explicit_reference como Dispositivo identificado sem percentual/faixa semântica; preservar whole_norma como escopo e semantic como score técnico opcional.
4. Não substituir todos os scores por 100% nem chamar correspondência de confiança jurídica.

Critérios de aceite: Art. 1 exato não mostra baixa correspondência0%; cache e fonte sem campo permanecem funcionais.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_serializers.py; node --test C:/Jurix/tests/js/streaming.behavior.test.mjs

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-008

Achados cobertos: UI-A-001

Objetivo: Conter ações de fontes em qualquer coluna.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UI-A-001: src/apps/core/static/css/jurix-rag.css:519; src/apps/core/static/css/jurix-figma.css:788; src/apps/core/static/js/chat.js:1000; screenshot audit-20261002-assistente-360.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/core/static/css/jurix-rag.css
- C:/Jurix/src/apps/core/static/css/jurix-figma.css
- C:/Jurix/tests/js/real.browser.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste geometry real da pill em coluna de 260px com contagem, badge longo e Ver fontes.
2. Definir proprietário CSS jurix-rag.css; retirar somente regras concorrentes da pill em jurix-figma.css.
3. Usar max-inline-size: 100%,min-width: 0 e wrapping; até 767px manter contagem/Ver fontes e mover badge longo para drawer. Não ocultar o próprio botão.
4. Testar contagens 1/24/100, labels longos, clear/dark e rail/expanded.

Critérios de aceite: Bounding box e texto/ação dentro do container em320/360; Ver fontes clicável, foco íntegro; não depender de overflow:hidden para passar.

Comandos de verificação: node --test C:/Jurix/tests/js/real.browser.test.mjs; browser pergunta artigo1 e drawer

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-009

Achados cobertos: UX-A-006

Objetivo: Criar título identificável para pergunta formatada recusada.

Esforço: P

Pré-requisitos: T-004. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-006: src/processing/conversation_titles.py:9,93; screenshot audit-20261002-history-menu-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/processing/conversation_titles.py
- C:/Jurix/src/tests/test_conversation_titles.py
- C:/Jurix/src/tests/test_chat_sessions_api.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste pergunta com 8.206/2026 e fontes vazias; titulo deve conter referência identificável, não só Pesquisa jurídica.
2. Reutilizar parse_normative_references em vez de _NORM limitado a dígitos; quando faltar tema fundamentado, usar Lei nº 8.206/2026 ou Art. 7 — Lei nº 8.206/2026.
3. Não gerar tema inventado; título específico salvo pelo usuário prevalece. Não invocar LLM bloqueante.
4. Manter truncamento seguro e HTML escapado nas APIs/UI.

Critérios de aceite: Formato pontuado reconhecido; título curto e não duplicação integral da pergunta; renamed title preservado.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_conversation_titles.py src/tests/test_chat_sessions_api.py

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-010

Achados cobertos: UX-A-007

Objetivo: Qualificar situação temporal na norma.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-007: src/apps/legislation/templates/legislation/norma_detail.html:145; src/processing/answer_contract.py:91; screenshot audit-20261002-norma-detail-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/templates/legislation/norma_detail.html
- C:/Jurix/src/apps/legislation/views.py
- C:/Jurix/src/tests/test_workspace_routes.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste data_vigencia preenchida com corpus unknown: não deve declarar vigente hoje.
2. Reutilizar o estado temporal/contexto usado pela timeline; mostrar Início de vigência registrado ou Situação atual não verificada no corpus, conforme metadata.
3. Manter datas existentes; não inferir data_vigencia quando ausente nem alterar modelos/corpus.

Critérios de aceite: Tabela e timeline coerentes; sem Vigente inferido só por data; data desconhecida explicitada.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_workspace_routes.py; browser /normas/3/ e /normas/4/

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-011

Achados cobertos: UX-A-002

Objetivo: Resolver norma exata antes da pesquisa por assunto.

Esforço: M

Pré-requisitos: T-004. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-002: src/apps/legislation/workspace_views.py:217; screenshot audit-20261002-legal-search-exact-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/workspace_views.py
- C:/Jurix/src/tests/test_workspace_routes.py
- C:/Jurix/src/processing/normative_reference.py (somente se helper compartilhado necessário)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste /pesquisa/?q=Lei+nº+8.206/2026: somente norma correspondente ou primeiro resultado explicitamente exato, sem ranking de colofões de outras leis.
2. Compartilhar resolução implementada na T-004; usar dispositivos da norma identificada, respeitando tipo/ano e filtros.
3. No caso de artigo específico escolher o dispositivo; no caso de lei inteira mostrar ementa/metadata, não cláusula genérica de vigência como melhor resumo.
4. Norma ausente retorna vazio qualificado; pesquisa por tema sem referência mantém estratégia atual.

Critérios de aceite: Consulta exata prioriza norma3; tema livre permanece; nenhuma alteração do ranking de histórico.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_workspace_routes.py; browser /pesquisa/

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-012

Achados cobertos: IA-A-003

Objetivo: Não gerar resposta com leis substitutas quando a norma exata falta.

Esforço: M

Pré-requisitos: T-004,T-006. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: IA-A-003: src/processing/adaptive_rag_service.py:395; src/processing/rag_context_builder.py:99; 2026-10-02/rag-runtime.json, missing_norm.

Arquivos a alterar:

- C:/Jurix/src/processing/adaptive_rag_service.py
- C:/Jurix/src/processing/rag_context_builder.py
- C:/Jurix/src/processing/answer_contract.py
- C:/Jurix/src/processing/rag_service.py
- C:/Jurix/src/apps/legislation/api_search.py
- C:/Jurix/src/tests/test_adaptive_retrieval.py
- C:/Jurix/src/tests/test_answer_contract.py
- C:/Jurix/src/tests/test_streaming_incremental.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste overview de 99999/2026 com corpus sem essa norma e fontes semanticamente parecidas; mock de LLM deve ter zero chamadas.
2. Produzir resultado estruturado norm_not_in_corpus para referência inequívoca ausente; separar da recuperação geral ambígua.
3. Retornar sources=[] e coverage correspondente ao escopo vazio; nunca marcar outras normas como whole_norma.
4. Propagar motivo aditivo ao contrato e ao evento done, mantendo a ordem/status existentes. O ramo no-results de RAGService já evita geração: reutilizá-lo após bloquear o fallback de outras leis. Implementar motivo norm_not_in_corpus tanto em answer_question quanto em stream_answer_question, com dados retornados explicitamente pela recuperação; não guardar motivo em estado mutável compartilhado entre requests. Não afirmar que a lei não existe no mundo, somente que não foi localizada no acervo.

Critérios de aceite: Zero geração/retry na ausência exata; fontes vazias; referência ambígua pede esclarecimento ou fluxo geral seguro.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_adaptive_retrieval.py src/tests/test_answer_contract.py src/tests/test_streaming_incremental.py src/tests/test_rag_stream_safety_v2.py. Testar endpoint síncrono e SSE com LLM mockado: zero chamadas, sources=[], reason=norm_not_in_corpus; consulta livre sem referência mantém comportamento.

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-013

Achados cobertos: IA-A-001

Objetivo: Validar sínteses de incisos por família de artigo sem enfraquecer segurança.

Esforço: G

Pré-requisitos: T-005,T-006. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: IA-A-001: src/processing/strict_grounding.py:422; src/processing/grounding_service.py:278; 2026-10-02/rag-runtime.json, caso overview.

Arquivos a alterar:

- C:/Jurix/src/processing/strict_grounding.py
- C:/Jurix/src/processing/grounding_service.py
- C:/Jurix/src/tests/test_strict_grounding.py
- C:/Jurix/src/tests/test_grounding_service.py
- C:/Jurix/src/tests/test_rag_stream_safety_v2.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Criar fixture caput + incisos do mesmo artigo e claim enumerativo; teste baseline deve falhar pelo apoio dividido.
2. Construir evidência composta adicional somente de dispositivos da mesma norma/artigo, com relação pai validada, texto efetivamente enviado e IDs individuais; não concatenar corpus inteiro.
3. Manter invariantes de números vinculados, modalidade, negação e condição; omitir desde que sem ônus deve continuar falhando. Também testar incisos de outro artigo/norma, referência inexistente e conteúdo truncado.
4. Reportar matches com cada citation_id/deviceID original, sem inventar um URL para evidência composta.
5. Revisar todos os diffs do checker antes de liberar próximo passo. Benchmark: válido agregado passa, inválido agregado falha; não baixar thresholds para salvar amostra.

Critérios de aceite: Sinteses equivalentes passam; alteração numérica/negação/condição rejeitada; matched sources mapeiam evidência real; overview QA responde ou reporta motivo específico verificável.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_strict_grounding.py src/tests/test_grounding_service.py src/tests/test_rag_stream_safety_v2.py. No navegador QA perguntar “O que prevê a Lei nº 8.206/2026? Explique seus principais dispositivos.”; inspecionar fonte de cada enumeração e manutenção de condições legais. Repetir a fixture negativa sem condição e confirmar recusa. Não exigir texto idêntico entre execuções do modelo.

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-014

Achados cobertos: UI-A-005

Objetivo: Expor associação entre claims verificados e fonte.

Esforço: M

Pré-requisitos: T-007,T-013. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UI-A-005: src/apps/legislation/serializers.py:158; src/apps/core/static/js/jurix-rag.js:255,322; screenshot audit-20261002-source-expanded-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/serializers.py
- C:/Jurix/src/apps/legislation/api_search.py
- C:/Jurix/src/apps/core/static/js/jurix-rag.js
- C:/Jurix/src/tests/test_serializers.py
- C:/Jurix/tests/js/streaming.behavior.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Definir evidence_contributions por citation_id com trechos de claims supported do contrato final; excluir unsupported e nunca usar texto LLM não validado.
2. Enviar campo aditivo no done; sources preliminar não pode afirmar contribuição ainda não verificada.
3. No drawer mostrar Sustenta: trecho do claim quando existente. Sem mapping: rotular Trecho recuperado, não Contribuição genérica.
4. Preservar agrupamento/IDs, hyperlink oficial e copyMarkdown; testar claims com várias fontes. O campo deve sobreviver à serialização dict/cache e restauração da sessão após F5; usar o mesmo serializer para resposta final e histórico, sem guardar HTML.

Critérios de aceite: Contribuição útil e rastreável; fonte apenas recuperada não é apresentada como apoio validado; nenhuma URL gerada peloLLM.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_serializers.py src/tests/test_streaming_incremental.py; node --test C:/Jurix/tests/js/streaming.behavior.test.mjs

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-015

Achados cobertos: UI-A-002

Objetivo: Reduzir composer móvel sem perder controles.

Esforço: M

Pré-requisitos: T-008. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UI-A-002: src/apps/legislation/templates/legislation/chatbot.html; src/apps/core/static/css/jurix-search-controls.css; screenshot audit-20261002-assistente-360.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/templates/legislation/chatbot.html
- C:/Jurix/src/apps/core/static/css/jurix-search-controls.css
- C:/Jurix/src/apps/core/static/css/jurix-chat.css
- C:/Jurix/src/apps/core/static/js/jurix-search-controls.js
- C:/Jurix/tests/js/real.browser.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Adicionar disclosure Opções de pesquisa com botão de 44px visível até 767px; nele colocar os controles já funcionais, sem recriar state/payload.
2. Manter textarea/send/cancel/attachment e garantir Enter/Shift+Enter/IME.
3. Ajustar spacing para altura ociosa ≤ 180px em 360×900; textarea crescente limitada a 30dvh. Não definir altura fixa que corte mensagens/erro.
4. Preservar todos os IDs data-control existentes e teclado/menuEsc; estado deve persistir ao mudar viewport.

Critérios de aceite: Composer ocioso ≤ 180px em 360×900; opções continuam no payload; cancelamento visível; nenhum overlap com a sidebar.

Comandos de verificação: node --test C:/Jurix/tests/js/real.browser.test.mjs C:/Jurix/tests/js/streaming.behavior.test.mjs; browser360/768/1280

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-016

Achados cobertos: UI-A-003

Objetivo: Compactar cabeçalho da biblioteca normativa.

Esforço: P

Pré-requisitos: T-004. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UI-A-003: src/apps/core/static/css/jurix-norma-list.css:68,104,126; src/apps/legislation/templates/legislation/norma_list.html; screenshot audit-20261002-normas-1280.jpg.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/templates/legislation/norma_list.html
- C:/Jurix/src/apps/core/static/css/jurix-norma-list.css
- C:/Jurix/tests/js/norma_ui_v3.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Trocar texto autorreferencial por instrução curta Buscar por número, ano ou assunto.
2. Unificar contagem corpus/resultados num único bloco; H1 máximo 2rem, margem entre seções de 24px, padding do hero ≤ 24px.
3. Preservar formulário/facets/contagem filtrada/pagination e ordenação por publicação.
4. A 1280×900 mostrar ao menos o primeiro resultado na primeira dobra; a 360px priorizar busca antes de estatísticas.

Critérios de aceite: Busca e resultado aparecem sem atravessar hero redundante; metadata ainda legível; rotas/filtros intactos.

Comandos de verificação: node --test C:/Jurix/tests/js/norma_ui_v3.test.mjs; & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_dynamic_suggestions_and_norma_list_v3.py

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-017

Achados cobertos: UI-A-004

Objetivo: Tornar índice normativo tocável sem produzir mural de chips.

Esforço: M

Pré-requisitos: T-002. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UI-A-004: src/apps/core/static/css/jurix-legal-detail.css:64; 2026-10-02/browser-metrics.json.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/templates/legislation/norma_detail.html
- C:/Jurix/src/apps/core/static/css/jurix-legal-detail.css
- C:/Jurix/src/apps/core/static/js/jurix-legal-detail.js
- C:/Jurix/src/tests/test_workspace_routes.py
- C:/Jurix/tests/js/real.browser.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Mostrar artigos principais num índice compacto e filhos em disclosure do artigo; preservar todos os href#dispositivo-ID e ordem normativa.
2. Área de 44px em toque; font-size ≥ .8125rem, gap de 8px; labels completos e sem Inciso duplicado.
3. Teste hash direto de um filho revela grupo correspondente e destaca/foca dispositivo; teclado opera disclosure. Não modificar estrutura/modelo de dispositivo.

Critérios de aceite: Alvos de 44px no móvel; todos os incisos acessíveis; deeplinks de artigos/incisos funcionam; sem rolagem horizontal.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_workspace_routes.py; node --test C:/Jurix/tests/js/real.browser.test.mjs

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-018

Achados cobertos: A11Y-A-001

Objetivo: Usar renderer canônico para conversa temporária.

Esforço: M

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: A11Y-A-001: src/apps/core/static/js/chat.js:553–599; screenshot audit-20261002-assistant-waiting-1280.jpg (estado registrado após espera); inspeção do primeiro envio.

Arquivos a alterar:

- C:/Jurix/src/apps/core/static/js/chat.js
- C:/Jurix/src/apps/core/static/js/jurix-sidebar.js
- C:/Jurix/tests/js/sidebar.unification.test.mjs
- C:/Jurix/tests/js/real.browser.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Teste com request pendente: existe exatamente uma linha temporária, nenhum estado vazio e nenhum role=button contendo button.
2. Adicionar entrada temporária ao renderer JurixSidebar.render; link e trigger irmãos; não criar markup paralelo em createSessionCardImmediately.
3. Reconciliar por client_session_id/server_id sem duplicar; falha deve permitir retomar/remover a conversa QA sem controles aninhados inválidos.
4. Preservar menu/pin/rename/classes de seleção e preferência de recolhimento; não inferir obrigação de recolhimento automático.

Critérios de aceite: Mesma SessionRow antes/depois de done; estado vazio não coexiste com conversa; foco e menus funcionam em todas as rotas.

Comandos de verificação: node --test C:/Jurix/tests/js/sidebar.unification.test.mjs C:/Jurix/tests/js/real.browser.test.mjs

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-019

Achados cobertos: PERF-A-001, IA-A-003

Objetivo: Mostrar espera e recusa com motivo útil sem rascunho jurídico.

Esforço: M

Pré-requisitos: T-012,T-013,T-014. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: IA-A-003: src/processing/adaptive_rag_service.py:395; src/processing/rag_context_builder.py:99; 2026-10-02/rag-runtime.json, missing_norm; PERF-A-001: src/processing/rag_service.py:735–802; src/apps/core/static/js/chat.js:1608–1658; 2026-10-02/rag-runtime.json.

Arquivos a alterar:

- C:/Jurix/src/processing/rag_contract_helpers.py
- C:/Jurix/src/apps/legislation/api_search.py
- C:/Jurix/src/apps/core/static/js/chat.js
- C:/Jurix/src/apps/core/static/js/jurix-chat-controller.js
- C:/Jurix/src/apps/core/static/css/jurix-chat-controller.css
- C:/Jurix/src/tests/test_streaming_incremental.py
- C:/Jurix/tests/js/streaming.behavior.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Adicionar reason codes norm_not_in_corpus, evidence_insufficient e generation_failed ao fallback/contrato. Se número/ano já foram enviados, não solicitar os mesmos dados novamente.
2. Mostrar status junto à resposta: “Consultando o acervo”, “Preparando a resposta”, “Conferindo referências”. Após 10s, mostrar tempo decorrido discreto; não inventar percentual de progresso.
3. Associar IDs ao receber sources, mas revelar fontes/copy juntos após grounded=true, com fade de 160ms. Em reduced-motion, revelar imediatamente.
4. Não expor chunks brutos do LLM nem refazer o texto no done quando já igual. Limpar timers em cancelamento, erro e navegação.
5. Usar role=status/aria-live=polite para mudanças de fase, sem anunciar o cronômetro a cada segundo. No resultado norm_not_in_corpus oferecer revisar o número ou pesquisar nas normas; não afirmar inexistência da lei.

Critérios de aceite: Feedback imediato e acessível; recusa distingue corpus/modelo; ações aparecem uma vez após validação; sem F5, rascunho ou perda de citações.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_streaming_incremental.py src/tests/test_rag_stream_safety_v2.py; node --test C:/Jurix/tests/js/streaming.behavior.test.mjs

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-020

Achados cobertos: SEC-A-001

Objetivo: Alinhar dependências Python num ambiente QA separado.

Esforço: M

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: SEC-A-001: requirements.txt:8,12,14; src/apps/ingestion/ocr_tasks.py:143; 2026-10-02/python-advisories.json.

Arquivos a alterar:

- C:/Jurix/requirements.txt
- C:/Jurix/src/tests/test_dependencies.py
- C:/Jurix/docs/production-readiness.md

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Registrar versões instaladas e declaradas; criar venv QA novo em C:/Users/Cauã V/AppData/Local/Temp/jurix-implementation-qa-20261002/venv. Se esse diretório existir, parar e pedir um caminho alternativo. Não alterar .venv ou .env atuais.
2. Confirmar em advisories/releases primários a disponibilidade e suporte de Requests 2.33.0 e Pillow 12.3.0; atualizar pins para esses valores se confirmados. Manter PyMuPDF declarado 1.28.2 somente após confirmar instalação compatível. Se indisponível, parar, não adivinhar versão.
3. Instalar requirements no venv QA. Instalar pip-audit somente como ferramenta desse venv, sem adicionar à produção. Rodar pip check e auditoria de toda a árvore.
4. Executar pytest, OCR, anexos e PDF com esse Python. Registrar pins/resultado e roteiro reproduzível. Não contar IDs duplicados GHSA/PYSEC como falhas únicas.

Critérios de aceite: Ambiente QA coerente com requirements; advisories aplicáveis resolvidos ou exceções revisadas; suíte/PDF passam; ambiente original preservado.

Comandos de verificação: & 'C:/Users/Cauã V/AppData/Local/Temp/jurix-implementation-qa-20261002/venv/Scripts/python.exe' -m pip check; usar o mesmo executável com -m pip_audit -r requirements.txt e -m pytest -q

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-021

Achados cobertos: SEC-A-002

Objetivo: Atualizar cadeia de testes browser sem fix--force.

Esforço: M

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: SEC-A-002: tests/js/package.json:10; tests/js/package-lock.json; 2026-10-02/npm-advisories.json.

Arquivos a alterar:

- C:/Jurix/tests/js/package.json
- C:/Jurix/tests/js/package-lock.json
- C:/Jurix/tests/js/real.browser.test.mjs (sóajusteAPInecessário)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Confirmar release/engines de **puppeteer-core** 25.12.0 e Node instalado antes da edição; se incompatível, parar. O audit sugeriu essa versão, mas não foi instalada durante auditoria. A chave real em package.json é puppeteer-core, não puppeteer; não adicionar uma segunda biblioteca ou downloader de Chromium.
2. Atualizar apenas puppeteer-core/lockfile em cópia QA de tests/js; executar npm ci, npm test e npm audit.
3. Se a API de testes mudou, adaptar apenas chamadas necessárias, sem enfraquecer assertivas de UI/segurança. Não incluir Puppeteer no bundle de produção.
4. Revisar diff de pins/lockfile e preservar os hunks preexistentes de testes. Não executar npm audit fix --force.

Critérios de aceite: npm test verde; os sete achados dev resolvidos ou exceções explicadas; auditoria de produção continua sem achados reportados.

Comandos de verificação: npm ci; npm test; npm audit --json; npm audit --omit=dev --json (cwd tests/js QA)

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-022

Achados cobertos: COD-A-001

Objetivo: Extrair orquestração de geração/validação de RAGService.

Esforço: M

Pré-requisitos: T-005,T-006,T-012,T-013. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: COD-A-001: src/processing/rag_service.py; 2026-10-02/architecture.json.

Arquivos a alterar:

- C:/Jurix/src/processing/rag_service.py
- C:/Jurix/src/processing/rag_answer_pipeline.py (novo)
- C:/Jurix/src/tests/test_rag_service.py
- C:/Jurix/src/tests/test_rag_stream_safety_v2.py

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Registrar sequência atual de cache/status/sources/chunk/done em testes antes de extrair.
2. Mover o laço de geração/validação/retry e captura de timings para rag_answer_pipeline.py com dependências explícitas. RAGService mantém a API pública; helper não ganha acesso ao banco por conta própria.
3. Preservar campos, ordem de eventos, exception handling e fingerprints de cache. Não mudar budgets, limiares ou ranking nesta tarefa.
4. Executar arquitetura e pytest completo; comparar saída antes/depois.

Critérios de aceite: rag_service.py ≤ 850 linhas; gate passed:true sem expandir limite; eventos/cache/grounding sem regressão.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q; & 'C:/Jurix/.venv/Scripts/python.exe' scripts/architecture_budget_v2.py --json docs/audit/QA_ARCHITECTURE.json

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-023

Achados cobertos: PERF-A-003

Objetivo: Centralizar tokens e retirar downloads de fontes desnecessários.

Esforço: M

Pré-requisitos: T-008,T-015,T-016. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: PERF-A-003: src/apps/legislation/templates/legislation/chatbot.html:21–33,284–306; 2026-10-02/asset-metrics.json; jurix-rag.css:519 e jurix-figma.css:788.

Arquivos a alterar:

- C:/Jurix/src/apps/core/static/css/jurix-tokens.css (novo)
- C:/Jurix/src/apps/core/static/css/jurix-figma.css
- C:/Jurix/src/apps/core/static/css/workspace.css
- C:/Jurix/src/apps/legislation/templates/legislation/chatbot.html
- C:/Jurix/src/apps/legislation/templates/legislation/workspace/base.html
- C:/Jurix/tests/js/visual.foundation.test.mjs (novo)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Implementar cores/espaços/type/motion da especificação proposta, mantendo aliases --figma-*. Carregar jurix-tokens.css antes dos componentes nos dois shells.
2. Retirar requisições preconnect/Google Fonts e usar a pilha de sistema já declarada. Não baixar fontes novas.
3. Padronizar corpo 1rem/1.65, metadata≥.8125rem e H1 workspace 1.5–2rem; preservar labels, texto jurídico e ícones próprios.
4. Testar temas, foco e contraste com fundos compostos; screenshots das nove telas antes/depois. Não apagar CSS sem uma regressão que exercite a regra removida.

Critérios de aceite: Sem requisições Google Fonts; aliases legados preservados; contrastes AA nos estados alterados; bundle local não aumenta.

Comandos de verificação: npm test em C:/Jurix/tests/js. No navegador QA abrir assistente, normas, detalhe, pesquisa, configurações, histórico, coleções, árvore e comparação em 320/360/768/1280/1920px, claro e escuro; verificar foco e registrar screenshots. Comparar somas de bytes dos mesmos CSS/JS locais carregados antes/depois com asset-metrics.json; não chamar bytes brutos de tamanho transferido. Confirmar ausência de links fonts.googleapis.com/fonts.gstatic.com no HTML e ausência de requisições correspondentes.

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-024

Achados cobertos: COD-A-003

Objetivo: Validar entradas de coleção no servidor.

Esforço: P

Pré-requisitos: Nenhuma. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: COD-A-003: src/apps/legislation/workspace_views.py:328–389; src/apps/legislation/models.py:626; templates/legislation/workspace/collections.html:48.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/workspace_views.py
- C:/Jurix/src/tests/test_collections_workspace.py
- C:/Jurix/src/apps/legislation/templates/legislation/workspace/collections.html
- C:/Jurix/src/apps/legislation/templates/legislation/workspace/collection_detail.html

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Criar testes com usuários QA: nome de 121 caracteres, descrição de 501 caracteres, norma_id texto/negativo/inexistente e coleção de outro proprietário.
2. Validar no servidor nome de 1–120 caracteres, descrição ≤ 500 caracteres e ID inteiro positivo antes do ORM; apresentar erros de campo e preservar valores.
3. Manter CSRF e owner filter; só anunciar sucesso quando a operação realmente ocorrer.
4. Rodar em SQLite de testes e, quando autorizado/configurado, Postgres QA. Não usar conta administrativa real.

Critérios de aceite: POST inválido não retorna 500 nem altera dados; erro ligado ao campo por label/aria-describedby; ownership preservado.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_collections_workspace.py

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-025

Achados cobertos: PERF-A-002

Objetivo: Criar contrato de cancelamento por turno com autorização.

Esforço: G

Pré-requisitos: T-019,T-022. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: PERF-A-002: src/apps/core/static/js/jurix-chat-api.js:159; src/apps/core/static/js/jurix-chat-controller.js:22; src/processing/rag_service.py:758.

Arquivos a alterar:

- C:/Jurix/src/apps/legislation/api_cancel.py (novo)
- C:/Jurix/src/apps/legislation/api_urls.py
- C:/Jurix/src/processing/generation_control.py (novo)
- C:/Jurix/src/apps/legislation/api_search.py
- C:/Jurix/src/tests/test_generation_cancel.py (novo)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. No queued, emitir cancel_token assinado com Django signing contendo UUID do turno e proprietário: user_id ou hash da sessão Django do visitante. TTL de 600s. client_session_id sozinho não é autorização.
2. Criar POST /api/v1/search/cancel/ com CSRF. Validar assinatura, TTL e proprietário antes de marcar o turno no cache.
3. Cache por turno com TTL de 600s; cancelar turno encerrado é no-op idempotente. Não colocar pergunta, resposta ou chave API no token/cache de controle.
4. Testar assinatura inválida, outro usuário/sessão, expiração, CSRF e isolamento entre turnos. LocMem suporta somente QA single-process; release multiworker exige backend compartilhado validado.

Critérios de aceite: Cancelamento de outro turno proibido; UUID do cliente não autoriza terceiros; autorização testada; ainda não prometer interrupção upstream.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_generation_cancel.py src/tests/test_streaming_incremental.py

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-026

Achados cobertos: PERF-A-002

Objetivo: Propagar cancelamento autorizado até consumo do LLM.

Esforço: G

Pré-requisitos: T-025. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: PERF-A-002: src/apps/core/static/js/jurix-chat-api.js:159; src/apps/core/static/js/jurix-chat-controller.js:22; src/processing/rag_service.py:758.

Arquivos a alterar:

- C:/Jurix/src/processing/rag_answer_pipeline.py
- C:/Jurix/src/processing/llm_provider.py
- C:/Jurix/src/llm_engine/ollama_service.py
- C:/Jurix/src/apps/core/static/js/jurix-chat-api.js
- C:/Jurix/src/apps/core/static/js/jurix-chat-controller.js
- C:/Jurix/src/tests/test_generation_cancel.py
- C:/Jurix/tests/js/streaming.behavior.test.mjs

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Receber should_cancel na orquestração e nos geradores Ollama/remotos; verificar antes da request, entre linhas/tokens e antes de retry/cache/save.
2. Cancelar fechando response/generator em finally; não matar Ollama nem salvar draft como resposta completed.
3. Frontend mantém token do turno ativo e faz POST cancel antes/independentemente de abort; preservar a pergunta, os turnos anteriores e retry idempotente.
4. Emitir terminal cancelled uma vez. Testar cancel durante retry, done concorrente e nova pergunta; FakeResponse deve registrar closed=true.
5. QA real: enviar pergunta sintética, cancelar e medir fechamento da conexão/ausência de segunda tentativa. Não prometer interrupção instantânea do processamento físico do provedor sem confirmação.
6. A verificação entre tokens não interrompe uma leitura bloqueada sem novos bytes. Usar timeout de leitura finito e teste de provedor silencioso; registrar o limite de latência de cancelamento, sem zerar timeout ou criar loop ocupado.

Critérios de aceite: Conexão upstream fechada; nenhuma persistência completed após cancelamento; um terminal; retry funcional; autorização mantida.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_generation_cancel.py src/tests/test_rag_stream_safety_v2.py; node --test C:/Jurix/tests/js/streaming.behavior.test.mjs

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-027

Achados cobertos: UX-A-005

Objetivo: Preparar reparação reversível dos sete colofões sem tocar acervo real.

Esforço: M

Pré-requisitos: T-020. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: UX-A-005: src/processing/legal_parser.py:75; src/apps/ingestion/management/commands/repair_legal_colophons.py:37; 2026-10-02/colophon-residuals.json.

Arquivos a alterar:

- C:/Jurix/docs/audit/QA_COLOPHON_REPAIR.md (novo)
- C:/Jurix/src/tests/test_colophon_repair_plan.py (se novo caso necessário)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Na cópia QA, reproduzir dispositivos 214, 288, 312, 346, 348, 353, 361. Ler src/apps/ingestion/management/commands/repair_legal_colophons.py e seu --help; executar inicialmente o dry-run sem --apply.
2. Confrontar datas OCR/SAPL e listar conflitos sem escolher automaticamente o footer. Revisar hash, backup e reversão já exigidos pelo comando.
3. Aplicar apenas em cópia QA explicitamente autorizada, com manifesto aprovado, hash exato e backup verificado. Checar revisão/invalidadores de cache/embeddings.
4. Registrar diff dos dados QA. Aplicação no banco real permanece pendência operacional que exige nova autorização do usuário.
5. Copiar no relatório o comando de aplicação exato mostrado por --help, somente após conferir os nomes de flags para manifesto/hash/backup. Se forem diferentes dos testes ou faltar aprovação de dados QA, parar; não inventar flags.

Critérios de aceite: Artigo final QA contém apenas texto legal; metadata separada; conflitos de datas não sobrescritos; banco real inalterado.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q src/tests/test_colophon_repair_plan.py; & 'C:/Jurix/.venv/Scripts/python.exe' manage.py repair_legal_colophons --help; executar dry-run apenas com DATABASES apontando comprovadamente à cópia QA.

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

### Tarefa: T-028

Achados cobertos: COD-A-002

Objetivo: Adicionar smoke integrado dos fluxos que a suíte atual não cobre.

Esforço: M

Pré-requisitos: T-001–T-027 aceitas; gates operacionais QA podem permanecer explicitamente pendentes. Serviço web QA apenas para passos de navegador; Ollama QA apenas para integração real, nunca para testes unitários mockados.

Evidência de entrada: COD-A-002: src/tests/test_workspace_routes.py:313; src/tests/test_legal_diff.py; tests/js/real.browser.test.mjs; coverage.json.

Arquivos a alterar:

- C:/Jurix/tests/js/jurix.audit-regressions.test.mjs (novo)
- C:/Jurix/src/tests/test_legal_user_journeys.py (novo)
- C:/Jurix/docs/audit/QA_RELEASE_CHECKLIST.md (novo)

Arquivos que NÃO devem ser tocados: todos os caminhos fora da lista acima, especialmente C:/Jurix/.env, C:/Jurix/db.sqlite3, C:/Jurix/config/settings.py, migrations, GOAL.md, relatórios originais de auditoria e hunks preexistentes. Se a implementação exigir outro caminho, parar e solicitar revisão do escopo.

Passos:

1. Criar corpus QA com artigos/incisos/cláusulas condicionais. Cobrir número formatado, overview, follow-up, norma ausente e PDF extraído.
2. Testar navegador contra Django QA em assistente, normas, detalhe, pesquisa, configurações, histórico, coleções, árvore e comparação nas cinco larguras.
3. Separar integração Ollama opcional da suíte rápida com mocks. No real, validar normas/fontes, condições, recusas e timings; não exigir frase textual idêntica.
4. Verificar Tab/Escape/foco, claro/escuro, reduced-motion emulado e zoom de 200% em navegador compatível. Se indisponível, registrar NV; não declarar conformidade.
5. Rodar todas as suítes/gates; check --deploy apenas com staging QA configurado e autorizado, sem substituir .env local.

Critérios de aceite: Falhas principais cobertas por regressões; todos os 27 achados mapeados a evidência/resultado; sem alegação genérica de compliance; PostgreSQL/Celery validados em QA ou gates pendentes.

Comandos de verificação: & 'C:/Jurix/.venv/Scripts/python.exe' -m pytest -q; & 'C:/Jurix/.venv/Scripts/python.exe' -m ruff check src config; & 'C:/Jurix/.venv/Scripts/python.exe' manage.py check; & 'C:/Jurix/.venv/Scripts/python.exe' scripts/architecture_budget_v2.py --json docs/audit/QA_ARCHITECTURE.json; & 'C:/Jurix/.venv/Scripts/python.exe' scripts/validate_documentation_contract.py; npm test em C:/Jurix/tests/js; executar a matriz visual descrita nos passos.

Rollback: seguir a regra comum: reverter somente o commit desta tarefa, se autorizado; caso contrário aplicar patch inverso somente dos próprios hunks, preservando baseline e dados. Nunca git checkout/reset/clean.

Se falhar: parar, apresentar teste/erro sanitizado e diff; não improvisar, não alterar arquivos fora da lista nem enfraquecer o critério de aceite.

## Handoff sugerido (não executar automaticamente)

“A implementação está autorizada somente para a T-001 deste guia proposto. Confirme main/HEAD/status e hashes; se diferirem, pare. Leia os quatro documentos propostos e execute T-001 preservando alterações preexistentes. Você está autorizado a criar um commit local contendo apenas os próprios hunks da T-001, sem push, merge ou troca de branch. Entregue diff, testes e páginas PDF renderizadas; pare para revisão antes da T-002.”

O texto acima é sugestão para o usuário autorizar posteriormente, **não autorização já concedida**. Se o usuário escolher outra branch, revalidar antes; o pacote descreve main local. Para continuidade ampla, obter autorização explícita de tarefas/commits e manter gates de revisão T-013/T-025/T-026.

