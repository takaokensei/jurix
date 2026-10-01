# Design system Jurix — referência atual

Este arquivo registra os tokens que o frontend realmente define em 2026-10-01. Não declara conformidade WCAG global: os contrastes abaixo são cálculos de pares representativos de tokens, não auditoria de cada combinação renderizada.

## Propriedade e fontes

| Responsabilidade | Arquivo atual | Decisão |
|---|---|---|
| Tokens visuais efetivamente usados por Assistente, workspace e evidências | `src/apps/core/static/css/jurix-figma.css` | Fonte de verdade para os tokens `--figma-*`, `--jurix-space-*`, `--jurix-radius-*`, `--jurix-motion-*` e `--font-*`. Claro/escuro muda em `:root[data-theme="light"]`. |
| Fundação Swiss histórica e tokens genéricos `--color-*`, `--space-*`, `--font-size-*` | `src/apps/core/static/css/swiss-design-system.css` | Legado ainda consumido por superfícies antigas; não adicionar uma paleta concorrente. Migrar consumidor por consumidor com teste visual. |
| Primitivas de componente e foco | `src/apps/core/static/css/jurix-components.css` | Consome as variáveis existentes; manter como camada de componente, sem redefinir cores semânticas. |
| Layout do workspace | `src/apps/core/static/css/workspace.css` | Consumidor dos tokens `--figma-*`; valores CSS locais ainda existem e não são automaticamente tokens globais. |

Há duplicação histórica de `:root` e de `--font-sans` em folhas diferentes. A consolidação precisa ser gradual; `jurix-figma.css` é o dono visual atual, enquanto `swiss-design-system.css` permanece compatibilidade. Um valor legado só pode ser removido após busca de todos os consumidores e execução do contrato visual.

## Tokens medidos no código

| Papel | Escuro | Claro |
|---|---|---|
| Canvas | `--figma-bg-root: #081220` | `#F7F9FC` |
| Sidebar | `--figma-bg-sidebar: #0B111E` | `#FFFFFF` |
| Superfície | `--figma-bg-surface: #111827` | `#FFFFFF` |
| Texto principal | `--figma-text-white: #F8FAFC` | `#0F172A` |
| Texto de corpo | `--figma-text-body: #E2E8F0` | `#334155` |
| Texto secundário | `--figma-text-muted: #94A3B8` | `#475569` |
| Ação azul | `--figma-blue-primary: #2563EB` | `#1D4ED8` |
| Foco | anel azul claro `#60A5FA`, 3 px translúcido | anel azul `#1D4ED8`, 3 px translúcido |
| Espaçamento | 4, 8, 12, 16, 24 px | mesmos tokens |
| Raios | 8, 12, 16 px | mesmos tokens |
| Movimento | 160 ms rápido, 220 ms padrão | igual; `prefers-reduced-motion` deve eliminar movimento não essencial |
| Tipografia | UI system sans; serif só editorial; mono para código | mesma escala |

Os valores estão em `src/apps/core/static/css/jurix-figma.css`. A fonte genérica é `system-ui, -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif`; `swiss-design-system.css` ainda declara famílias adicionais e outra escala, por isso não se deve presumir que cada página usa a mesma fonte efetiva.

## Contraste calculado (sRGB, razão relativa WCAG)

Método: conversão sRGB para luminância relativa e razão `(Lmais clara + .05) / (Lmais escura + .05)`, calculada em Node.js. É uma checagem de pares nominais; transparências, estados hover, imagens, herança/cascata e contraste de foco precisam de inspeção por componente.

| Par token | Razão | Referência AA |
|---|---:|---|
| Texto principal escuro sobre canvas escuro | 17.96:1 | ≥4.5:1 |
| Texto de corpo escuro sobre canvas escuro | 15.24:1 | ≥4.5:1 |
| Texto secundário escuro sobre canvas escuro | 7.33:1 | ≥4.5:1 |
| Azul claro sobre canvas escuro | 7.39:1 | ≥4.5:1 |
| Texto principal claro sobre canvas claro | 16.93:1 | ≥4.5:1 |
| Texto de corpo claro sobre canvas claro | 9.82:1 | ≥4.5:1 |
| Texto secundário claro sobre canvas claro | 7.18:1 | ≥4.5:1 |
| Azul de ação claro sobre canvas claro | 6.35:1 | ≥4.5:1 |
| Branco sobre botão azul escuro (`#2563EB`) | 5.17:1 | ≥4.5:1 |
| Branco sobre botão azul claro (`#1D4ED8`) | 6.70:1 | ≥4.5:1 |

Contorno, estados não textuais e indicadores de foco devem alcançar 3:1 contra cores adjacentes. O anel translúcido atual precisa ser medido sobre cada superfície real antes de ser declarado conforme. Contraste de foco não fica provado pelos números de texto acima.

## Regras de implementação

1. Usar os tokens semânticos existentes para novas cores; não inserir cores arbitrárias no HTML nem criar nova paleta por tela.
2. Manter foco visível com espessura mínima 2 CSS px e offset; alvo de toque preferencial 44×44 CSS px.
3. Não usar cor como único sinal: combinar texto/ícone/estado semântico.
4. Respeitar zoom e reflow; validar ao menos 320/360/768/1280/1920 px e zoom 200% antes de afirmar compatibilidade.
5. Reduzir duração/movimento para `prefers-reduced-motion: reduce`; evitar loops decorativos.
6. Sans-serif para interface e leitura corrente; serif fica restrita a títulos editoriais deliberados.

## Mapeamento de componentes atuais

| Componente/área | Implementação atual | Tokens/regras |
|---|---|---|
| App shell e sidebar | `workspace/base.html`, `_sidebar.html`, `workspace.css`, `jurix-sidebar.css` | Canvas/surface/border, alvos e navegação nativa |
| Composer e conversa | `chatbot.html`, `jurix-chat-shell.css`, `jurix-figma.css` | Sans, superfície elevada, foco, estado de streaming |
| Drawer e cartões de evidência | `jurix-rag.js`, `jurix-rag.css` | Cor semântica, estado textual, links oficiais explícitos |
| Norma e árvore | `norma_detail.html`, `jurix-legal-detail.css`, `jurix-legal-detail.js` | Coluna de leitura, hierarquia jurídica e foco de âncora |
| Campos, botões, estados de erro | `jurix-components.css`, `workspace.css` | Foco/disabled/hover explícitos e rótulos associados |

## Referências de princípios

- Apple HIG — hierarquia, consistência, legibilidade e alvos de interação: <https://developer.apple.com/design/human-interface-guidelines/>
- Material Design 3 — papéis de cor, forma, elevação e estados de componentes: <https://m3.material.io/foundations>
- WCAG 2.2 AA — contraste 1.4.3/1.4.11, foco 2.4.7/2.4.11, alvos 2.5.8 e reflow 1.4.10: <https://www.w3.org/TR/WCAG22/>
