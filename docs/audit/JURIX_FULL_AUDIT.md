# Auditoria técnica e de experiência do Jurix

Data: 30/09/2026. Fonte de verdade: checkout local C:\Jurix, commit b2c8a2ba54a08eb8478359f5d18965346cd388ce. Escopo: observação e planejamento; nenhum código de produto foi alterado.

## Resumo executivo

O produto apresenta um shell coerente, busca normativa, detalhes com árvore/comparação, histórico e um contrato SSE com estados explícitos. O navegador carregou 80 combinações de rota, tema e viewport com HTTP 200, sem erro JavaScript de página nem rolagem horizontal global. A suíte Python passou (669 testes, 6 ignorados) e o comando npm test passou. Isso comprova um bom piso de regressão, não conformidade WCAG ou qualidade de respostas jurídicas.

Os riscos com maior impacto são: (1) a interface ainda pode mostrar fontes e selo de correspondência após uma resposta rejeitada pelo grounding; (2) filtros de tipo/ano na pesquisa são aplicados após os primeiros 50 dispositivos, podendo ocultar uma norma pertinente; (3) GET da conversa altera estado de sessão. A fonte local examinada continha dez normas consolidadas; não há metadado auditado aqui que prove cobertura integral do SAPL. Não inferir completude do acervo a partir da prontidão do processo.

**Fluxos presumidos centrais:** perguntar ao assistente e conferir fontes; pesquisar por assunto ou identificador; ler norma e dispositivo; comparar versões e verificar vigência; recuperar histórico. **Fluxos de IA/assíncronos:** SSE e grounding, Ollama/embedding, ingestão e sincronização SAPL via Celery. Essa priorização é inferida das rotas e da apresentação em README.md:428-552; não substitui pesquisa com usuários.

## Estado local, ambiente e metodologia

- Git inicial: branch main, sem staged nem unstaged; GOAL.md era o único arquivo não rastreado. main e origin/ui/pro-polish apontavam ao mesmo commit b2c8a2b; main estava 108 commits à frente de origin/main. Não houve fetch, pull, push, commit ou troca de branch. O diff relevante do working tree era vazio. **A preferência anterior por ui/pro-polish não coincide com o checkout atual**; a proibição explícita de trocar branch nesta auditoria prevaleceu. Nada foi publicado nem mesclado.
- Recursos detectados: Python 3.12 em .venv, Node com dependências instaladas, Chrome/Edge via Puppeteer, Docker com web/PostgreSQL/Redis/worker/beat saudáveis, Ollama escutando localmente. Configurações consultadas: README.md:237-345, pyproject.toml:54-63, config/settings.py:145-176 e :224-390, docker-compose.yml e docker-compose.dev.yml. Nenhum valor de .env foi copiado.
- Execução real: servidor de QA preexistente em 127.0.0.1:8005, navegador novo sem login ou histórico pessoal, somente GET nas rotas de produto e ações locais sem submit ao servidor. Capturas em screenshots/ e métricas em runtime-manifest.json, geradas por capture_runtime.mjs. Quatro larguras (360, 768, 1280, 1920), dois temas, dez rotas, 80 imagens. Conteúdo jurídico com possíveis nomes foi desfocado no registro visual; as métricas foram colhidas antes do desfoque. O script exige opção explícita para incluir /assistente/ numa nova execução, pois o GET escreve sessão temporária.
- Resultado das capturas: 80/80 HTTP 200, sem pageerror registrado, sem overflow horizontal global. A paleta abriu com Ctrl+K no assistente; a expansão do texto integral e a revelação dos campos de provedor remoto funcionaram. Isso não testa cada interação de cada tela. Os testes de navegador sintéticos em tests/js/real.browser.test.mjs cobrem parte de drawer, foco, histórico e estados do chat, sem acessar dados do usuário.
- Verificações: manage.py check: 0 issues. manage.py check --deploy: 3 erros e 7 avisos ao avaliar a configuração de desenvolvimento ativa (DEBUG/chave de desenvolvimento/hosts), resultado esperado para esse ambiente, não evidência de implantação insegura. npm test: código 0. pytest -q src/tests: 669 passed, 6 skipped, 7 warnings, 45,50 s. ruff check .: falhou em duas ocorrências I001. Liveness em :8005 respondeu 200; readiness em :8005 respondeu 503 por “redis probe timeout”; readiness no contêiner :8000 respondeu ready. Essa divergência é do ambiente de QA, não foi classificada como defeito de produção.
- Limite operacional descoberto durante a captura: views.py:427-440 grava uma sessão Django de visitante e atualiza a sessão ativa autenticada em GET. As primeiras capturas do assistente criaram sessões anônimas efêmeras no banco local de QA antes da descoberta; nenhum registro preexistente foi editado intencionalmente e nenhum cleanup foi executado. Novos GETs dessa rota foram interrompidos. Não foram enviados prompts ao Ollama nem tarefas Celery, pois esses fluxos podem gravar mensagens/corpus no banco real.
- Não testado em runtime: sessão autenticada, POST/DELETE de coleções e histórico, upload, streaming real, falhas do Ollama/Celery, pipeline SAPL, edição do admin, zoom 200%, leitor de tela, LCP/INP/CLS p75 e plano de consulta PostgreSQL. Marcar esses fluxos como pendentes, mesmo com testes unitários/sintéticos.

### Fontes oficiais consultadas

HIG princípios/layout/alvos/movimento: https://developer.apple.com/design/human-interface-guidelines/design-principles ; https://developer.apple.com/design/human-interface-guidelines/layout ; https://developer.apple.com/design/human-interface-guidelines/accessibility ; https://developer.apple.com/design/human-interface-guidelines/motion . Material 3: https://m3.material.io/foundations (página oficial exige JavaScript nesta ferramenta; somente descrição indexada verificada, portanto recomendações M3 são **parcialmente verificadas**). Heurísticas: https://www.nngroup.com/articles/ten-usability-heuristics/ . Formulários e tabelas: https://design-system.service.gov.uk/components/error-summary/ ; https://carbondesignsystem.com/components/data-table/usage/ . WCAG: https://www.w3.org/TR/WCAG22/ ; https://www.w3.org/WAI/WCAG22/Understanding/target-size-minimum ; https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html . Performance: https://web.dev/articles/vitals . Segurança: https://top10.owasp.org/2021/ ; https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html . Sem cópia de marcas ou componentes dessas fontes.

## Inventário de rotas, telas, estados e arquivos

Arquivos base: config/urls.py:9-15; src/apps/legislation/workspace_urls.py:8-19; src/apps/legislation/urls.py:10-22; src/apps/legislation/api_urls.py:14-64. Todas as telas workspace herdam templates/legislation/workspace/base.html e carregam jurix-figma.css, workspace.css, jurix-components.css, workspace.js e command_palette.js; o chat usa chatbot.html e módulos próprios.

| Rota/tela | View/template | CSS/JS específico; estados/formulários | Runtime |
| --- | --- | --- | --- |
| / | RedirectView em config/urls.py:10 | redireção para /assistente/ | 302 |
| /assistente/ | views.py:408, chatbot.html | jurix-chat*.css, jurix-rag.css, chat.js, jurix-chat-api.js, jurix-search-controls.js; inicial, composer, sugestões, filtros, anexo, streaming, erro, drawer e paleta | inicial/paleta sim; streaming/anexo real não |
| /assistente/<session_slug>/ | mesma view/template | restauração, retry, fontes, foco | não testado em runtime |
| /normas/chatbot/ e /normas/chatbot/<session_slug>/ | urls.py:14-15 chama views.chatbot_view | mesmo chat legado; o código atual não usa as funções de redireção definidas em workspace_views.py:134-149 | não testado |
| /pesquisa/ | workspace_views.py:166, workspace/search.html | workspace.css; busca GET, filtros, resultados, vazio, fallback e erro | vazio e consulta de teste sim |
| /normas/ | views.py:82, norma_list.html | jurix-norma-list.css/js; filtros GET, paginação, cards | sim |
| /normas/<pk>/ | views.py:167, norma_detail.html | jurix-legal-detail.css/js; ementa, índice, expandir artigo, timeline, texto integral, coleções | pk=3, detalhe e texto integral sim |
| /normas/<pk>/compare/ | views.py:234, norma_compare.html | jurix-legacy-shell.css; diff, tabela de eventos | pk=3 sim |
| /normas/<pk>/tree/ | views.py:366, norma_tree.html | jurix-legal-tree.js, jurix-legacy-shell.css; nós expansíveis | pk=3 inicial sim |
| /normas/<pk>/export/pdf/ | views.py:332, resposta PDF | download, paginação | não testado |
| /colecoes/ | workspace_views.py:290, workspace/collections.html | workspace.css, jurix-collections.js; vazio, criação modal autenticada | vazio anônimo sim; modal não |
| /colecoes/<pk>/ | workspace_views.py:328, workspace/collection_detail.html | adicionar/remover norma, confirmação | não testado em runtime |
| /historico/ | workspace_views.py:363, workspace/history.html | jurix-history-actions.js e jurix-anonymous-history-page.js; busca, paginação, swipe, confirmação | vazio anônimo sim; pop. não |
| /configuracoes/ | workspace_views.py:152, workspace/settings.html | workspace.js; tema, densidade, provedor, validação, reset | tela, troca de provedor e erro sem chave sim |
| /admin/ | Django Admin em config/urls.py:12 | login/admin gerados pelo Django | apenas redireção 302 |

API em /api/v1/: health/live/, health/, health/ready/ (api_health.py); search/semantic/, search/answer/, search/answer/stream/ (api_search.py); normas/, normas/<pk>/ (api_normas.py); normas/<pk>/timeline/, normas/<pk>/conflicts/ (temporal_api.py); suggestions/ e chat/attachments/ e chat/attachments/<attachment_id>/ (api_attachments.py); chat/sessions/, chat/sessions/<session_id>/, chat/sessions/slug/<slug>/ e chat/sessions/<session_id>/regenerate/ (api_chat.py). Os GETs de saúde, lista/detalhe/timeline/conflitos normativos responderam; demais operações de API não foram testadas contra dados reais.

### Fluxos de backend lidos, mas não executados em dados reais

- **Ingestão e atualização:** `src/apps/ingestion/tasks.py:1-62` é fachada de compatibilidade; implementação está separada em `core_tasks.py`, `download_tasks.py`, `ocr_tasks.py`, `segmentation_tasks.py`, `ner_tasks.py` e `consolidation_tasks.py`. `config/settings.py:230-242` agenda limpeza de anexos e sincronização incremental SAPL a cada 900 s, com página padrão de 100 registros. **100 é tamanho de página, não limite total**: `sapl_sync.py:195-329` persiste cursor, avança páginas e para por página inalterada/fim; `:335-446` implementa varredura integral separada. Não executar sync nesta auditoria, porque grava corpus. Os testes `test_sapl_incremental.py`, `test_sapl_sync_state.py`, `test_sapl_pagination_diagnostics.py` passaram na suíte, mas não provam completude do servidor externo.
- **Consolidação jurídica:** `src/processing/target_resolver.py:220-278` resolve hierarquia/alvos de eventos; `src/apps/ingestion/consolidation_tasks.py:35` agenda consolidação; `src/apps/legislation/views.py:167-366` apresenta texto, comparação e árvore. Faltou verificar em runtime com uma norma extensa e eventos contraditórios; não há achado de erro de resolução sem caso reprodutível.
- **Recuperação e geração:** `src/processing/adaptive_retrieval.py:1-80` declara política híbrida/temporal; `rag_service.py:92-267` trata vetores/fallback e `:625-760` trata estados e grounding; `api_search.py:328-493` converte em SSE. `config/settings.py:274-318` configura Ollama e obriga grounding estrito fora de DEBUG. Não foi enviada pergunta real à LLM, portanto latência, cadência de streaming e qualidade factual permanecem não testadas em runtime.
- **Persistência e segurança:** `src/apps/legislation/models.py:552-671` define sessão/mensagem; `api_chat.py:75-123` aplica ownership; `api_limits.py:205-247` implementa rate limit. Uploads, exclusões e regeneração têm cobertura de testes, mas não foram acionados no QA para evitar mutação de dados. Não usar `manage.py check --deploy` de um ambiente DEBUG como proxy para implantação; validar com configuração segura e segredos injetados em ambiente isolado.

## Achados verificados

### IA e confiança jurídica

ID: **A-IA-001**  
Título: fontes e selo de correspondência podem acompanhar resposta rejeitada pelo grounding.  
Severidade: Alto.  
Evidência: src/processing/rag_service.py:636-640 envia fontes antes da validação; :719-760 emite fallback e done com as mesmas fontes quando grounded=false; src/apps/legislation/api_search.py:438-443 e :483-491 não repassam grounded no done e persistem sources_json; src/apps/core/static/js/chat.js:1610-1625 exibe as fontes sempre que a lista é não vazia. A regeneração tem caminho próprio em src/apps/legislation/api_chat.py:187-232 e chat.js:970-1013.  
Verificado em: leitura de código; o caminho rejeitado não foi acionado no banco real.  
Referência: Nielsen, prevenção de erros e status do sistema — https://www.nngroup.com/articles/ten-usability-heuristics/ .  
Impacto: a mensagem “evidência insuficiente” pode surgir junto de “alta correspondência”, criando confiança jurídica indevida.  
Correção proposta: incluir grounded e estado terminal no evento done; só publicar selo/links de fontes de sustentação quando grounded=true; em rejeição, mostrar evidências como “recuperadas, insuficientes”, sem badge de confiança. Cobrir stream e regeneração com evento sintético.  
Esforço: M. Dependências: nenhuma.

ID: **A-IA-002**  
Título: filtros de tipo/ano são aplicados depois do top 50 vetorial.  
Severidade: Alto.  
Evidência: src/apps/legislation/workspace_views.py:200-218 chama semantic_search(k=50) e só depois filtra result.dispositivo.norma.tipo/ano; src/processing/rag_service.py:181-204 aplica LIMIT antes desse filtro.  
Verificado em: leitura de código; não foi criado corpus sintético com mais de 50 candidatos.  
Referência: Nielsen, correspondência entre sistema e mundo real — https://www.nngroup.com/articles/ten-usability-heuristics/ .  
Impacto: consulta “tipo X, ano Y” pode dizer que não há resultados mesmo quando itens pertinentes ocupam posição 51 ou posterior antes do filtro.  
Correção proposta: propagar tipo/ano para a query SQL e para o fallback SQLite antes de LIMIT; testar corpus com 50 itens irrelevantes melhores colocados e um item filtrado na posição 51.  
Esforço: M. Dependências: nenhuma.

ID: **A-IA-003**  
Título: fallback SQLite lexical é apresentado como busca semântica.  
Severidade: Médio.  
Evidência: src/processing/rag_service.py:116-134 usa AdaptiveRetriever._lexical para SQLite; src/apps/legislation/workspace_views.py:194-218 inicia search_mode como semantic; workspace/search.html:22 mostra “Busca semântica” quando esse modo permanece. A captura screenshots/search-results-dark-1280x800.png veio do servidor SQLite.  
Verificado em: runtime e leitura de código.  
Referência: Nielsen, visibilidade do estado — https://www.nngroup.com/articles/ten-usability-heuristics/ .  
Impacto: usuário interpreta a ordenação lexical como similaridade semântica.  
Correção proposta: transportar o modo efetivamente usado à view e à interface, preservando a distinção entre zero resultados e falha de infraestrutura.  
Esforço: P. Dependências: A-IA-002 se ambos alterarem a mesma busca.

### UX, conteúdo e navegação

ID: **A-UX-004**  
Título: resultado por dispositivo abre a norma no topo, perdendo o artigo encontrado.  
Severidade: Médio.  
Evidência: workspace/search.html:33 usa URL da norma sem fragmento; norma_detail.html:96 define id=dispositivo-<pk>.  
Verificado em: leitura de código.  
Referência: Nielsen, reconhecimento em vez de memorização — https://www.nngroup.com/articles/ten-usability-heuristics/ .  
Impacto: exige procurar novamente o dispositivo em normas longas.  
Correção proposta: anexar #dispositivo-<pk> ao link, preservar foco/posição e indicar destaque temporário respeitando movimento reduzido.  
Esforço: P. Dependências: nenhuma.

ID: **A-UX-005**  
Título: prévia do histórico usa a resposta do assistente antes da pergunta.  
Severidade: Médio.  
Evidência: workspace_views.py:396-398 atribui first_answer.content a session.primary_query; workspace/history.html:26 apresenta primary_query abaixo do título.  
Verificado em: leitura de código; histórico autenticado não foi aberto em runtime.  
Referência: HIG, hierarquia e conteúdo principal — https://developer.apple.com/design/human-interface-guidelines/design-principles .  
Impacto: resumo pode ser uma resposta extensa/truncada, pouco útil para localizar conversa.  
Correção proposta: usar a pergunta inicial ou, explicitamente, a mais recente; nomear variável conforme escolha e testar título/pergunta diferentes.  
Esforço: P. Dependências: nenhuma.

ID: **A-UX-006**  
Título: Coleções e composer prometem recursos além do corpus/modelo atual.  
Severidade: Médio.  
Evidência: workspace/collections.html:10 e :30 prometem pesquisas e evidências; models.py:534-540 armazena apenas normas. chatbot.html:285 convida a perguntar sobre jurisprudência, mas a recuperação inspecionada em rag_service.py:92-267 busca Dispositivo de Norma municipal.  
Verificado em: leitura de código e telas públicas screenshots/collections-dark-360x800.png e screenshots/assistant-dark-360x800.png.  
Referência: Nielsen, correspondência entre linguagem e funcionamento — https://www.nngroup.com/articles/ten-usability-heuristics/ .  
Impacto: cria expectativa de coleção de evidências e jurisprudência que a interface não sustenta.  
Correção proposta: ajustar textos ao escopo entregue; só voltar a prometer esses recursos após implementação verificável.  
Esforço: P. Dependências: nenhuma.

ID: **A-UX-007**  
Título: controles de escopo/modo no assistente truncam rótulos em 360 px.  
Severidade: Médio.  
Evidência: screenshots/assistant-dark-360x800.png; chatbot.html:208-225; jurix-figma.css:1782-1795 força elipse nas duas colunas.  
Verificado em: runtime.  
Referência: HIG, hierarquia/layout adaptável — https://developer.apple.com/design/human-interface-guidelines/layout .  
Impacto: o usuário precisa abrir o menu para descobrir o valor selecionado.  
Correção proposta: mostrar rótulos completos em uma coluna abaixo de 400 px, ou usar texto curto inequívoco com nome acessível completo.  
Esforço: P. Dependências: nenhuma.

### Acessibilidade e legibilidade

ID: **A-A11Y-008**  
Título: o botão “Anexar documento” anuncia menu, mas abre seletor de arquivo.  
Severidade: Médio.  
Evidência: jurix-search-controls.js:144-151 atribui aria-haspopup=menu a todos os controles; :70-80 chama ensureFileInput().click() para attachment; chatbot.html:212-216 contém o controle visual.  
Verificado em: leitura de código.  
Referência: WCAG 4.1.2, nome/papel/valor — https://www.w3.org/TR/WCAG22/#name-role-value .  
Impacto: tecnologia assistiva anuncia interação diferente da real.  
Correção proposta: para attachment usar button sem aria-haspopup/aria-expanded/aria-controls de menu, mantendo Enter/Espaço e rótulo; validar navegação por teclado.  
Esforço: P. Dependências: nenhuma.

ID: **A-A11Y-009**  
Título: erro de configuração remota não é associado aos campos inválidos.  
Severidade: Médio.  
Evidência: workspace.js:137-149 escreve mensagem geral; teste local de formulário vazio após selecionar OpenAI retornou status visível, zero aria-invalid e zero aria-describedby nos campos modelo/chave; foco foi para external_model.  
Verificado em: runtime sem salvar e leitura de código.  
Referência: WCAG 3.3.1 — https://www.w3.org/WAI/WCAG22/Understanding/error-identification.html ; GOV.UK — https://design-system.service.gov.uk/components/error-summary/ .  
Impacto: usuário de leitor de tela não recebe erro contextual ao retornar ao campo; erro de múltiplos campos exige inferência. Não foi declarada violação WCAG conclusiva sem teste assistivo.  
Correção proposta: mensagens por campo com id próprio, aria-invalid e aria-describedby, preservar resumo em role=status e foco no primeiro erro.  
Esforço: P. Dependências: nenhuma.

ID: **A-UI-010**  
Título: metadados e ajuda de formulários estão pequenos para leitura prolongada.  
Severidade: Médio.  
Evidência: workspace.css:52, :59, :61, :70-77 usa 10–12 px em badges, labels e ajuda; screenshot/settings-dark-360x800.png mostra nota do provedor comprimida em várias linhas.  
Verificado em: runtime e leitura de CSS.  
Referência: HIG, tipografia e legibilidade — https://developer.apple.com/design/human-interface-guidelines/accessibility .  
Impacto: aumenta esforço de leitura e reduz hierarquia cognitiva; tamanho pequeno isolado não é, por si, falha WCAG.  
Correção proposta: escala relativa para ajuda em 0,875rem/1,45, metadados mínimos de 0,75rem e teste em zoom 200% antes de aprovar.  
Esforço: P. Dependências: nenhuma.

ID: **A-UI-011**  
Título: fonte remota é incluída no HTML mesmo quando a CSP de produção a bloqueia.  
Severidade: Médio.  
Evidência: workspace/base.html:11-13 e chatbot.html:14-16 sempre importam Google Fonts; config/settings.py:365-366 e config/middleware.py:73-86 permitem esses domínios só quando CSP_ALLOW_GOOGLE_FONTS=true (padrão DEBUG). Não foram encontrados arquivos WOFF/TTF locais em src/.  
Verificado em: leitura de código; produção com CSP estrita não foi iniciada.  
Referência: HIG, consistência visual — https://developer.apple.com/design/human-interface-guidelines/design-principles ; OWASP, configuração segura — https://top10.owasp.org/2021/ .  
Impacto: produção usa fallback tipográfico e pode ter diferenças de layout/console.  
Correção proposta: condicionar o link à política ou empacotar fontes locais licenciadas; validar CSP estrita em navegador antes de escolher.  
Esforço: M. Dependências: nenhuma.

### Performance e dados

ID: **A-PERF-012**  
Título: busca do histórico ignora sessões além das 500 mais recentes.  
Severidade: Médio.  
Evidência: workspace_views.py:378-391 filtra, anota, prefetch e corta em [:500] antes de ranquear/paginar em Python; :371 limita mensagens a 20 por sessão.  
Verificado em: leitura de código; não há conta de teste com mais de 500 sessões.  
Referência: Carbon, padrões para dados densos e busca — https://carbondesignsystem.com/components/data-table/usage/ .  
Impacto: conversas antigas não aparecem nem são alcançáveis por busca/paginação após o limite; custo de prefetch e ranking cresce no servidor.  
Correção proposta: paginar/filtrar no banco, com ranking determinístico e cursor ou busca textual indexada, e testar mais de 500 sessões sintéticas.  
Esforço: G. Dependências: A-UX-005 (prévia).

ID: **A-PERF-013**  
Título: diff de normas grandes não tem limite de processamento.  
Severidade: Médio.  
Evidência: views.py:247-255 divide textos completos e usa SequenceMatcher(autojunk=False) antes de renderizar todas as diff_rows; não há corte de linhas ou execução assíncrona nesse caminho.  
Verificado em: leitura de código; tempo com norma longa não foi medido.  
Referência: Core Web Vitals, tempo de resposta/interatividade — https://web.dev/articles/vitals .  
Impacto: possibilidade de CPU e HTML excessivos em textos repetitivos ou longos; magnitude depende do corpus.  
Correção proposta: medir caso sintético longo, estabelecer limite explícito de linhas/tempo e paginação ou diff assíncrono com mensagem clara.  
Esforço: M. Dependências: nenhuma.

ID: **A-COD-014**  
Título: ordenação por “recentes” usa número da lei como string.  
Severidade: Médio.  
Evidência: models.py:30 define numero como CharField; views.py:89-94 ordena por -ano,-numero; api_normas.py:119 aplica a mesma ordem.  
Verificado em: leitura de código; as dez normas locais observadas têm números da mesma faixa e não exercitam o caso.  
Referência: Nielsen, consistência e prevenção de erro — https://www.nngroup.com/articles/ten-usability-heuristics/ .  
Impacto: números de larguras distintas podem ficar em ordem lexical (9 antes de 10 em ordem decrescente).  
Correção proposta: definir critério jurídico de recência (data de publicação com fallback estável, ou número normalizado com campo derivado) e aplicar na web e API, com teste 9/10 no mesmo ano.  
Esforço: M. Dependências: nenhuma.

### Segurança e engenharia

ID: **A-COD-015**  
Título: GET do assistente altera estado persistente.  
Severidade: Alto.  
Evidência: views.py:427-440 atualiza is_active e salva ChatSession autenticada; :453-461 grava temp_chat_session_id em request.session no GET anônimo. A captura do assistente confirmou a necessidade de tratar esse GET como ação com efeito colateral.  
Verificado em: leitura de código e runtime anônimo.  
Referência: RFC 9110, métodos seguros — https://www.rfc-editor.org/rfc/rfc9110.html#section-9.2.1 .  
Impacto: F5/abertura de URL muda estado no servidor e crawlers/previews podem criar sessões; também inviabiliza uma auditoria puramente GET sem side effects.  
Correção proposta: apenas ler na view GET; ativação/criação de sessão em POST protegido ou no primeiro envio, mantendo sessão anônima no cliente.  
Esforço: M. Dependências: nenhuma.

ID: **A-SEC-016**  
Título: endpoint compatível controlado pelo cliente pode alcançar serviços locais do host.  
Severidade: Médio, condicionado ao modo de implantação.  
Evidência: llm_provider.py:33-46 aceita localhost/127.0.0.1/host.docker.internal e porta/caminho enviados pelo cliente; :52-59 faz POST do servidor para essa URL acrescida de /chat/completions. api_search.py:328-356 expõe o streaming a usuários anônimos com limite de taxa. Redirecionamentos estão desabilitados, uma mitigação já presente.  
Verificado em: leitura de código; nenhum endpoint interno foi sondado. Não há demonstração de exploração.  
Referência: OWASP SSRF — https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html .  
Impacto: em implantação com serviços HTTP internos compatíveis acessíveis pelo web worker, um cliente pode fazê-lo contatar serviço não escolhido pelo operador.  
Correção proposta: em produção aceitar somente endpoints exatos cadastrados pelo operador, validar esquema/host/porta/caminho após normalização e testar negações; preservar modo local explícito para desenvolvimento.  
Esforço: M. Dependências: nenhuma.

ID: **A-COD-017**  
Título: o gate Ruff já falha em dois imports.  
Severidade: Baixo.  
Evidência: execução ruff check .: I001 em src/apps/legislation/serializers.py:10 e src/tests/test_source_urls.py:1; pyproject.toml:21-33 habilita I.  
Verificado em: comando executado.  
Referência: Ruff I001 — https://docs.astral.sh/ruff/rules/unsorted-imports/ .  
Impacto: CI/lint não fica verde mesmo com suítes funcionais aprovadas.  
Correção proposta: ordenar somente os imports desses dois arquivos e repetir ruff check .  
Esforço: P. Dependências: nenhuma.

## Hipóteses a validar

1. **Cobertura do corpus:** dez normas consolidadas foram vistas no QA (screenshots/norms-dark-360x800.png); config/settings.py:349 define meta operacional de 300, mas não há aqui prova do total oficial nem de que a instância observada seja produção. Validar plano de ingestão e sinal de completude antes de afirmar “acervo completo”.
2. **Anexos no composer estreito:** jurix-search-controls.css:47-55 limita previews a 42 px, permite wrap e esconde excedente. É provável que a segunda linha fique inacessível; a tentativa sintética no estado inicial retornou altura zero porque o composer ativo estava oculto. Reproduzir em fixture com composer ativo; não registrar como falha runtime confirmada.
3. **CWV e dependências:** não houve coleta p75 de LCP/INP/CLS nem auditoria automatizada de CVEs. Os tempos DOMContentLoaded e transferBytes em runtime-manifest.json são medições locais com cache compartilhado, não substituem CWV. Confirmar em ambiente representativo com Lighthouse/RUM e ferramentas de vulnerabilidades, sem instalar dependências durante esta auditoria.
4. **Acessibilidade completa:** testes de foco/reduced-motion passaram em suite sintética, porém não houve zoom 200%, leitor de tela ou contraste de todos os pares dinâmicos. O índice da norma tem 24 links com altura de 15 px a 360 px; distância mínima medida entre centros foi 25,02 px, portanto não declarar violação WCAG 2.5.8 sem avaliar exceções de espaçamento. Recomenda-se alvo maior por ergonomia HIG.

## Matriz de conformidade por amostra

Legenda: OK observado = evidência restrita ao estado testado; Parcial = limitação ou achado; Pendente = não testado. Uma linha OK não significa conformidade global.

| Critério | Tela/fluxo | Status e evidência |
| --- | --- | --- |
| HIG hierarquia e navegação | Assistente, Normas, Pesquisa, Configurações | Parcial: shell coerente nas capturas; rótulos truncados em screenshots/assistant-dark-360x800.png |
| HIG alvos de toque | Detalhe da norma | Parcial: índice com 15 px de altura; WCAG 2.5.8 não declarado falho pela exceção medida |
| HIG cor, movimento | telas principais | OK observado: dois temas em 80 capturas; reduced-motion testado em tests/js/real.browser.test.mjs; zoom pendente |
| M3 tokens e estados | shell e componentes | Parcial: tokens existem em CSS; especificação M3 integral não verificada nesta ferramenta |
| WCAG 1.4.3 e 1.4.11 contraste | botões/texto nos temas | Parcial: testes estáticos de contraste passaram; não há medição de todos os componentes dinâmicos |
| WCAG 1.4.10 reflow | dez rotas | OK observado em 360/768/1280/1920 px sem overflow global; 320 px e 200% zoom pendentes |
| WCAG 2.1.1/2.4.7 teclado/foco | paleta, detalhe, drawer sintético | Parcial: Ctrl+K e expansão funcionaram; foco do drawer coberto em tests/js/real.browser.test.mjs; leitor de tela pendente |
| WCAG 3.3.1 identificação do erro | Configurações | Parcial: mensagem geral aparece, associação por campo ausente (A-A11Y-009) |
| WCAG 4.1.2 nome/papel/valor | Anexo | Parcial: aria-haspopup não corresponde ao seletor de arquivo (A-A11Y-008) |
| OWASP entrada/autorização | Markdown, sessões, anexos | Parcial: DOMPurify e CSRF/rate limit no código; testes XSS passam; endpoint local configurável pede revisão (A-SEC-016) |
| CWV LCP/INP/CLS | todas | Pendente: sem medição representativa |

## Validação de controles existentes

O frontend sanitiza Markdown com DOMPurify em jurix-markdown.js:85-88; o middleware declara CSP em config/middleware.py:73-112; sessões do chat são consultadas com user=request.user em api_chat.py:75-123; limitações de taxa usam Redis com falha fechada em api_limits.py:205-247; uploads verificam assinatura e tamanho em attachment_service.py:120-162. Esses controles reduzem risco, mas a auditoria não equivale a pentest. As bibliotecas e regras do sistema podem mudar; validar sua versão no próximo gate de release.
