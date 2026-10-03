# Auditoria completa do Jurix — 02/10/2026

Esta é a reavaliação do **workspace real, incluindo alterações não commitadas**. Não é a repetição da auditoria anterior nem uma avaliação do remoto. Documento proposto porque os quatro nomes originais já existiam; eles permanecem intactos. Apenas auditoria/planejamento: nenhuma correção da aplicação foi implementada.

## Resumo executivo

Há uma base técnica útil e uma UI sensivelmente mais consistente do que as imagens antigas: shell compartilhado, menu de conversas com fixação, fontes agrupadas, confirmação de exclusão, tema claro e citações copiáveis. Porém, **não recomendo classificar o estado atual como production-grade**. Exportação PDF perde conteúdo, busca exata falha em duas telas e perguntas jurídicas válidas podem terminar em recusa por defeitos de validação.

Avaliação editorial, não certificação ou resultado de benchmark: **7/10 como protótipo de pesquisa; 5,5/10 como produto jurídico; 6/10 em UI/UX**. A nota de pesquisa considera instrumentação, contratos e suíte existente; a de produto penaliza integridade do documento e falhas nos fluxos principais. Os PDFs de escopo citados em turnos anteriores não foram relidos nesta auditoria: não afirmar aderência formal ao PIBIC somente com estas notas.

Prioridade: PDF → ações da norma → busca exata → claims/cobertura → densidade e fontes móveis → dependências → orquestração/performance. Não aumentar confiança nem esconder recusas para parecer mais moderno.

## Estado local preservado

- Branch auditada: **main**, HEAD **3d6d428e5a92f9c516418018e21fe6bf11a90d41**. Não foi trocada para ui/pro-polish e não foi consultado o remoto como fonte de código.
- Staged: vazio. Commits locais à frente do upstream configurado: nenhum, conforme refs locais, sem fetch.
- Unstaged preexistente: **39 arquivos, 1.294 inserções / 205 exclusões**. Inclui RAG, streaming, sidebar, serializers, testes e config/settings.py. O diff relevante está resumido integralmente em [git-baseline.json](C:/Jurix/docs/audit/2026-10-02/git-baseline.json), com lista de caminhos e hashes.
- Não rastreados preexistentes: GOAL.md; docs/audit/2026-10-01/; os quatro relatórios originais; capture_runtime.mjs; runtime-manifest.json; screenshots anteriores; migration0021; normative_query.py; testes correspondentes. Lista completa no baseline.
- Auditoria inclui esses arquivos; **não tratá-los como descartáveis nem fazer git add .**.
- Integridade final: comparar [git-final.json](C:/Jurix/docs/audit/2026-10-02/git-final.json). A auditoria não autoriza commit, push, merge, pull, stash, reset, clean ou switch.

## Capacidades e isolamento

Terminal PowerShell, Python/Node, Docker CLI, rede, navegador real IAB, árvore acessível, screenshot e controle de viewport disponíveis. Nenhum AGENTS.md encontrado em C:/ ou C:/Jurix. Usados computer-use para navegador e pdf para exportação. Canvas não foi usado: a entrega pedida é um pacote Markdown específico.

Web auditada em **http://127.0.0.1:8006**, com código/settings locais e backup SQLite temporário; localStorage é separado de8005. O servidor isolado não executa migrations nem muda o banco real. [audit_server.py](C:/Jurix/docs/audit/2026-10-02/audit_server.py) documenta as únicas diferenças: caminho do banco, logging e middleware de telemetria. O banco temporário é artefato descartável do sistema, não novo ambiente de produção. Consultas de QA não contêm dados de pessoas/usuários.

Configuração efetiva: Python3.12.10, Django5.2.17, SQLite, LocMemCache, DEBUG=True, Ollama llama3/nomic-embed-text. Corpus10 normas consolidadas,189 dispositivos;7 datas de vigência não registradas. Ver [environment.json](C:/Jurix/docs/audit/2026-10-02/environment.json).

Docker aberto **não significa dependências saudáveis**: Postgres/Redis parados; worker unhealthy e ping falha por DNS redis:6379. Web Docker8000 healthy no liveness. Não iniciei Redis/Celery para não consumir fila ou alterar corpus real. Readiness local503, liveness200. Ingestão Celery, pgvector/PostgreSQL e failover distribuído: **não testados em runtime**; teste unitário não substitui integração.

Limitações: sem conta QA autenticada; sem execução de CRUD administrativo, provedor remoto pago, carga concorrente ou teclados/leitores físicos. Zoom200% não verificado: atalhos no IAB não alteraram DPR/largura CSS. prefers-reduced-motion verificado por código/testes, não emulação real do sistema. Core Web Vitals não medidos: API performance indisponível no escopo de inspeção; tempos abaixo são laboratório local, não LCP/INP/CLS de campo.

## Inventário de telas e componentes

Hipótese de centralidade: usuário consulta uma lei/artigo, lê e verifica fonte, faz follow-up; alternativamente busca norma, lê consolidado e compara. Configurações/histórico são suporte frequente; Coleções depende de conta; administração/ingestão é operação, não navegação pública principal.

Arquivos de views abaixo pertencem a C:/Jurix/src/apps/legislation/. Templates pertencem a C:/Jurix/src/apps/legislation/templates/legislation/. CSS/JS citados pertencem a C:/Jurix/src/apps/core/static/css/ e /js/, com extensão .css/.js. “Base” inclui workspace/base.html, _sidebar.html, _topbar.html, jurix-figma.css, workspace.css, jurix-components.css, jurix-sidebar.css, theme.js, config.js, workspace.js, command_palette.js, jurix-anonymous-history.js, jurix-chat-api.js e jurix-sidebar.js.

| Rota | View | Template | CSS | JS | Visto em runtime |
|---|---|---|---|---|---|
| /assistente/ e /assistente/<slug>/ | workspace_views.assistente_view → views.chatbot_view | chatbot.html | jurix-figma, workspace, jurix-rag, jurix-markdown, jurix-chat*, jurix-sidebar, jurix-search-controls | chat, jurix-chat-api/renderer/state/controller, jurix-markdown/rag/sidebar/anonymous-history/search-controls, command_palette | Sim: perguntas, espera, sucesso, recusa, F5, copiar, fontes, submenu e mobile |
| /normas/ | views.NormaListView | norma_list.html | jurix-norma-list + base | jurix-norma-list + base | Sim: busca formatada falhou, cards, filtros visíveis, 5 larguras |
| /normas/<pk>/ | views.NormaDetailView | norma_detail.html | jurix-legal-detail, jurix-legacy-shell + base | jurix-legal-detail + base | Sim: ementa, índice/hash, ações móvel/desktop, texto, timeline |
| /normas/<pk>/compare/ | views.norma_compare_view | norma_compare.html | jurix-legacy-shell, jurix-legal-detail + base | base | Sim: comparação OCR/consolidado; 5 larguras |
| /normas/<pk>/tree/ | views.norma_dispositivos_tree_view | norma_tree.html | jurix-legacy-shell + base | jurix-legal-tree + base | Sim: recolher/expandir artigo, 5 larguras |
| /normas/<pk>/export/pdf/ | views.norma_pdf_export_view | Nenhum; fitz gera PDF | Não se aplica | Não se aplica | Sim: download, renderização das 2 páginas, extração textual |
| /pesquisa/ | workspace_views.legal_search_view | workspace/search.html | workspace + base | base | Sim: consulta exata, resultados/empty state, 5 larguras |
| /configuracoes/ | workspace_views.settings_view | workspace/settings.html | workspace + base | workspace + base | Sim: provedor compatível incompleto, erro/foco; tema claro/sistema e salvar |
| /historico/ | workspace_views.history_view | workspace/history.html | workspace + base | jurix-anonymous-history-page, jurix-history-actions + base | Sim: QA local, busca, pin, cancelar exclusão, 5 larguras; autenticado não |
| /colecoes/ | workspace_views.collections_view | workspace/collections.html | workspace + base | jurix-collections quando autenticado + base | Sim: visitante indisponível; 5 larguras; CRUD autenticado não |
| /colecoes/<pk>/ | workspace_views.collection_detail_view | workspace/collection_detail.html | workspace + base | jurix-collections + base | HTTP redireciona visitante; conteúdo autenticado não testado |
| /normas/chatbot/ e /normas/chatbot/<slug>/ | views.chatbot_view | chatbot.html | Mesmo assistente | Mesmo assistente | Alias sem slug: HTTP200; variante slug não visitada |
| /admin/login/ e demais /admin/ | Django AdminSite e ModelAdmin | Django admin/login.html e templates registrados | Assets Django Admin | Assets Django Admin | Login HTTP200; autenticação/CRUD não testados |

### Estados, formulários, modais e fluxos

- Assistente: novo/resumido; sugestões; textarea; Enter/Shift+Enter; seletores modo/escopo; anexos; processamento; resposta validada; insuficiência; cancelamento/retry; copy; drawer de fontes; expansão por norma/dispositivo. Envio, resposta, recusa, follow-up, F5, copy e drawer executados; cancelamento upstream/anexo real/queda de serviço não executados. Seletores têm implementação e payload em jurix-search-controls.js e chat.js:1559; não são meramente decorativos.
- Sidebar: expandir/recolher, mobile overlay, recents, menu rename/pin/delete, pesquisa de conversa; pin e menu/confirmar-cancelar executados. Não houve exclusão definitiva. Rename dialog possui implementação; envio da renomeação não executado.
- Pesquisa/normas: busca, filtros tipo/ano/ordem/status, resultados e vazio. Consulta formatada e falha executadas; combinações completas de todos os filtros/paginação não exercitadas. Ordenação por publicação já existe, não é pendência.
- Norma: ementa, informações técnicas, Mais ações, índice/hash, expansão de texto, datas/timeline, consolidado, árvore, comparação, PDF, perguntar com norma_id. Expansão/actions/hash/tree/PDF executados; consolidação/revisão administrativa de eventos não.
- Configurações: provedor/modelo/temperatura/fontes, compatível/endpoint/chave, tema/densidade, persistência, exportar/apagar histórico. Salvar aparência e erro de provedor incompleto executados; nenhuma chave real ou endpoint remoto foi cadastrado; exportar/apagar JSON não executados.
- Coleções: indisponível ao visitante, criação com dialog, add/remove norma e coleção de terceiro. Visitante executado; CRUD/ownership em runtime não; testes existentes executados.
- Admin: login, tabelas, filtros, forms de modelos e actions. Apenas GET login; não cadastrar usuário/ingestão durante auditoria.
- APIs: catálogo completo abaixo; [public-http.json](C:/Jurix/docs/audit/2026-10-02/public-http.json) registra GET públicos e negativas401. SSE foi POST real com CSRF e Ollama; REST answer síncrona/regenerate autenticado não exercitados.

## O que foi efetivamente verificado

[verification-results.json](C:/Jurix/docs/audit/2026-10-02/verification-results.json) registra comandos e resultados:

- pytest completo: **805passed,6skipped,7warnings,75,10s**, cobertura71,69%. Ruff: passou. manage.py check: passou. pip check: passou. git diff --check: passou.
- npm test: exit0, incluindo30testes de navegador com fixtures. Não confundir fixtures com testes contra Ollama vivo.
- Gate de documentação passou. Gate de arquitetura **passed:false**,867/850linhas em rag_service.py.
- manage.py check --deploy:3erros e7warnings de configuração **local de desenvolvimento**; não é evidência de ambiente externo inseguro. Checklist real de release precisa rodar com settings de staging autorizados, sem substituir .env local.
- npm audit --omit=dev:0; npm audit completo:7pacotes high, dev-only. Consulta PyPI por versão: advisories Requests/Pillow; não é auditoria de toda árvore Python.
- Nove telas ×360,768,1280,1920 e320 =45combinações; nenhum overflow horizontal de página. Há clipping interno de pill no chat. Screenshots de360,1920,320 mais interações desktop e tema claro.
- Requests de laboratório: norma detail9queries e39–67ms de cabeçalho; árvore3queries e28–52ms; comparação4queries e14–16ms. **Não foi demonstrado N+1** nesse corpus; não extrapolar para carga. Telemetria mede despacho/resposta não-streaming, não toda geração SSE.
- Assets locais brutos: assistente464.128bytes, configurações174.093, normas206.111. Sem gzip/fontes remotas, logo não usar como tamanho de transferência.
- Ollama real, casos overview/artigo1/lei ausente/artigo7/follow-up. Tempos dos probes são de uma amostra sequencial local, hardware/carga não controlados.

### Cadeia de geração, evidências, citações e cópia

1. normative_query.py classifica consulta; adaptive_rag_service.py amplia overview para48fontes e contexto até24.000caracteres configurados. **Top-k5 não limitou o caso pequeno:**24dispositivos recuperados. Em normas grandes há amostragem declarada; não alegar cobertura de todo acervo.
2. rag_context_builder.py monta [[n]] com dispositivo/intervalo. Corte de conteúdo não entra corretamente em coverage.complete, conforme probe sintético.
3. rag_service.py acumula tokens, valida e tenta novamente até2vezes. Texto não validado não é exposto atualmente; decisão de segurança apropriada, mas a espera precisa de feedback.
4. sources SSE chega antes do texto; chat.js:1608 registra metadados/citações, mas o controle público aparece no done após grounded=true. **Isso segue a preferência mais recente de não exibir rascunho/fontes prematuramente**. O pedido anterior de fontes durante geração conflita com essa preferência; não restaurar a política antiga sem nova decisão.
5. done só faz flush quando texto diverge; não houve necessidade de F5 para fontes válidas no teste atual.
6. IDs estruturados e [[n]] são resolvidos por jurix-markdown.js/jurix-rag.js. LLM não precisa construir URLs. Copiar resposta do artigo1 preservou duas referências como Markdown com URLs oficiais. Link de lei inteira e link de dispositivo devem manter semânticas distintas, conforme testes existentes.
7. Artigo7 contextual foi resolvido para8206; falhou por uma linha referencial tratada como claim. Não consertar memória que funcionou.
8. Recusa por ausência de condição jurídica continua necessária. Melhor comunicação não pode transformar omissão factual em resposta “confiável”.

## Achados comprovados

Formato de IDs: AREA-A-###. Severidade produto, não CVSS. P=pequeno, M=médio, G=grande. “Runtime sintético” é probe controlado sem produção. Uma referência é princípio de avaliação, não afirmação de certificação.

### UX-A-001 — Busca de normas não aceita a referência jurídica formatada

ID: UX-A-001  
Título: Busca de normas não aceita a referência jurídica formatada  
Severidade: Alto  
Evidência: src/apps/legislation/views.py:75,96; src/apps/core/static/js/jurix-norma-list.js (splitNormaIdentifier); screenshot audit-20261002-norm-search-formatted-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — correspondência com linguagem do usuário](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: “Lei nº 8.206/2026” retorna zero resultados, embora /normas/3/ exista.  
Correção proposta: Normalizar tipo, número pontuado e ano no servidor com parse_normative_references; aplicar filtros explícitos; manter busca textual quando não houver referência inequívoca.  
Esforço: P  
Dependências: Nenhuma

### UX-A-002 — Pesquisa jurídica ranqueia outras leis acima da lei pedida

ID: UX-A-002  
Título: Pesquisa jurídica ranqueia outras leis acima da lei pedida  
Severidade: Alto  
Evidência: src/apps/legislation/workspace_views.py:217; screenshot audit-20261002-legal-search-exact-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — prevenção de erros](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: A consulta exata formatada retornou dez normas; a pedida ficou depois de cláusulas genéricas de outras normas.  
Correção proposta: Resolver a referência antes de RAGService.semantic_search; consultar a norma exata e seus dispositivos; não substituir uma lei ausente por uma lei semelhante.  
Esforço: M  
Dependências: UX-A-001

### UX-A-003 — Ações secundárias da norma desaparecem no desktop

ID: UX-A-003  
Título: Ações secundárias da norma desaparecem no desktop  
Severidade: Alto  
Evidência: src/apps/core/static/css/jurix-legal-detail.css:37; src/apps/legislation/templates/legislation/norma_detail.html:62; screenshot audit-20261002-normas-3-1920.jpg  
Verificado em: runtime + leitura de código  
Referência: [WCAG 2.1.1 — operação por teclado](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)  
Impacto: details começa fechado e seu summary é display:none no desktop. Comparar, exportar e abrir SAPL ficam fora da árvore acessível; no móvel o summary reaparece.  
Correção proposta: Manter summary visível e operável em todos os breakpoints; não usar CSS para esconder o único controle que abre details.  
Esforço: P  
Dependências: Nenhuma

### UX-A-004 — Comparação dá falsa indicação de incisos removidos

ID: UX-A-004  
Título: Comparação dá falsa indicação de incisos removidos  
Severidade: Alto  
Evidência: src/processing/legal_diff.py:11,50; src/apps/legislation/views.py:235; screenshot audit-20261002-comparison-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Carbon — apresentação consistente de dados](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines)  
Impacto: “I – texto” do OCR é uma unidade, mas “Inciso I texto” do consolidado não passa na regex. O inciso aparece como exclusivo do OCR embora o conteúdo esteja presente.  
Correção proposta: Reconhecer ambos os marcadores, com validação romana e limite de palavra, preservando artigo/parágrafo pai; comparar unidades equivalentes sem remover negações ou números.  
Esforço: P  
Dependências: Nenhuma

### UX-A-005 — Colofões continuam dentro dos dispositivos de sete normas

ID: UX-A-005  
Título: Colofões continuam dentro dos dispositivos de sete normas  
Severidade: Alto  
Evidência: src/processing/legal_parser.py:75; src/apps/ingestion/management/commands/repair_legal_colophons.py:37; 2026-10-02/colophon-residuals.json  
Verificado em: runtime de leitura + leitura de código  
Referência: [Nielsen — integridade da informação](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: IDs de normas 4,6,7,9,10,11,12 contêm sessão, autoria/publicação no artigo final. Poluem exibição e recuperação. É dado legado remanescente, não prova de que o parser novo esteja errado.  
Correção proposta: Usar o comando de reparação existente inicialmente em dry-run; revisar conflitos de datas e manifesto; aplicar somente em cópia de QA. Aplicação no acervo real exige autorização separada e backup.  
Esforço: M  
Dependências: SEC-A-001

### UX-A-006 — Título genérico dificulta reconhecer a conversa

ID: UX-A-006  
Título: Título genérico dificulta reconhecer a conversa  
Severidade: Médio  
Evidência: src/processing/conversation_titles.py:9,93; screenshot audit-20261002-history-menu-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — reconhecimento](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: A conversa sobre 8.206/2026 ganhou “Pesquisa jurídica”. A regex de títulos não aceita ponto no número; uma resposta recusada não oferece evidências para selecionar tema.  
Correção proposta: Reutilizar o parser normativo e produzir fallback descritivo por número/artigo mesmo quando a resposta é recusada. Não introduzir geração LLM bloqueante nem sobrescrever título renomeado.  
Esforço: P  
Dependências: UX-A-001

### UX-A-007 — Vigência apresentada com mais certeza que a cobertura permite

ID: UX-A-007  
Título: Vigência apresentada com mais certeza que a cobertura permite  
Severidade: Alto  
Evidência: src/apps/legislation/templates/legislation/norma_detail.html:145; src/processing/answer_contract.py:91; screenshot audit-20261002-norma-detail-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — correspondência e confiança](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: A tabela diz “Vigente”, mas a timeline diz “Vigência registrada”. Dez normas no corpus não comprovam inexistência de revogação posterior.  
Correção proposta: Derivar a tabela da mesma situação temporal da timeline e usar “Início de vigência registrado”; só declarar vigência atual quando houver cobertura/validação apropriada.  
Esforço: P  
Dependências: Nenhuma

### UX-A-008 — PDF exportado perde o texto jurídico

ID: UX-A-008  
Título: PDF exportado perde o texto jurídico  
Severidade: Crítico  
Evidência: src/apps/legislation/views.py:312–329; src/tests/test_workspace_routes.py:313; 2026-10-02/export-8206.pdf, export-8206-page1.png, export-8206-page2.png; pdftotext executado  
Verificado em: runtime + leitura de código  
Referência: [PyMuPDF — contrato de insert_textbox](https://pymupdf.readthedocs.io/en/latest/page.html#Page.insert_textbox)  
Impacto: O PDF real tem duas páginas; a primeira não contém nenhum artigo e a segunda contém apenas o fim dos metadados. O retorno de insert_textbox é ignorado e a paginação usa 52 linhas com wrapping por caracteres, não medidas da fonte.  
Correção proposta: Paginar por largura e altura reais da fonte; só avançar o cursor após inserção bem-sucedida; rejeitar overflow silencioso. Testar texto extraído de todas as páginas e renderizar arquivos curtos/longos.  
Esforço: M  
Dependências: Nenhuma; revalidar PDF no ambiente QA atualizado em SEC-A-001.

### UI-A-001 — Controle de fontes cortado no celular

ID: UI-A-001  
Título: Controle de fontes cortado no celular  
Severidade: Alto  
Evidência: src/apps/core/static/css/jurix-rag.css:519; src/apps/core/static/css/jurix-figma.css:788; src/apps/core/static/js/chat.js:1000; screenshot audit-20261002-assistente-360.jpg  
Verificado em: runtime + leitura de código  
Referência: [WCAG 1.4.10 — reflow](https://www.w3.org/WAI/WCAG22/Understanding/reflow.html)  
Impacto: A pill mede 418,45px dentro de uma coluna de 260px a 360px. A página não tem scroll horizontal, mas isso ocorre porque o conteúdo é recortado; não significa reflow íntegro.  
Correção proposta: Definir max-inline-size:100%, min-width:0 e layout quebrável; no móvel manter contagem + Ver fontes e mover informação secundária para o drawer, sem esconder a ação.  
Esforço: P  
Dependências: Nenhuma

### UI-A-002 — Composer móvel ocupa espaço excessivo

ID: UI-A-002  
Título: Composer móvel ocupa espaço excessivo  
Severidade: Médio  
Evidência: src/apps/legislation/templates/legislation/chatbot.html; src/apps/core/static/css/jurix-search-controls.css; screenshot audit-20261002-assistente-360.jpg  
Verificado em: runtime  
Referência: [Apple — conteúdo e organização](https://developer.apple.com/design/tips/)  
Impacto: O formulário mede aproximadamente 292px em viewport de 900px: três seletores empilhados deslocam a leitura. É fricção de densidade, não falha de rolagem geral.  
Correção proposta: No móvel mover opções para um menu “Opções de pesquisa” de 44px; manter pergunta/envio e uma linha de auxiliares. Meta de altura ociosa ≤180px a 360×900, sem esconder cancelar.  
Esforço: M  
Dependências: UI-A-001

### UI-A-003 — Cabeçalho de Normas atrasa o acesso aos resultados

ID: UI-A-003  
Título: Cabeçalho de Normas atrasa o acesso aos resultados  
Severidade: Médio  
Evidência: src/apps/core/static/css/jurix-norma-list.css:68,104,126; src/apps/legislation/templates/legislation/norma_list.html; screenshot audit-20261002-normas-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Apple — alinhamento e conteúdo principal](https://developer.apple.com/design/tips/)  
Impacto: Hero grande, explicação sobre a própria interface e contadores redundantes consomem a primeira dobra; o usuário precisa rolar antes de consultar o acervo.  
Correção proposta: Trocar por cabeçalho compacto, uma linha de corpus/atualização, formulário e resultados. Não alterar a ordenação por publicação já existente.  
Esforço: P  
Dependências: Nenhuma

### UI-A-004 — Índice normativo tem alvos pequenos para toque

ID: UI-A-004  
Título: Índice normativo tem alvos pequenos para toque  
Severidade: Médio  
Evidência: src/apps/core/static/css/jurix-legal-detail.css:64; 2026-10-02/browser-metrics.json  
Verificado em: runtime  
Referência: [Apple — alvos de toque recomendados](https://developer.apple.com/design/tips/)  
Impacto: Links do índice têm 16px de altura. A medição entre centros não encontrou colisões de círculos de 24px: NÃO é automaticamente reprovação WCAG 2.5.8, mas fica abaixo da meta ergonômica de 44px.  
Correção proposta: Usar índice de artigos com disclosure de filhos e área clicável ≥44px em dispositivos de toque; evitar transformar 24 links minúsculos em 24 chips enormes.  
Esforço: M  
Dependências: Nenhuma

### UI-A-005 — Contribuição da fonte é um rótulo genérico

ID: UI-A-005  
Título: Contribuição da fonte é um rótulo genérico  
Severidade: Médio  
Evidência: src/apps/legislation/serializers.py:158; src/apps/core/static/js/jurix-rag.js:255,322; screenshot audit-20261002-source-expanded-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — informação útil para a decisão](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: “Contribuição: Trecho de dispositivo” não informa qual afirmação a evidência sustenta.  
Correção proposta: Associar IDs de fontes aos claims validados. Exibir excerto da afirmação sustentada quando o contrato o oferecer; antes disso usar “Trecho recuperado”, sem fingir explicação.  
Esforço: M  
Dependências: IA-A-001

### A11Y-A-001 — Linha temporária de conversa usa controles aninhados

ID: A11Y-A-001  
Título: Linha temporária de conversa usa controles aninhados  
Severidade: Médio  
Evidência: src/apps/core/static/js/chat.js:553–599; screenshot audit-20261002-assistant-waiting-1280.jpg (estado registrado após espera); inspeção do primeiro envio  
Verificado em: runtime + leitura de código  
Referência: [WCAG — semântica de controles e teclado](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html)  
Impacto: createSessionCardImmediately ainda cria um role=button com botão de exclusão dentro e pode coexistir com “Nenhuma conversa ainda”; depois o renderer canônico corrige o estado.  
Correção proposta: Encaminhar a linha temporária para o renderer da sidebar, com link e botão irmãos; remover empty state antes de inserir a linha e reconciliar pelo ID.  
Esforço: M  
Dependências: Nenhuma

### IA-A-001 — Síntese da lei inteira falha mesmo com ampla recuperação

ID: IA-A-001  
Título: Síntese da lei inteira falha mesmo com ampla recuperação  
Severidade: Alto  
Evidência: src/processing/strict_grounding.py:422; src/processing/grounding_service.py:278; 2026-10-02/rag-runtime.json, caso overview  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — prevenção de erros e feedback](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: Foram recuperados 24 dispositivos/8 artigos de 8.206/2026, mas a saída final recusou a pergunta. Claims que resumem vários incisos não encontram apoio em um item isolado. Também houve omissão da condição “sem ônus”: essa rejeição é correta e deve permanecer.  
Correção proposta: Permitir apoio composto limitado à mesma família de artigo, com identificação de cada evidência e invariantes de número, negação e condição; não baixar limiar global nem aceitar resposta inteira por score médio.  
Esforço: G  
Dependências: IA-A-002, IA-A-004

### IA-A-002 — Referência sem proposição vira claim jurídico rejeitado

ID: IA-A-002  
Título: Referência sem proposição vira claim jurídico rejeitado  
Severidade: Alto  
Evidência: src/processing/grounding_service.py:278–418; 2026-10-02/followup-runtime.json  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — diagnóstico adequado](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: Perguntas explícita e contextual sobre art.7 foram recusadas; o claim rejeitado foi apenas “**Lei nº8206/2026, Art.7º**”. O contexto foi resolvido para a lei correta; não atribuir o problema à memória.  
Correção proposta: Reconhecer linhas compostas somente de referência jurídica como metadado, sem ignorar frases factuais em negrito. Adicionar teste negativo de referência + obrigação falsa.  
Esforço: P  
Dependências: Nenhuma

### IA-A-003 — Lei ausente aciona recuperação de leis diferentes

ID: IA-A-003  
Título: Lei ausente aciona recuperação de leis diferentes  
Severidade: Alto  
Evidência: src/processing/adaptive_rag_service.py:395; src/processing/rag_context_builder.py:99; 2026-10-02/rag-runtime.json, missing_norm  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — prevenção de erros](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: 99999/2026 não foi localizada no corpus QA, mas a consulta recupera cinco fontes de outras leis, recebe rótulo whole_norma e tenta gerar duas vezes antes da recusa. Isso não comprova inexistência da lei fora do acervo.  
Correção proposta: Quando uma referência inequívoca estiver ausente, retornar motivo norm_not_in_corpus e nenhuma evidência municipal substituta; não invocar geração. Oferecer busca oficial/correção da referência sem afirmar inexistência jurídica.  
Esforço: M  
Dependências: UX-A-001

### IA-A-004 — Cobertura completa pode esconder truncamento de um dispositivo

ID: IA-A-004  
Título: Cobertura completa pode esconder truncamento de um dispositivo  
Severidade: Alto  
Evidência: src/processing/rag_context_builder.py:105–139; 2026-10-02/context-boundary.json  
Verificado em: runtime sintético + leitura de código  
Referência: [Nielsen — integridade e transparência](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: Probe controlado: dispositivo com38.000 caracteres; apenas7.778 enviados como evidência; coverage.complete=true e evidence_scope=complete. A validação confere quantidade de itens, não conteúdo completo.  
Correção proposta: Registrar corte por dispositivo e contabilizar bytes/intervalos enviados; coverage.complete só quando todos os dispositivos selecionados forem incluídos integralmente. Não ampliar orçamento para esconder o erro.  
Esforço: P  
Dependências: Nenhuma

### IA-A-005 — Correspondência exata aparece como baixa relevância, 0%

ID: IA-A-005  
Título: Correspondência exata aparece como baixa relevância, 0%  
Severidade: Médio  
Evidência: src/apps/legislation/serializers.py:155–169; src/apps/core/static/js/jurix-rag.js:265; screenshot audit-20261002-source-expanded-1280.jpg  
Verificado em: runtime + leitura de código  
Referência: [Nielsen — correspondência com o modelo mental](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: Art.1 identificado diretamente aparece com “Baixa correspondência”, pontuação0%. Pontuação semântica zero não descreve seleção determinística.  
Correção proposta: Preservar match_kind no serializer e representar explicit_reference como “Dispositivo identificado”; score semântico opcional somente para recuperação por similaridade.  
Esforço: P  
Dependências: Nenhuma

### PERF-A-001 — Streaming visível começa só após toda geração/validação

ID: PERF-A-001  
Título: Streaming visível começa só após toda geração/validação  
Severidade: Médio  
Evidência: src/processing/rag_service.py:735–802; src/apps/core/static/js/chat.js:1608–1658; 2026-10-02/rag-runtime.json  
Verificado em: runtime + leitura de código  
Referência: [Web performance — medir experiência de espera](https://web.dev/articles/vitals)  
Impacto: Overview: primeiro sources604ms, primeiro texto24.824ms, total26.347ms. Duas gerações9.209ms+15.374ms. O modelo fornece tokens antes, mas o backend os acumula para segurança. Não é prova de defeito de GPU.  
Correção proposta: Manter texto não verificado oculto; melhorar estados/tempo de espera e reduzir retries desnecessários pelos achados IA. Não chamar a animação de tokens SSE como streaming do modelo; streaming validado por parágrafo é etapa experimental separada.  
Esforço: M  
Dependências: IA-A-001, IA-A-002, IA-A-003

### PERF-A-002 — Cancelamento local não interrompe prontamente geração bloqueante

ID: PERF-A-002  
Título: Cancelamento local não interrompe prontamente geração bloqueante  
Severidade: Médio  
Evidência: src/apps/core/static/js/jurix-chat-api.js:159; src/apps/core/static/js/jurix-chat-controller.js:22; src/processing/rag_service.py:758  
Verificado em: leitura de código  
Referência: [Nielsen — controle do usuário](https://www.nngroup.com/articles/ten-usability-heuristics/)  
Impacto: AbortController cancela o navegador; não há sinal de cancelamento consultado dentro do consumo do LLM. A mensagem atual admite que o servidor pode continuar. Tempo real até interromper Ollama não foi medido.  
Correção proposta: Planejar cancel token por turno, com propriedade/autorização, checagem entre tokens e fechamento da resposta upstream; nunca matar globalmente Ollama ou cancelar turnos de outros usuários.  
Esforço: G  
Dependências: IA-A-003

### PERF-A-003 — CSS/JS do assistente têm carga e regras sobrepostas

ID: PERF-A-003  
Título: CSS/JS do assistente têm carga e regras sobrepostas  
Severidade: Médio  
Evidência: src/apps/legislation/templates/legislation/chatbot.html:21–33,284–306; 2026-10-02/asset-metrics.json; jurix-rag.css:519 e jurix-figma.css:788  
Verificado em: runtime de assets + leitura de código  
Referência: [Material — papéis e tokens; web performance](https://developer.android.com/codelabs/m3-design-theming)  
Impacto: Assets locais somam464.128bytes brutos no chat, contra174.093 em Configurações; não são bytes transferidos comprimidos. Pill/drawer têm definições concorrentes em arquivos diferentes. Sem evidência de bundle catastrófico.  
Correção proposta: Definir um proprietário por componente, remover somente regras provadamente substituídas, manter budget de assets e comparação visual. Preferir font stack de sistema já disponível a três downloads de famílias externos.  
Esforço: M  
Dependências: UI-A-001, UI-A-002

### SEC-A-001 — Dependências Python instaladas divergem e têm advisories

ID: SEC-A-001  
Título: Dependências Python instaladas divergem e têm advisories  
Severidade: Alto  
Evidência: requirements.txt:8,12,14; src/apps/ingestion/ocr_tasks.py:143; 2026-10-02/python-advisories.json  
Verificado em: verificação de ambiente + leitura de código  
Referência: [OWASP2025 A03 — supply chain; advisory Requests](https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures/)  
Impacto: Requests2.32.3 está instalado e declarado; Pillow11.0.0 instalado vs12.0.0 declarado; PyMuPDF1.24.10 instalado vs1.28.2 declarado. PyPI retornou4 registros para Requests e33 para Pillow (IDs duplicados GHSA/PYSEC, não33falhas únicas). Não foi demonstrada exploração nem analisada toda árvore Python.  
Correção proposta: Atualizar pins compatíveis em venv novo de QA, auditar árvore completa e rodar OCR/PDF/network testes. Não sobrescrever venv/config atual ou declarar dependência segura só porque pip check passou.  
Esforço: M  
Dependências: Nenhuma

### SEC-A-002 — Ferramentas de testes JavaScript têm sete achados high

ID: SEC-A-002  
Título: Ferramentas de testes JavaScript têm sete achados high  
Severidade: Médio  
Evidência: tests/js/package.json:10; tests/js/package-lock.json; 2026-10-02/npm-advisories.json  
Verificado em: verificação de dependências  
Referência: [OWASP2025 A03 — supply chain](https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures/)  
Impacto: npm audit reporta7pacotes high na cadeia Puppeteer. npm audit --omit=dev encontrou0; não atribuir esses achados ao bundle de produção.  
Correção proposta: Atualizar Puppeteer em instalação de QA compatível com browser/Node; revisar lockfile, repetir npm test e audit; não usar npm audit fix --force.  
Esforço: M  
Dependências: Nenhuma

### COD-A-001 — Hotspot de RAG excede orçamento de arquitetura

ID: COD-A-001  
Título: Hotspot de RAG excede orçamento de arquitetura  
Severidade: Médio  
Evidência: src/processing/rag_service.py; 2026-10-02/architecture.json  
Verificado em: comando executado  
Referência: [Orçamento arquitetural do próprio projeto](C:/Jurix/scripts/architecture_budget_v2.py:10); [Django — rede de segurança de testes](https://docs.djangoproject.com/en/5.2/topics/testing/overview/)  
Impacto: 867linhas para orçamento850, passed:false. Aumentar o orçamento esconderia dívida; os testes verdes não invalidam o gate.  
Correção proposta: Extrair a orquestração de geração/validação para módulo coeso, mantendo API/eventos; medir antes/depois sem mexer no orçamento.  
Esforço: M  
Dependências: IA-A-001, IA-A-002

### COD-A-002 — Testes verdes não cobrem os contratos reproduzidos

ID: COD-A-002  
Título: Testes verdes não cobrem os contratos reproduzidos  
Severidade: Médio  
Evidência: src/tests/test_workspace_routes.py:313; src/tests/test_legal_diff.py; tests/js/real.browser.test.mjs; coverage.json  
Verificado em: leitura de código + testes  
Referência: [Django — testes por comportamento](https://docs.djangoproject.com/en/5.2/topics/testing/overview/)  
Impacto: 805pytestpassam e npm test passa, mas PDF só testa assinatura, diff só testa artigos simples e fixturesbrowser não exercitam RAG real/formato de número desta auditoria.  
Correção proposta: Cada correção deve começar por regressão que falha no baseline; acrescentar smoke de usuário com corpus QA e matriz responsiva, sem exigir texto LLM idêntico.  
Esforço: M  
Dependências: UX-A-008, UX-A-004, IA-A-001

### COD-A-003 — Validação de coleção depende de restrições do HTML

ID: COD-A-003  
Título: Validação de coleção depende de restrições do HTML  
Severidade: Médio  
Evidência: src/apps/legislation/workspace_views.py:328–389; src/apps/legislation/models.py:626; templates/legislation/workspace/collections.html:48  
Verificado em: leitura de código; não testado com conta em runtime  
Referência: [GOV.UK — erros associados aos campos](https://design-system.service.gov.uk/components/error-summary/)  
Impacto: O servidor não limita name a120 nem description a500 como o formulário; norma_id é passado ao ORM sem parse seguro. O HTML não é barreira para POST direto; PostgreSQL pode falhar por limite de coluna.  
Correção proposta: Validar no servidor os mesmos limites e IDs inteiros positivos; responder com erros de campo sem500, mantendo escopo por proprietário e CSRF.  
Esforço: P  
Dependências: Nenhuma

## Hipóteses a validar — não são fatos nem tarefas corretivas automáticas

- Corrida entre dois controladores de sidebar/chat em transição: CSS/JS sobrepostos existem; não reproduzi consistentemente flicker final após todas as animações. Não construir SPA para resolver hipótese.
- INP/CLS/LCP, NVDA/leitor de tela, zoom200%, reduced-motion em SO, contraste de **todos** os estados hover/disabled: sem avaliação completa. Há testes de contraste de tokens, não laudo WCAG.
- Interrupção de Ollama após abort: código indica ausência de cancel token; não medi CPU ou duração de término após cancel.
- Escalabilidade de query/memória com100mil dispositivos; pgvector/reranking em Postgres; Redis distribuído; retries Celery: não testados por isolamento/dependências indisponíveis.
- Provadores externos, SSRF em DNS rebinding e comportamento de provedor que devolve stream malformado: existem testes e validação allowlist, não pen-test completo. Não cadastrar chaves reais para “provar”.
- Divergência de datas de publicação em OCR versus SAPL em parte do corpus: requer confronto oficial e revisão; não corrigir automaticamente a partir de footer.
- Coleções precisam de decisão de autenticação do produto. Hoje a tela informa indisponibilidade, em vez de prometer login inexistente. Criar login público/registro não está implicitamente autorizado por esta auditoria.
- Cards grandes/composer com teclado virtual real: viewport móvel não emula teclado/iPhone; precisa dispositivo real.
- “Eventos aplicados” da comparação usa queryset de eventos ativos; revisar correspondência com resultado de consolidação quando houver exemplo de evento, inexistente nesta amostra.

## Matriz de conformidade — amostra, não certificado

A=atende no fluxo testado; P=parcial; F=falha constatada; NV=não verificado. Normas incluem list/detail; árvore/comparação recebem coluna própria.

| Critério | Assistente/fontes | Normas | Pesquisa | Histórico/sidebar | Configurações | Coleções | Árvore/comparação |
|---|---|---|---|---|---|---|---|
| Apple: hierarquia/deferência | P — composer denso | P — hero e índice | P — ranking impede tarefa | A no menu atual; P temporário | A na amostra | P — função indisponível | P — diff falso |
| Apple: toque44px | P — pill/clipping | P — índice16px | P — amostra de controles | P — menu34px | A nos campos principais | P | P |
| M3: tokens/estados | P — regras duplicadas | P | P | P | P | P | P |
| WCAG1.4.3 contraste | P — tokens testados | P | P | P | P — claro inspecionado | P | P |
| WCAG1.4.10 reflow320 | F — fonte cortada | A na amostra | A na amostra | A na amostra | A na amostra | A na amostra | A; scroll interno tabela |
| WCAG2.1.1 teclado | P — drawerEscape passa | F — ações escondidas desktop | P | P — temporário | P — erros foco passam | NV autenticado | P — árvore interagida |
| WCAG2.4.7/2.4.11 foco | P — retorno drawer passa | P — ações inacessíveis | P | P — cancelar devolve controle | P | NV autenticado | P |
| WCAG2.5.8 alvos24px/exceções | NV completo | Índice medido; espaçamento26px, sem colisão | NV | NV | NV | NV | NV |
| Zoom200% / leitor real | NV | NV | NV | NV | NV | NV | NV |
| Reduced-motion | P código/testes; SO NV | P | P | P | P | P | P |
| Nielsen: feedback/recuperação | P — recusa sem causa útil | P — PDF e busca | F — norma exata não priorizada | A nos casos testados | A validação incompleta | P indisponível | F integridade do diff |

Referências oficiais consultadas: [Apple UI tips](https://developer.apple.com/design/tips/); [WCAG2.2](https://www.w3.org/TR/WCAG22/); [M3 codelab oficial de temas](https://developer.android.com/codelabs/m3-design-theming); [NN/g](https://www.nngroup.com/articles/ten-usability-heuristics/); [Carbon table](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines); [GOV.UK errors](https://design-system.service.gov.uk/components/error-summary/); [Web Vitals](https://web.dev/articles/vitals); [Django deploy](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/); [OWASP2025 A03](https://top10.owasp.org/2025/A03_2025-Software_Supply_Chain_Failures/); [Requests advisory](https://github.com/psf/requests/security/advisories/GHSA-9hjg-9r4m-mvj7); [Pillow advisories](https://github.com/python-pillow/Pillow/security/advisories).

HIG completo e a página web [M3 tokens](https://m3.material.io/foundations/design-tokens/overview) retornaram conteúdo dependente de JS, insuficiente para verificação textual integral. Não certificar aderência integral a esses documentos; Apple tips e codelab oficial foram fontes primárias acessíveis. Não foram usados/copied assets de produtos terceiros. Comparações com ChatGPT são somente padrões de navegação/context menu já pedidos pelo usuário, não licenciamento de marca/ícones.

## Apêndice — todas as rotas resolvidas

91 padrões, incluindo AdminSite e modelos registrados. Inventário bruto em [route-inventory.json](C:/Jurix/docs/audit/2026-10-02/route-inventory.json). As colunas “template/assets” referem-se ao inventário acima; endpoints JSON não possuem template. Rotas admin usam assets/admin do Django. Regeneração/admin/CRUD não marcados como runtime pela existência de um teste.

| Padrão | Nome | View/handler | Template/assets | Runtime |
|---|---|---|---|---|
| / | home_redirect | django.views.generic.base.RedirectView | Inventário de telas acima | HTTP redirect200 |
| /assistente/ | assistant | src.apps.legislation.workspace_views.assistente_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /assistente/<str:session_slug>/ | assistant_session | src.apps.legislation.workspace_views.assistente_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /configuracoes/ | settings | src.apps.legislation.workspace_views.settings_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /pesquisa/ | legal_search | src.apps.legislation.workspace_views.legal_search_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /colecoes/ | collections | src.apps.legislation.workspace_views.collections_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /colecoes/<int:pk>/ | collection_detail | src.apps.legislation.workspace_views.collection_detail_view | Inventário de telas acima | Visitante redirecionado; autenticado não |
| /historico/ | history | src.apps.legislation.workspace_views.history_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /admin/ | index | django.contrib.admin.sites.AdminSite.index | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/login/ | login | django.contrib.admin.sites.AdminSite.login | Django admin; template depende do handler | HTTP GET login200; sem autenticação |
| /admin/logout/ | logout | django.contrib.admin.sites.AdminSite.logout | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/password_change/ | password_change | django.contrib.admin.sites.AdminSite.password_change | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/password_change/done/ | password_change_done | django.contrib.admin.sites.AdminSite.password_change_done | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/autocomplete/ | autocomplete | django.contrib.admin.sites.AdminSite.autocomplete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/jsi18n/ | jsi18n | django.contrib.admin.sites.AdminSite.i18n_javascript | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/r/<path:content_type_id>/<path:object_id>/ | view_on_site | django.contrib.contenttypes.views.shortcut | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/group/ | auth_group_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/group/add/ | auth_group_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/group/<path:object_id>/history/ | auth_group_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/group/<path:object_id>/delete/ | auth_group_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/group/<path:object_id>/change/ | auth_group_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/group/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/<id>/password/ | auth_user_password_change | django.contrib.auth.admin.UserAdmin.user_change_password | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/ | auth_user_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/add/ | auth_user_add | django.contrib.auth.admin.UserAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/<path:object_id>/history/ | auth_user_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/<path:object_id>/delete/ | auth_user_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/<path:object_id>/change/ | auth_user_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/auth/user/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/norma/ | legislation_norma_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/norma/add/ | legislation_norma_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/norma/<path:object_id>/history/ | legislation_norma_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/norma/<path:object_id>/delete/ | legislation_norma_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/norma/<path:object_id>/change/ | legislation_norma_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/norma/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/dispositivo/ | legislation_dispositivo_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/dispositivo/add/ | legislation_dispositivo_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/dispositivo/<path:object_id>/history/ | legislation_dispositivo_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/dispositivo/<path:object_id>/delete/ | legislation_dispositivo_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/dispositivo/<path:object_id>/change/ | legislation_dispositivo_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/dispositivo/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/eventoalteracao/ | legislation_eventoalteracao_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/eventoalteracao/add/ | legislation_eventoalteracao_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/eventoalteracao/<path:object_id>/history/ | legislation_eventoalteracao_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/eventoalteracao/<path:object_id>/delete/ | legislation_eventoalteracao_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/eventoalteracao/<path:object_id>/change/ | legislation_eventoalteracao_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/eventoalteracao/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatsession/ | legislation_chatsession_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatsession/add/ | legislation_chatsession_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatsession/<path:object_id>/history/ | legislation_chatsession_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatsession/<path:object_id>/delete/ | legislation_chatsession_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatsession/<path:object_id>/change/ | legislation_chatsession_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatsession/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatmessage/ | legislation_chatmessage_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatmessage/add/ | legislation_chatmessage_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatmessage/<path:object_id>/history/ | legislation_chatmessage_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatmessage/<path:object_id>/delete/ | legislation_chatmessage_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatmessage/<path:object_id>/change/ | legislation_chatmessage_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/chatmessage/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/collection/ | legislation_collection_changelist | django.contrib.admin.options.ModelAdmin.changelist_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/collection/add/ | legislation_collection_add | django.contrib.admin.options.ModelAdmin.add_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/collection/<path:object_id>/history/ | legislation_collection_history | django.contrib.admin.options.ModelAdmin.history_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/collection/<path:object_id>/delete/ | legislation_collection_delete | django.contrib.admin.options.ModelAdmin.delete_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/collection/<path:object_id>/change/ | legislation_collection_change | django.contrib.admin.options.ModelAdmin.change_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/legislation/collection/<path:object_id>/ | — | django.views.generic.base.RedirectView | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/^(?P<app_label>auth\|legislation)/$ | app_list | django.contrib.admin.sites.AdminSite.app_index | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /admin/(?P<url>.*)$ | — | django.contrib.admin.sites.AdminSite.catch_all_view | Django admin; template depende do handler | Não testado em runtime; sem conta QA/admin |
| /normas/ | norma_list | src.apps.legislation.views.NormaListView | Inventário de telas acima | Browser real; consultar inventário de estados |
| /normas/chatbot/ | chatbot | src.apps.legislation.views.chatbot_view | Inventário de telas acima | HTTP200 |
| /normas/chatbot/<str:session_slug>/ | chatbot_session | src.apps.legislation.views.chatbot_view | Inventário de telas acima | Não visitada; alias do assistente |
| /normas/<int:pk>/ | norma_detail | src.apps.legislation.views.NormaDetailView | Inventário de telas acima | Browser real; consultar inventário de estados |
| /normas/<int:pk>/export/pdf/ | norma_pdf_export | src.apps.legislation.views.norma_pdf_export_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /normas/<int:pk>/compare/ | norma_compare | src.apps.legislation.views.norma_compare_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /normas/<int:pk>/tree/ | norma_tree | src.apps.legislation.views.norma_dispositivos_tree_view | Inventário de telas acima | Browser real; consultar inventário de estados |
| /api/v1/health/live/ | health_live | src.apps.legislation.api_health.health_live_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/health/ | health_check | src.apps.legislation.api_views.health_ready_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/health/ready/ | health_ready | src.apps.legislation.api_views.health_ready_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/search/semantic/ | semantic_search | src.apps.legislation.api_views.semantic_search_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/search/answer/ | rag_answer | src.apps.legislation.api_views.rag_answer_api | JSON/SSE; sem template | Não testado em runtime; suíte automatizada |
| /api/v1/search/answer/stream/ | rag_answer_stream | src.apps.legislation.api_views.chatbot_stream_api | JSON/SSE; sem template | POST SSE real e CSRF/Ollama |
| /api/v1/normas/ | norma_list | src.apps.legislation.api_views.norma_list_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/suggestions/ | dynamic_suggestions | src.apps.legislation.api_views.dynamic_suggestions_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/normas/<int:pk>/ | norma_detail | src.apps.legislation.api_views.norma_detail_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/normas/<int:pk>/timeline/ | norma_timeline | src.apps.legislation.temporal_api.norma_timeline_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/normas/<int:pk>/conflicts/ | norma_conflicts | src.apps.legislation.temporal_api.norma_conflicts_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/chat/sessions/ | chat_sessions | src.apps.legislation.api_views.chat_sessions_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/chat/attachments/ | chat-attachments | src.apps.legislation.api_views.chat_attachment_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/chat/attachments/<str:attachment_id>/ | chat-attachment-detail | src.apps.legislation.api_views.chat_attachment_detail_api | JSON/SSE; sem template | DELETE não executado; suíte |
| /api/v1/chat/sessions/<int:session_id>/ | chat_session_detail | src.apps.legislation.api_views.chat_session_detail_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/chat/sessions/slug/<str:slug>/ | chat_session_by_slug | src.apps.legislation.api_views.chat_session_by_slug_api | JSON/SSE; sem template | GET público ou401 verificado; mutations não executadas |
| /api/v1/chat/sessions/<int:session_id>/regenerate/ | chat_session_regenerate | src.apps.legislation.api_views.chat_session_regenerate_api | JSON/SSE; sem template | Não testado em runtime; suíte automatizada |

## Handoff

Ordem de leitura para a implementação: este relatório → plano mestre → design system → [guia do Luna proposto](C:/Jurix/docs/audit/JURIX_LUNA_EXECUTION_GUIDE.proposed.md). Não misturar IDs da auditoria anterior. Iniciar por T-001 somente depois de nova autorização de implementação; o prompt atual **não autoriza alterar produto nem commit**.

### Conferência final do pacote e do workspace

Conferência executada: 27 IDs de achados, 28 tarefas, todos os campos obrigatórios presentes e todos os achados cobertos por tarefas. Os screenshots citados existem; 47 imagens QA foram preservadas. Inventário com 91 padrões de rota; matriz com 45 casos de navegador nas larguras 320/360/768/1280/1920px.

[git-final.json](C:/Jurix/docs/audit/2026-10-02/git-final.json) confirma: branch main e HEAD inalterados; staged inalterado; zero arquivos preexistentes com hash modificado; banco SQLite original com o mesmo hash. As 39 modificações tracked continuam sendo as anteriores à auditoria. As únicas criações no workspace são os quatro documentos propostos, evidências/screenshots e auxiliares desta auditoria. Originais JURIX_*.md e GOAL.md intactos. Sem commit, push, pull, merge ou troca de branch.

O override de viewport foi removido ao terminar. Servidor QA em 8006 e aba QA mantidos para continuidade, com banco temporário separado; não são uma implantação nem uma atualização do servidor pessoal em 8005.

