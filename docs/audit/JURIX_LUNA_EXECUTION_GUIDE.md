# Guia de execução para GPT 6.0 Luna — não executar durante a auditoria

Leia primeiro `docs/audit/JURIX_FULL_AUDIT.md`, depois `JURIX_MASTER_IMPLEMENTATION_PLAN.md` e `JURIX_DESIGN_SYSTEM_SPEC.md`. Este guia descreve uma etapa **futura**; a etapa atual não autoriza patch, commit, push ou troca de branch.

## Contrato de trabalho futuro

1. Conferir `git branch --show-current`, `git status --short`, `git diff`, `git diff --cached`, commit e testes antes de T-001. O snapshot auditado era branch `main` em `b2c8a2b`, com `GOAL.md` não rastreado e sem alterações de produto. O usuário desejou manter trabalho em `ui/pro-polish`; **não mudar branch automaticamente**. Se branch/estado diferir, parar e pedir decisão.
2. Executar **uma** tarefa por vez; antes e depois rodar os comandos da tarefa. Não alterar arquivos fora da lista. Não adicionar dependências, não alterar corpus real, migrations ou settings locais. Criar testes em arquivos novos só quando a tarefa nomeá-los. Não presumir que o achado ainda exista: conferir as linhas indicadas na auditoria antes de editar.
3. Se uma etapa, teste ou pré-condição falhar, **parar e relatar a saída sem segredos; não improvisar**. Não consertar um segundo problema no mesmo commit. Usar `apply_patch` e inspecionar `git diff --check`/diff final. Commit só após autorização do usuário para a fase de implementação. Cada rollback abaixo é `git revert <hash-do-commit-da-tarefa>` após verificar que o commit contém só essa tarefa; não usar reset/clean.
4. Baseline conhecido: `python -m pytest -q src/tests` = 669 passed/6 skipped; `npm test` passou; `python manage.py check` passou; `ruff check .` já tem duas I001 (T-017). Não atribuir essa falha preexistente às T-001–T-016. Usar `.venv\Scripts\python.exe` no Windows.

## Tarefas atômicas

### T-001 — estado de grounding no contrato de fontes

- **Achados cobertos:** A-IA-001. **Objetivo:** resposta insuficiente nunca receber selo de alta correspondência ou fonte apresentada como sustentação.
- **Pré-requisitos:** baseline registrado; fixture de streaming existente. **Arquivos a alterar:** `src/apps/legislation/api_search.py`, `src/apps/legislation/api_chat.py`, `src/apps/core/static/js/chat.js`, `src/tests/test_rag_stream_safety_v2.py`, `src/tests/test_chat_sessions_api.py`, `tests/js/streaming.behavior.test.mjs`. **Não tocar:** `src/processing/rag_service.py`, modelos, migrations, corpus, configuração Ollama.
- **Passos:** 1. Em `api_search.py:483-491`, adicionar `grounded=bool(item.get('grounded'))` ao evento done sem retirar chaves; ao persistir mensagem, usar `sources_json=sources_list if grounded else []` e registrar `grounded` em metadata_json. 2. Em `chat.js:1610-1625`, só chamar `linkLegalReferences` e `showSourcesGradually` se `done.grounded === true`; no ramo falso, mostrar “Evidências recuperadas, mas insuficientes para fundamentar a resposta” sem selo. 3. Em `api_chat.py:187-232`, aplicar o mesmo filtro `response.get('grounded')` a fontes persistidas e retornadas pela regeneração; incluir grounded no JSON da resposta. 4. Cobrir stream, F5/restauração e regeneração com grounded true/false em testes sintéticos. Não alterar evento preliminar `sources` nem SSE incremental.
- **Aceite:** done preserva JSON anterior + booleano; falso não exibe nem persiste badge/links de sustentação; verdadeiro exibe apenas após conclusão; F5 e regeneração preservam a regra. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_rag_stream_safety_v2.py src/tests/test_chat_sessions_api.py`; `node --test tests/js/streaming.behavior.test.mjs`; `npm test`. **Rollback:** revert do commit T-001. **Se falhar:** parar, anexar evento sintético e diff.

### T-002 — GET do assistente sem escrita

- **Achados:** A-COD-015. **Objetivo:** navegar/F5 não criar sessão anônima nem alterar `is_active`. **Pré-requisitos:** T-001; banco de teste isolado. **Arquivos:** `src/apps/legislation/views.py`, `src/tests/test_chat_session_slug.py`, `src/tests/test_workspace_routes.py`. **Não tocar:** migrations, banco real, `GOAL.md`, URLs públicas.
- **Passos:** 1. Em `views.py:427-440`, remover update/save de `is_active` no ramo GET; manter consulta por slug e autorização. 2. Em `:453-461`, não escrever `temp_chat_session_id` em GET; usar identificador já existente se houver, ou renderizar estado inicial sem ID e deixar o primeiro POST criar sessão. 3. Localizar quem lê `current_session_id` no template/JS antes de finalizar; se o fluxo exige ID em GET, parar e especificar migração do primeiro POST em vez de inventar contrato. 4. Testar dois GETs anônimos e autenticados, sem `session.modified`, sem nova ChatSession e sem mudança `is_active`; testar envio inicial separadamente.
- **Aceite:** GET idempotente e primeiro envio ainda funciona. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_chat_session_slug.py src/tests/test_workspace_routes.py src/tests/test_chatbot_view_post.py`; `npm test`. **Rollback:** revert T-002. **Se falhar:** parar, registrar contrato dependente de ID.

### T-003 — destinos do provedor compatível

- **Achados:** A-SEC-016. **Objetivo:** em produção, cliente não escolhe host/porta/caminho internos arbitrários. **Pré-requisitos:** T-002; acordar política de implantação/allowlist com responsável. **Arquivos:** `src/processing/llm_provider.py`, `config/settings.py`, `src/tests/test_llm_provider.py`. **Não tocar:** `.env`, chaves, `docker-compose.yml`, provedores externos oficiais.
- **Passos:** 1. Definir setting de allowlist de URLs base exatas, vazio por padrão de produção; modo desenvolvimento local explícito e isolado. 2. Normalizar URL com `urlparse`, rejeitar userinfo, query, fragmento, caminho inesperado, porta não permitida e URL fora da allowlist em produção; validar novamente antes de `requests.post`. 3. Preservar `allow_redirects=False`. 4. Testar localhost/host.docker.internal arbitrário negado em produção, URL exata permitida, subdomínio/porta/path parecidos negados, dev explícito mantido. Não fazer POST de teste a serviço real.
- **Aceite:** testes demonstram negação sem tráfego de rede; provedores OpenAI/Gemini/etc. inalterados. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_llm_provider.py`; `.venv\Scripts\python.exe manage.py check`. **Rollback:** revert T-003. **Se falhar:** parar e pedir regra de endpoints permitidos; não adivinhar.

### T-004 — filtros antes de LIMIT

- **Achados:** A-IA-002. **Objetivo:** resultado filtrado não desaparecer por estar após o top 50 global. **Pré-requisitos:** T-003; banco de teste SQLite e teste PostgreSQL se disponível. **Arquivos:** `src/processing/rag_service.py`, `src/apps/legislation/workspace_views.py`, `src/tests/test_rag_service.py`, `src/tests/test_workspace_routes.py`. **Não tocar:** modelos/migrations, pesos globais de ranking, pipeline SAPL.
- **Passos:** 1. Adicionar argumentos opcionais `norma_type` e `year` em `semantic_search`, com defaults para chamadas antigas. 2. Aplicar filtros na query por `dispositivo__norma__tipo` e `__ano` antes de ordenar/LIMIT, inclusive no ramo lexical SQLite. 3. Passar os argumentos na view; remover o pós-filtro redundante, preservando deduplicação. 4. Criar fixture com 50 melhores globais fora do filtro e 1 válido; conferir que aparece com filtro e contrato sem filtro é igual.
- **Aceite:** fixture 51 passa em ambos os backends testáveis; ausência de filtro não muda API. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_rag_service.py src/tests/test_workspace_routes.py`; `.venv\Scripts\python.exe manage.py check`. **Rollback:** revert T-004. **Se falhar:** parar com SQL/fixture, sem mexer em corpus.

### T-005 — rótulo de fallback real

- **Achados:** A-IA-003. **Objetivo:** não chamar busca lexical SQLite de semântica. **Pré-requisitos:** T-004. **Arquivos:** `src/processing/rag_service.py`, `src/apps/legislation/workspace_views.py`, `src/apps/legislation/templates/legislation/workspace/search.html`, `src/tests/test_workspace_routes.py`. **Não tocar:** modelos, embeddings, ranking.
- **Passos:** 1. Definir como `semantic_search` comunica modo efetivo sem quebrar seus chamadores; preferir metadado de retorno opt-in à mudança obrigatória de tipo. 2. Na view, exibir `lexical` quando SQLite segue `_lexical`; manter `semantic` para pgvector e distinguir erro de zero resultados. 3. Testar cada ramo com mock de backend.
- **Aceite:** SQLite exibe “Busca textual”; PostgreSQL exibe semântica; erro mostra fallback. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py src/tests/test_rag_service.py`; inspeção de `/pesquisa/?q=IPTU` em QA isolado. **Rollback:** revert T-005. **Se falhar:** parar, não renomear toda a API.

### T-006 — resultado aponta ao dispositivo

- **Achados:** A-UX-004. **Objetivo:** clique no resultado abre o artigo exato. **Pré-requisitos:** T-005. **Arquivos:** `src/apps/legislation/templates/legislation/workspace/search.html`, `src/tests/test_workspace_routes.py`. **Não tocar:** `norma_detail.html`, modelos, JS de chat.
- **Passos:** 1. Acrescentar `#dispositivo-{{ result.dispositivo.pk }}` ao `href` da norma em `search.html:33` apenas quando PK existir. 2. Testar href e alvo DOM existente para resultado de fixture. 3. Validar abertura por mouse/Enter em viewport 360 e 1280 sem novo scroll horizontal.
- **Aceite:** URL final tem fragmento de dispositivo válido; resultado sem dispositivo mantém URL base. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py`; `npm test`. **Rollback:** revert T-006. **Se falhar:** parar se a deduplicação não expuser PK.

### T-007 — prévia correta do histórico

- **Achados:** A-UX-005. **Objetivo:** prévia mostrar pergunta inicial, não resposta. **Pré-requisitos:** T-006. **Arquivos:** `src/apps/legislation/workspace_views.py`, `src/tests/test_workspace_routes.py`, `src/apps/legislation/templates/legislation/workspace/history.html` somente se o nome de variável mudar. **Não tocar:** título gerado, armazenamento de mensagens, migrations.
- **Passos:** 1. O prefetch atual traz apenas as **20 mensagens mais recentes**; portanto, não escolher `first_user` dessa lista como “pergunta inicial”. Anotar `ChatSession` com `Subquery(ChatMessage.objects.filter(session_id=OuterRef('pk'), role='user').order_by('created_at','pk').values('content')[:1])` e usar o valor como `primary_query`; importar `OuterRef, Subquery` em `workspace_views.py`. 2. Usar “Sem consulta registrada” quando nulo e manter escape do template. 3. Fixture com mais de 20 mensagens, título, pergunta inicial, pergunta recente e resposta diferentes comprova valor exibido.
- **Aceite:** pergunta é prévia e HTML não é interpretado. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py`; `npm test`. **Rollback:** revert T-007. **Se falhar:** parar e indicar formato real das mensagens.

### T-008 — copy limitada ao produto entregue

- **Achados:** A-UX-006. **Objetivo:** evitar promessa de jurisprudência/evidência em Coleções. **Pré-requisitos:** T-007. **Arquivos:** `src/apps/legislation/templates/legislation/workspace/collections.html`, `src/apps/legislation/templates/legislation/chatbot.html`, `src/tests/test_workspace_routes.py`. **Não tocar:** RAG, modelos Collection, catálogo SAPL.
- **Passos:** 1. Substituir em `collections.html:10,30` “pesquisas/evidências” por “normas salvas”. 2. Substituir em `chatbot.html:285` jurisprudência por “normas, artigos ou legislação municipal”. 3. Testar textos renderizados anônimo/autenticado e verificar não haver outras promessas na mesma tela.
- **Aceite:** os dois estados vazios descrevem apenas funções implementadas. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py`; `npm test`. **Rollback:** revert T-008. **Se falhar:** parar diante de copy conflitante, não remover funcionalidades.

### T-009 — semântica do botão de anexo

- **Achados:** A-A11Y-008. **Objetivo:** tecnologia assistiva não anunciar menu inexistente. **Pré-requisitos:** T-008. **Arquivos:** `src/apps/core/static/js/jurix-search-controls.js`, `tests/js/search-controls.test.mjs`. **Não tocar:** upload backend, tipos MIME, política de anexos.
- **Passos:** 1. Na iteração de `wire()` em torno de `:144`, aplicar `aria-haspopup=menu`/`expanded`/`controls` apenas a escopo e modo. 2. Para `attachment`, remover esses atributos; preservar nome e clique do input. 3. Testar Enter/Espaço, atributos do DOM e foco após seletor cancelado.
- **Aceite:** anexo é botão comum; demais menus mantêm ARIA correto. **Verificar:** `node --test tests/js/search-controls.test.mjs`; `npm test`. **Rollback:** revert T-009. **Se falhar:** parar com árvore DOM observada.

### T-010 — erro associado ao campo de provedor

- **Achados:** A-A11Y-009. **Objetivo:** erro local identificável por campo. **Pré-requisitos:** T-009. **Arquivos:** `src/apps/core/static/js/workspace.js`, `src/apps/legislation/templates/legislation/workspace/settings.html`, `src/tests/test_workspace_routes.py`, `tests/js/real.browser.test.mjs`. **Não tocar:** armazenamento de chave, endpoint, settings Django.
- **Passos:** 1. Dar `id` estável à ajuda/erro de modelo, chave e endpoint. 2. Em `workspace.js:137-149`, marcar `aria-invalid=true`, associar `aria-describedby` ao erro de cada campo ausente e focar o primeiro; limpar atributos quando válido ou ao mudar provedor. 3. Preservar resumo geral em região `role=status`; nunca inserir valor da chave na mensagem. 4. Testar vazio e correção em navegador.
- **Aceite:** campo inválido anuncia erro correspondente, foco vai ao primeiro, estado limpo após correção. **Verificar:** `node --test tests/js/real.browser.test.mjs`; `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py`. **Rollback:** revert T-010. **Se falhar:** parar, não mexer na persistência da chave.

### T-011 — controles legíveis a 360 px

- **Achados:** A-UX-007. **Objetivo:** escopo e modo visíveis sem elipse em mobile. **Pré-requisitos:** T-010. **Arquivos:** `src/apps/core/static/css/jurix-figma.css`, `tests/js/real.browser.test.mjs`. **Não tocar:** rótulos semânticos, JS de busca, sidebar.
- **Passos:** 1. Em media query até 399 px substituir duas colunas de `:1782-1795` por uma coluna com largura disponível e `white-space:normal` nos rótulos; manter botão de anexo acessível. 2. Medir overflow e altura em 360/768/1280 e ambos temas. 3. Capturar comparação sem dados pessoais.
- **Aceite:** texto de ambos controles integral; nenhum overflow horizontal; alvos separados. **Verificar:** `node --test tests/js/real.browser.test.mjs`; `npm test`; navegador 360/768/1280. **Rollback:** revert T-011. **Se falhar:** parar com screenshot e largura computada.

### T-012 — tipografia de ajuda

- **Achados:** A-UI-010. **Objetivo:** ajuda e labels legíveis sem ampliar layout indevidamente. **Pré-requisitos:** T-011. **Arquivos:** `src/apps/core/static/css/workspace.css`, `tests/js/real.browser.test.mjs`. **Não tocar:** tokens globais, texto jurídico, componentes do chat.
- **Passos:** 1. Revisar apenas seletores de `workspace.css:52,59,61,70-77`; labels/ajuda `0.875rem` com line-height ≥1.4 e metadados não essenciais ≥`0.75rem`. 2. Medir contraste do par real em claro/escuro. 3. Verificar 360/768/1280 e zoom 200% na tela Configurações.
- **Aceite:** sem clipping, foco e texto preservados, contraste mínimo aplicável comprovado por medição. **Verificar:** `npm test`; navegador em 200% e dois temas. **Rollback:** revert T-012. **Se falhar:** parar se o par de cor não atingir 4,5:1; abrir tarefa distinta para cor.

### T-013 — fonte e CSP consistentes

- **Achados:** A-UI-011. **Objetivo:** HTML não pedir fonte bloqueada por CSP estrita. **Pré-requisitos:** T-012; decisão entre fonte local licenciada e fallback de sistema. **Arquivos:** `src/apps/legislation/templates/legislation/workspace/base.html`, `src/apps/legislation/templates/legislation/chatbot.html`, `src/apps/core/static/css/jurix-figma.css`, `src/tests/test_workspace_routes.py`. **Não tocar:** `config/middleware.py`, CSP de produção, baixar fonte sem licença.
- **Passos:** 1. Escolher fallback de sistema se não houver licença/asset local; remover/prevenir links Google em produção sem CSP_ALLOW_GOOGLE_FONTS, preservando dev quando explicitamente habilitado. 2. Se usar flag no template, fornecer via contexto seguro existente; não expor valores de `.env`. 3. Testar HTML com flag false/true e navegador com CSP estrita, observando console/network; comparar quebra de linha de título.
- **Aceite:** flag false = zero request remoto de fonte; true = comportamento intencional; texto legível em fallback. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py`; `.venv\Scripts\python.exe manage.py check`; navegador em modo CSP. **Rollback:** revert T-013. **Se falhar:** parar e registrar decisão de licença/contexto pendente.

### T-014 — histórico além de 500 sessões

- **Achados:** A-PERF-012. **Objetivo:** busca e paginação alcançam sessão 501 sem carregar 500 objetos em memória. **Pré-requisitos:** T-007 e T-013; fixture isolada >500. **Arquivos:** `src/apps/legislation/workspace_views.py`, `src/tests/test_workspace_routes.py`, `src/apps/legislation/templates/legislation/workspace/history.html` somente se contrato de paginação mudar. **Não tocar:** modelos/migrations, sessões reais, JS de swipe/delete.
- **Passos:** 1. Registrar que `_rank_history` hoje calcula peso tipo BM25 em Python sobre as 500 sessões; o novo contrato SQL será **peso por presença**, não frequência: título com a frase exata = 100 pontos, cada token (até 8) no título = 10, cada token em mensagem = 1. Aprovar essa troca de ranking antes de editar. 2. Para cada token usar `Exists(ChatMessage.objects.filter(session_id=OuterRef('pk'), content__icontains=term))` e `Case/When` para somar pontuação no queryset; filtrar por score>0, ordenar `-score,-updated_at,-pk`; sem `[:500]` e sem join multiplicador. 3. `Paginator(queryset,20)` no banco; só então prefetch das mensagens dos 20 cards da página. Manter subquery da pergunta inicial de T-007. 4. Fixture com 501 sessões, busca por token exclusivo da 501ª, empate e múltiplas mensagens da mesma sessão; testar página final e contagem de queries. Se negócio exigir BM25 integral, parar e planejar FTS5/PostgreSQL FTS em tarefa separada, sem fallback ilimitado em Python.
- **Aceite:** sessão 501 encontrada e paginação estável; consultas/payload limitados por página. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_workspace_routes.py`; `.venv\Scripts\python.exe -m pytest -q src/tests/test_chat_sessions_api.py`; medir SQL em fixture. **Rollback:** revert T-014. **Se falhar:** parar com plano SQL e divergência SQLite/PostgreSQL; não usar busca Python ilimitada.

### T-015 — comparação longa limitada e explícita

- **Achados:** A-PERF-013. **Objetivo:** comparação patológica não travar request nem truncar silenciosamente. **Pré-requisitos:** T-014; fixture de norma longa. **Arquivos:** `src/apps/legislation/views.py`, `src/apps/legislation/templates/legislation/norma_compare.html`, `src/tests/test_workspace_routes.py` ou novo `src/tests/test_norma_compare_limits.py`. **Não tocar:** texto consolidado, eventos normativos, dados reais.
- **Passos:** 1. Medir com fixture repetitiva (tempo e linhas) antes de alterar. 2. Estabelecer limite documentado de linhas/caracteres para execução síncrona antes de `SequenceMatcher(autojunk=False)`; acima dele apresentar estado “comparação grande indisponível nesta visualização” com links para versões completas, não diff parcial disfarçado. 3. Testar abaixo/acima do limite e proteção de autorização/URL. Se produto exigir comparação integral, parar e abrir tarefa de processamento assíncrono em vez de improvisar.
- **Aceite:** request longo tem limite mensurável e UI explícita; comparação curta idêntica. **Verificar:** teste de comparação novo + `.venv\Scripts\python.exe -m pytest -q src/tests`; `npm test`. **Rollback:** revert T-015. **Se falhar:** parar e reportar baseline de tempo.

### T-016 — ordenação jurídica numérica

- **Achados:** A-COD-014. **Objetivo:** “recentes” ordenar leis 9/10 corretamente no mesmo ano na web e API. **Pré-requisitos:** T-015; regra de recência aprovada (número ou publicação). **Arquivos:** `src/apps/legislation/views.py`, `src/apps/legislation/api_normas.py`, `src/tests/test_dynamic_suggestions_and_norma_list_v3.py`, `src/tests/test_workspace_routes.py`. **Não tocar:** `models.py`, migrations, dados.
- **Passos:** 1. Registrar critério escolhido no teste (sugestão: publicação DESC com fallback ano/número). 2. Aplicar mesma expressão/ordem estável nas duas queries, evitando cast que quebre numeração alfanumérica; se formato real tiver sufixos não tratados, parar. 3. Fixture 9/10 e empate valida web/API.
- **Aceite:** web/API iguais e ordem 10 antes de 9 em recência numérica. **Verificar:** `.venv\Scripts\python.exe -m pytest -q src/tests/test_dynamic_suggestions_and_norma_list_v3.py src/tests/test_workspace_routes.py`; `.venv\Scripts\python.exe manage.py check`. **Rollback:** revert T-016. **Se falhar:** parar com exemplos de números fora do contrato.

### T-017 — gate Ruff

- **Achados:** A-COD-017. **Objetivo:** corrigir apenas as duas I001 observadas. **Pré-requisitos:** T-016; `ruff check .` ainda acusa somente elas. **Arquivos:** `src/apps/legislation/serializers.py`, `src/tests/test_source_urls.py`. **Não tocar:** restante do repositório, lógica, snapshots.
- **Passos:** 1. Rodar Ruff e comparar IDs. 2. Ordenar imports nesses dois arquivos apenas (`ruff check --select I --fix` com arquivos explícitos ou patch revisado). 3. Inspecionar diff para confirmar ausência de comportamento novo.
- **Aceite:** Ruff verde e diff só de imports. **Verificar:** `.venv\Scripts\python.exe -m ruff check .`; `.venv\Scripts\python.exe -m pytest -q src/tests`; `npm test`; `.venv\Scripts\python.exe manage.py check`; `git diff --check`. **Rollback:** revert T-017. **Se falhar:** parar com output completo sem secrets.

## Gate de entrega após T-017

Nenhuma tarefa acima prova completude de corpus, WCAG AA integral, métricas de campo nem funcionamento real do Ollama/Celery. Validar esses itens em ambiente isolado e registrar achados novos. Não fazer merge/push automaticamente. Conferir diff de cada commit, Git final e relatório de testes, inclusive skips e exceções de ambiente.
