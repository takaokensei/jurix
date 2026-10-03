# Jurix — especificação de design system proposta (02/10/2026)

Estado: proposta para implementação posterior; nenhum token/component foi alterado nesta auditoria. Fonte de verdade é o código local, não mockup anterior. Objetivo: precisão jurídica, leitura confortável e baixa densidade de controles permanentes. Manter Django/templates/JavaScript modular. Trocar framework não resolveria os achados de conteúdo e aumentaria o escopo.

Ler também [auditoria](C:/Jurix/docs/audit/JURIX_FULL_AUDIT.proposed.md) e [tarefas](C:/Jurix/docs/audit/JURIX_LUNA_EXECUTION_GUIDE.proposed.md). Decisões abaixo são especificação de produto, não alegação de WCAG/HIG certificado.

## Fundamentos e limites das referências

[Apple UI tips](https://developer.apple.com/design/tips/) sustenta organização e alvos de toque; não copiar SF Symbols, fontes ou marca. HIG completo não foi verificado textualmente, conforme auditoria. [Codelab M3 oficial](https://developer.android.com/codelabs/m3-design-theming) sustenta papéis de cores/temas; a página m3.material.io carregava só shell JS. [WCAG2.2](https://www.w3.org/TR/WCAG22/) define requisitos web. Distinguir 44px como meta ergonômica do produto de24px/exceções de WCAG2.5.8. Apple pt não é literalmente unidade CSS: usamos44CSSpx como adaptação de produto web.

### Cores semânticas propostas

Adicionar C:/Jurix/src/apps/core/static/css/jurix-tokens.css antes dos componentes em ambos os templates shell. Preservar variáveis --figma-* por aliases; não fazer uma substituição global cega. Valores estáveis e intencionais:

| Papel / token --jurix-* | Escuro | Claro | Uso |
|---|---|---|---|
| canvas | #081220 | #F7F9FC | Fundo da aplicação |
| surface | #111827 | #FFFFFF | Documento, composer |
| sidebar | #0B111E | #FFFFFF | Navegação |
| surface-hover | #1E293B | #EAF0F8 | Hover não selecionado |
| text | #F8FAFC | #0F172A | Texto principal |
| text-body | #E2E8F0 | #334155 | Resposta/documento |
| text-muted | #94A3B8 | #475569 | Metadata legível |
| action | #2563EB | #1D4ED8 | Botão primário |
| action-hover | #1D4ED8 | #1E40AF | Hover primário |
| on-action | #FFFFFF | #FFFFFF | Texto do botão |
| link | #93C5FD | #1D4ED8 | Citação/link com sublinhado |
| border | #334155 | #D7E0EC | Separação decorativa |
| control-border | #64748B | #64748B | Limite de controle quando necessário |
| focus | #93C5FD | #1D4ED8 | Outline de foco |
| success | #6EE7B7 | #047857 | Verificado, com ícone/texto |
| warning | #FDE68A | #92400E | Limitação, com rótulo |
| danger | #FCA5A5 | #B91C1C | Erro |
| danger-action | #B42332 | #B42332 | Ação destrutiva + texto branco |

Contraste deve ser calculado no **fundo final composto**, incluindo hover, alpha e disabled. Não usar border decorativo como única indicação de campo. Texto normal≥4,5:1; texto grande/UI relevante≥3:1, conforme [WCAG contraste](https://www.w3.org/WAI/WCAG22/Understanding/contrast-minimum.html). Disabled continua legível: indicar disabled por semântica, não apenas opacity indiscriminada.

### Tipografia e densidade

Usar fallback de sistema já declarado em jurix-figma.css: system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif. Remover requisições Google Fonts nesta proposta: sem baixar novas fontes nem nova dependência/licença. Serif do texto legal pode permanecer opcional, mas headings de workspace/navigation/composer usam sans, não misturar fontes arbitrariamente por rota.

| Token | Tamanho / altura | Peso | Contexto |
|---|---|---|---|
| --jurix-type-caption | .8125rem /1.45 | 400/500 | Metadata, rótulos auxiliares |
| --jurix-type-label | .875rem /1.45 | 500/600 | Controles |
| --jurix-type-body | 1rem /1.65 | 400 | Resposta e norma |
| --jurix-type-lead | 1.125rem /1.55 | 400 | Resumo real, não descrição da UI |
| --jurix-type-section | 1.25rem /1.4 | 600 | Seção de documento |
| --jurix-type-title | clamp(1.5rem,2.5vw,2rem) /1.2 | 650/700 | H1 da tela |

Não reduzir texto jurídico para caber num card. Zoom/reflow ajustam layout, não font-size. Corpo com46rem de largura máxima; listas/tabelas podem exigir superfície mais larga. Legibilidade prevalece sobre esconder trecho: botão “Ler trecho completo” claro e operável.

### Espaçamento, forma, elevação e foco

Escala em rem: .25,.5,.75,1,1.5,2,3 (equivalentes4,8,12,16,24,32,48 com base16). Gaps entre labels/campos8px; campos de grupo16px; seções24–32px; margem móvel16px. A versão compacta altera espaçamento, **não** corpo da norma nem alvo móvel.

Raios: controles10px, cards12px, composer16px, dialog16px. Pill só para metadata curta; não empilhar frases longas em cápsula inflexível.

Elevação0: fundo/linhas;1: documento com borda;2: menu com shadow0 8px 24px rgb(0 0 0/.18);3: dialog/drawer com backdrop simples. Tema claro sem sombras pesadas em toda mensagem. Não depender de glassmorphism/blur para separar informação.

Foco: outline2px solid var(--jurix-focus), outline-offset3px, scroll-margin-block-start5rem em âncoras. Não remover outline; shadow translúcida não substitui outline. Ver [WCAG Keyboard](https://www.w3.org/WAI/WCAG22/Understanding/keyboard.html).

### Motion

Tokens: fast120ms, standard180ms, drawer220ms, easing cubic-bezier(.2,.8,.2,1). Animar opacity/transform, não largura de coluna com leitura em andamento. Foco e ação não aguardam a animação. Source/copy revelados juntos após conteúdo validado, fade-in160ms; atualizar dados imediatamente mesmo se animação ainda estiver ocorrendo.

Sob prefers-reduced-motion: animation:none e transition:none nos componentes próprios; sem auto-scroll suave. Não apagar estados de loading por isso: continuar feedback textual. Cursor/pulso somente durante processamento real, sem loops decorativos. Não usar typewriter para mascarar geração buffered; streaming exige contrato seguro próprio.

## Componentes e estados

### AppShell / Sidebar / SessionRow

Uma partial visual e um renderer de linhas, inclusive criação temporária. Expanded15rem, collapsed4.5rem desktop; mobile≤900px é overlay240px com backdrop. Ícones permanecem no rail; cada um tem nome acessível e tooltip acionável por foco. Evitar auto-collapse por envio de pergunta. Estado persiste antes do primeiro paint; navegação para rota já ativa não recarrega. Nenhuma SPA/migração de framework é necessária.

SessionRow: link independente do botão “Opções de conversa”; título truncado por ellipsis, fulltitle no nome acessível; pin marcado com texto acessível. Scroll vertical reservado na lista, padding-inline-end8px mínimo; menu renderizado fora do overflow. Dropdown role=menu, setas/Home/End/Escape, foco retornado ao trigger. Renomear/fixar/excluir existentes continuam funcionais. Menuitem44px móvel; desktop40px, mas trigger44px. Loading/empty/pending substituem-se, não coexistem.

### Botão / link / disclosure

Primário, secundário, ghost e danger: **mínimo de 44px** de altura no produto; usar min-height: 2.75rem, não height fixa quando o rótulo quebra. Estados: default, hover, focus-visible, pressed, disabled, loading. Loading preserva largura e rótulo “Enviando/Processando”. Dialog destrutivo começa com foco em cancelar, não excluir.

Link jurídico sublinhado e legível. Lei inteira abre documento sem text fragment; artigo/inciso abre trecho oficial quando identificável. URLs derivadas de metadata validada, nunca LLM. Disclosure sempre visível se seus filhos dependem dele; summary escondido em details fechado é proibido em qualquer breakpoint.

### SearchComposer

Uma textarea expansível, send/cancel44px, opções em menu no móvel. Desktop: input+ações secundárias numa única superfície alinhada à coluna, não à viewport incluindo sidebar. Mobile: altura ociosa≤180px em360×900, textarea até30dvh quando cresce; anexos selecionados podem ampliar com limites. Enter envia, Shift+Enter quebra linha, composição IME não envia prematuramente.

Estados: idle, submitting, retrieving, generating, verifying, completed, failed, cancelled. “Preparando a resposta” é status, não badge assustador “rascunho”. Sem texto jurídico não validado. Cancelar mantém a pergunta e retry idempotente; não alegar que upstream parou quando não confirmou.

### AssistantMessage / UserMessage / EvidenceSummary

UserMessage discreta e alinhada; AssistantMessage com texto1rem/1.65, largura46rem. Conclusão direta, poucos títulos, listas para enumeração. Não inserir automaticamente heading “Resposta” e “Fim da resposta”.

EvidenceSummary: contagem e “Ver fontes” visíveis a320px. Desktop pode conter metadata secundária; mobile move essa informação para drawer. max-inline-size100%, min-width0, wrapping sem cortar ação. Ao receber SSE armazenar evidências/IDs; mostrar bloco de ações após final validado, conforme política mais recente. Copy preserva Markdown/citações e tem confirmação status não intrusiva.

### SourceDrawer / SourceCard / ConfidenceBadge

Drawer dialog acessível, desktop480px máximo, mobile100vw ou largura segura com16px; close44px, Escape, tab trap, restore focus, no backdrop infinito. Agrupar por norma; expandir todas reflete grupos abertos parcialmente/todos/nenhum. Transições não impedem abrir/fechar nova pergunta.

SourceCard: norma/artigo + trecho; “Trecho recuperado” se não houver claim mapping; “Sustenta: …” apenas com claim validado. Dispositivo exato recebe “Dispositivo identificado”; similaridade é dado técnico opcional, não probabilidade jurídica. Ausência de evidencia nunca “Alta confiança”. CitationID estável por norma/dispositivo; claim association separada da URL.

### NormaHeader / ArticleIndex / NormaTimeline / ComparisonTable

Header: identificação, ementa e situação temporal qualificadas, fonte oficial e principais ações descobríveis. Metadados abaixo do título, não competindo com ele. Índice de artigos com filhos recolhíveis, não coleção de links16px de altura. Texto em ordem normativa com indentação moderada; leitor não deve saltar dezenas de cards para entender o artigo.

Timeline: publicação/início/revogação com proveniência e revisão, não inferir vigência atual de data única. Comparação informa “diferenças textuais automáticas” e mantém aviso existente. Mesma estrutura deve produzir mesma unidade em ambos os lados. Tabela em desktop; no móvel o scroll interno é acessível/rotulado (sem page overflow); controles de rolagem e headers claros. Baseado em [Carbon data table](https://www.carbondesignsystem.com/building-blocks/core/components/data-table/guidelines).

### Campo / validação / EmptyState / ErrorState / Toast

Field label sempre visível, help associado com aria-describedby. Erro específico abaixo do campo + resumo quando múltiplos, primeiro inválido focado, aria-invalid=true. Validação no servidor é obrigatória, mesmo com maxlength HTML. Padrão [GOV.UK error summary](https://design-system.service.gov.uk/components/error-summary/).

EmptyState: um objetivo, uma headline, uma ação primária. Não confundir coleção vazia com coleção indisponível. Configuração sem serviço não deve prometer sucesso; feedback vem do status comprovado. ErrorState distingue norma ausente no corpus, evidência insuficiente, modelo falhou, rede interrompida. Não usar o mesmo pedido “informe número e ano” quando já foram enviados.

Toast role=status,3–5s apenas para sucesso reversível; erro relevante fica persistente perto da ação. Nunca toast para única explicação de falha jurídica. Dialog width min(420px,100vw−32px),focus/labels/restoration; transição160ms, reduced-motion sem animação.

## Layout responsivo

- 320–767px: margem de 16px; sidebar overlay; opções do composer em disclosure; drawer móvel; resultados em uma coluna. Medir overflow interno, não só document.scrollWidth.
- 768–900px: uma/duas colunas conforme espaço real; navegação overlay; formulários não esmagados.
- 901–1279px: sidebar de 15rem/rail de 4.5rem; conteúdo min-width: 0; centralização considera espaço restante.
- 1280–1920px: coluna de leitura de 46rem, biblioteca até 72rem; não aumentar linhas jurídicas para preencher monitor.
- Zoom de 200% e fonte personalizada: testes de navegador real adicionais obrigatórios; nenhuma certificação com matriz de viewport sozinha.
- Modal/Drawer usa conteúdo rolável próprio e scroll lock localizado, sem bloquear permanentemente a área principal.

## Mapeamento para arquivos atuais

Prefixos: CSS=C:/Jurix/src/apps/core/static/css/; JS=C:/Jurix/src/apps/core/static/js/; templates=C:/Jurix/src/apps/legislation/templates/legislation/.

| Atual → componente | Arquivos reais / proprietário proposto |
|---|---|
| figma-theme/tokens → Foundations | CSS jurix-figma.css:6; novo jurix-tokens.css; não renomear aliases existentes |
| workspace + chatbot shell → AppShell | templates workspace/base.html, chatbot.html, workspace/_sidebar.html, workspace/_topbar.html; CSS workspace.css/jurix-sidebar.css |
| chat-session-item → SessionRow | JS jurix-sidebar.js:178; substituir criação paralela em chat.js:553 |
| command palette → ConversationSearch | JS command_palette.js; CSS workspace.css; manter ícones DOM sanitizados |
| floating-input-bar → SearchComposer | templates chatbot.html; CSS jurix-search-controls.css/jurix-chat.css; JS jurix-search-controls.js/jurix-chat-controller.js |
| message-body → AssistantMessage | JS jurix-chat-renderer.js, chat.js, jurix-markdown.js; CSS jurix-markdown.css |
| sources-pill → EvidenceSummary | JS chat.js:1000; **CSS jurix-rag.css único proprietário**, remover duplicata de jurix-figma.css após regressão |
| drawer/source cards → SourceDrawer/SourceCard | JS jurix-rag.js; CSS jurix-rag.css; backend serializers.py |
| legal-detail-card → NormaHeader/Timeline | templates norma_detail.html; CSS jurix-legal-detail.css; views.py/temporal_api.py |
| dispositivos-index → ArticleIndex | templates norma_detail.html; JS jurix-legal-detail.js; CSS jurix-legal-detail.css |
| comparison → ComparisonTable | templates norma_compare.html; CSS jurix-legacy-shell.css; processing/legal_diff.py |
| workspace-form → FormField/ErrorState | templates workspace/settings.html/collections.html; JS workspace.js/jurix-collections.js; workspace_views.py |
| workspace-confirm-dialog → Dialog | JS jurix-anonymous-history-page.js/jurix-history-actions.js; CSS workspace.css; preservar foco seguro |
| jurix-session-menu/dialog → SessionMenu | JS jurix-sidebar.js; CSS jurix-sidebar.css |
| workspace-empty-state → EmptyState | templates workspace/search.html/collections.html; CSS workspace.css |

## Aceite visual da especificação

Após cada tarefa: before/after nas rotas afetadas em claro/escuro, 320/360/768/1280/1920px, foco/Tab/Escape. Texto e ações não recortados; fonte de corpo de 1rem; nenhuma ação depende só de ícone sem nome acessível. Compare as screenshots desta auditoria, não aparência copiada de terceiros. Os 189 dispositivos do corpus real permanecem intactos; 24 foi a quantidade recuperada no overview QA, não uma meta fixa de top-k. Preservar contratos de API salvo tarefa explícita.

Não transformar “parecer Apple” em wallpapers, neon ou efeitos. Qualidade aqui é conteúdo confiável, ação previsível, alinhamento e controle.

