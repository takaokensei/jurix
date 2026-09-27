# Design system do Jurix

## Decisão

O `jurix-figma.css` é a fonte visual canônica do produto. Ele representa o
shell atualmente usado pelo assistente e pelo workspace: fundo Deep Navy,
superfícies em grafite, azul para ações e foco, tipografia Lora para títulos
editoriais e Inter para interface e conteúdo operacional.

O `swiss-design-system.css` permanece isolado nas telas legadas que ainda
estão sendo migradas. O shell do workspace e o assistente não carregam os dois
vocabulários simultaneamente. Ele não deve receber novos componentes, tokens
ou cores. Novas telas devem estender
`legislation/workspace/base.html` e usar os tokens `--figma-*`.

## Regras de implementação

- O shell compartilhado é `legislation/workspace/base.html`.
- O estado ativo da navegação deve ser expresso por `active_nav` e não por
  marcação duplicada em templates de página.
- Cores de superfície, texto, borda e ação devem usar tokens do sistema
  canônico; valores locais só são aceitáveis para estados sem equivalência
  semântica e devem ser documentados no CSS.
- Toda mudança visual deve ser verificada em desktop e em viewport de 390px.
- Foco visível, `prefers-reduced-motion` e contraste legível são requisitos de
  cada componente, não refinamentos opcionais.
- `scripts/check_design_tokens.py` protege a migração: novos hexadecimais fora
  dos arquivos de tokens falham no CI; remoções do baseline são permitidas.

## Migração atual

`norma_list.html`, `norma_detail.html`, `norma_compare.html` e
`norma_tree.html` agora usam o shell do workspace. O CSS de compatibilidade
`jurix-legacy-shell.css` foi adaptado para superfícies escuras e tokens
compatíveis enquanto os componentes internos dessas três telas são
modernizados.

O arquivo Swiss será removido completamente quando os seletores legados
restantes forem migrados e os testes visuais confirmarem paridade.

Na primeira etapa de migração efetiva, `jurix-legacy-shell.css` deixou de usar
tokens Swiss e fallbacks hexadecimais: compare, tree, alerts e estatísticas
agora consomem exclusivamente tokens `--figma-*`. O baseline do gate caiu de
204 para 175 ocorrências legadas fora dos arquivos de tokens.
