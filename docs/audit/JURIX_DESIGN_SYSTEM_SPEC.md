# Especificação de design system — proposta para o Jurix

Este é um contrato de implementação futuro, não um novo tema aplicado. Base atual: `src/apps/core/static/css/jurix-figma.css:6-102` fornece tokens escuros e claros; `src/apps/core/static/css/workspace.css` e folhas por tela ainda têm regras locais. Referências: [HIG — princípios](https://developer.apple.com/design/human-interface-guidelines/design-principles), [layout](https://developer.apple.com/design/human-interface-guidelines/layout), [acessibilidade](https://developer.apple.com/design/human-interface-guidelines/accessibility), [movimento](https://developer.apple.com/design/human-interface-guidelines/motion), [Material 3 — foundations](https://m3.material.io/foundations) (conteúdo completo M3 não verificável nesta ferramenta), [WCAG 2.2](https://www.w3.org/TR/WCAG22/).

## Fundamentos e tokens

Usar nomes semânticos nos componentes; mapear para os `--figma-*` existentes em um único lugar, sem criar mais uma camada de valores avulsos. Os valores abaixo são **propostos** quando não constam do CSS atual e exigem cálculo de contraste para cada par de uso.

| Papel | Escuro atual → alias proposto | Claro atual → mesmo alias | Regra |
| --- | --- | --- | --- |
| Fundo app | `--figma-bg-root: #081220` → `--color-canvas` | `#F7F9FC` | Conteúdo domina, HIG deferência |
| Superfície | `--figma-bg-surface: #111827` → `--color-surface` | `#FFFFFF` | Agrupar por proximidade, HIG layout |
| Borda | `--figma-border: #1F2444` → `--color-border` | `#D7E0EC` | Não depender só da borda para estado |
| Ação | `--figma-blue-primary: #2563EB` → `--color-action` | `#1D4ED8` | Testar texto branco ≥4,5:1 e foco visível |
| Texto principal | `--figma-text-white: #F8FAFC` → `--color-text` | `#0F172A` | Texto normal ≥4,5:1 |
| Texto secundário | `--figma-text-muted: #94A3B8` → `--color-text-muted` | `#475569` | Não usar para erro sem rótulo |
| Feedback | `--figma-green`, `--figma-amber`, `--figma-red` → `--color-success/warning/danger` | valores claros já existentes no tema | Ícone + texto + cor; WCAG 1.4.1 |
| Foco | `--jurix-focus-ring` atual | variante clara atual | Visível, não obscurecido; WCAG 2.4.7/2.4.11 |

Tipografia: manter pilhas atuais `--font-sans: Inter/...` e `--font-serif: Lora/Georgia`, mas não assumir que Google Fonts carrega sob CSP de produção (A-UI-011). Proposta de escala relativa: micro `0.75rem` apenas metadado não essencial; ajuda/label `0.875rem/1.45`; corpo `1rem/1.55`; subtítulo `1.125rem/1.4`; título seção `1.5rem/1.25`; título página `2rem/1.15`. Preferir no máximo regular, medium, semibold; serif apenas identificação de norma/título, nunca para controle denso. Validar a 200% de zoom sem texto cortado. HIG tipografia e WCAG reflow.

Espaçamento: reutilizar `--jurix-space-1..5` = 4/8/12/16/24 px (`jurix-figma.css:48-52`); propor `--space-6:32px` e `--space-7:48px` para seções, sem mudar densidade de dados de uma vez. Raios atuais 8/12/16 px (`:53-55`); escolher 8 para campos, 12 para cards, 16 para modais. Elevação: superfície elevada já existe (`:59,102`); usar sombra só em drawer/modal, não em cada card. Material 3 fundamenta tokens/estados; HIG fundamenta hierarquia e harmonia.

Movimento: tokens atuais 160 e 220 ms (`:56-57`). Hover 120–160 ms, abertura 160–220 ms, nenhuma animação que atrase conclusão. `prefers-reduced-motion: reduce` deve cortar duração e preservar estados finais e foco. HIG movimento; WCAG 2.3.3 como princípio de melhoria, além de exigências AA aplicáveis.

## Componentes e estados verificáveis

| Componente | Estados obrigatórios e semântica | Regra de acessibilidade |
| --- | --- | --- |
| Botão | default, hover, focus-visible, pressed, disabled, busy | nome explícito; 44×44 px recomendado para toque HIG (não confundir com mínimo WCAG 2.5.8); não esconder foco |
| Campo/select | vazio, preenchido, foco, inválido, desabilitado, carregando | `<label for>` real; erro `aria-invalid=true` e `aria-describedby`; não depender só de placeholder; WCAG 3.3.1 |
| Tabela/lista de normas | carregando, vazio, parcial, erro, paginação | cabeçalhos reais; no mobile permitir reflow ou rolagem **interna rotulada**, nunca cortar coluna silenciosamente; [Carbon data table](https://carbondesignsystem.com/components/data-table/usage/) |
| Modal de confirmação | fechado, aberto, ação pendente, falha | foco inicial dentro, Escape quando seguro, devolver foco ao gatilho, ação destrutiva distinta |
| Toast/status | info, sucesso, alerta, erro | `role=status` para informativo, `role=alert` apenas erro urgente; não roubar foco |
| Estado vazio | primeira visita, filtro sem resultado, corpus indisponível | explicar diferença; CTA único relevante; sem prometer recurso inexistente |
| Loading/streaming | queued, retrieving, reranking, grounding, generating, finalizing, completed, insufficient_evidence, failed, cancelled | texto persistente em região viva, cancelamento, evitar anúncio de cada token |
| Evidence/source | recuperada, sustentadora, insuficiente, expandida | relação da afirmação com o artigo; fontes só entram depois do streaming finalizado; não transformar similaridade em probabilidade jurídica |

As decisões de agrupamento, linguagem simples, feedback imediato e prevenção de erro seguem [Nielsen](https://www.nngroup.com/articles/ten-usability-heuristics/). Erro de formulário deve aparecer também ao lado do campo, no padrão [GOV.UK error summary](https://design-system.service.gov.uk/components/error-summary/).

## Layout e responsividade

**≥1280 px:** sidebar estável/retrátil, coluna de leitura confortável (proposta `max-width: 72rem`, texto jurídico idealmente `65–80ch`), drawer de fontes lateral sem encobrir composer. **768–1279 px:** sidebar compacta com ícones rotulados por tooltip acessível; drawer sobreposto e foco gerenciado. **360–767 px:** uma coluna, barra de navegação sem truncar nome de seção, controles escopo/modo em linhas próprias, drawer ocupa largura sem scroll horizontal. **320 px e 200% zoom:** gate ainda pendente; não aprovar só porque 360 px passou. Espaçamento seguro, reflow e alvo tátil baseados em HIG layout/acessibilidade e WCAG 1.4.10/2.5.8.

## Mapeamento atual → componente do sistema

| Componente proposto | Arquivo atual e papel | Próxima tarefa |
| --- | --- | --- |
| AppShell/Sidebar/CommandPalette | `src/apps/legislation/templates/legislation/workspace/base.html`, `src/apps/core/static/css/jurix-figma.css`, `src/apps/core/static/js/command_palette.js` | manter; validar 320 px/zoom, não reescrever sem achado |
| SearchComposer/StreamingIndicator | `src/apps/legislation/templates/legislation/chatbot.html`, `src/apps/core/static/js/chat.js`, `src/apps/core/static/js/jurix-search-controls.js`, `src/apps/core/static/css/jurix-figma.css` | T-001, T-009, T-011 |
| AssistantMessage/ConfidenceBadge/EvidenceSummary/SourceDrawer | `src/apps/core/static/js/chat.js`, `src/apps/core/static/css/jurix-components.css` | T-001 |
| SearchResult/EmptyState | `src/apps/legislation/templates/legislation/workspace/search.html`, `src/apps/legislation/workspace_views.py` | T-004–T-006 |
| HistoryCard | `src/apps/legislation/templates/legislation/workspace/history.html`, `src/apps/legislation/workspace_views.py` | T-007, T-014 |
| FormField/ErrorState | `src/apps/legislation/templates/legislation/workspace/settings.html`, `src/apps/core/static/js/workspace.js`, `src/apps/core/static/css/workspace.css` | T-010, T-012 |
| NormaHeader/NormaTimeline/NormaTree | `src/apps/legislation/templates/legislation/norma_detail.html`, `src/apps/legislation/templates/legislation/norma_tree.html`, `src/apps/core/static/css/jurix-legal-detail.css` | manter; verificar fluxo com norma maior |
| CollectionEmptyState | `src/apps/legislation/templates/legislation/workspace/collections.html` | T-008 |

Não introduzir framework JS novo para implementar esses contratos. Os nomes são responsabilidades de UI, não exigência de classes/componentes React. Antes de declarar AA, medir contraste em todos os estados, testar teclado, zoom e leitor de tela; a auditoria atual não fez isso.
