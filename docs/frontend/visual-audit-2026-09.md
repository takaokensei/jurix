# Auditoria visual das rotas principais

Auditoria realizada no ambiente local com viewport desktop de 1440×900.
Uma tentativa de viewport mobile de 390×844 foi feita, mas a API do navegador
automatizado manteve o layout desktop; por isso ela não é considerada evidência
de responsividade real.

## Rotas verificadas

- `/assistente/`: shell do chatbot, histórico, streaming finalizado, fontes e
  composer.
- `/pesquisa/`: formulário, filtros, resultados e destaque de termos.
- `/normas/`: biblioteca, filtros, paginação e cards com SAPL.
- `/normas/3/`: detalhe, vigência, dispositivos, timeline e SAPL.
- `/normas/3/compare/`: comparação de versões e leitura monoespaçada.
- `/normas/3/tree/`: árvore de dispositivos.
- `/colecoes/`: estado vazio e navegação.
- `/historico/`: lista de conversas locais.
- `/configuracoes/`: controles de modelo, tema, densidade e formulário.

## Correções realizadas durante a auditoria

- As rotas de norma passaram a compartilhar sidebar, breadcrumb e busca rápida.
- A comparação deixou de exibir trechos com fundo branco sobre o tema escuro.
- O cabeçalho do workspace em 390px passou a truncar breadcrumb e busca sem
  sobreposição horizontal.
- A pesquisa passou a destacar termos encontrados com marcação segura.

## Observações pendentes

- A lista de conversas locais pode conter títulos repetidos quando o navegador
  possui sessões de testes históricas; isso é dado persistido, não duplicação
  de elementos no mesmo render.
- O chatbot usa um shell próprio de conversa por causa do composer e do
  streaming, mas mantém a mesma navegação e busca rápida do workspace.
## Auditoria estrutural atualizada — 2026-09-27

### Templates e shell

`norma_list.html`, `norma_detail.html`, `norma_compare.html` e
`norma_tree.html`, além de `workspace/search.html`, `collections.html`,
`collection_detail.html`, `history.html` e `settings.html`, estendem
`legislation/workspace/base.html`. Isso foi confirmado por inspeção dos
templates e por capturas reais de `/normas/`, `/normas/3/`,
`/normas/3/compare/`, `/normas/3/tree/`, `/pesquisa/`, `/colecoes/`,
`/historico/` e `/configuracoes/`.

O assistente (`chatbot.html`) permanece um shell especializado porque sua
área de conversa, composer e streaming têm estrutura própria. Ele reproduz a
mesma navegação principal, busca rápida, sidebar e tokens `jurix-figma.css`,
mas não compartilha literalmente o mesmo HTML de topbar do workspace. Essa é
a pendência estrutural restante do Backlog A; a migração deve ser feita por
extração de parciais compartilhados, preservando os hooks JavaScript do chat.

### Evidência visual

- `/assistente/`: sidebar, histórico persistente, composer, resposta e fontes.
- `/normas/`: shell canônico, filtros, cards e links SAPL.
- `/normas/3/`: detalhe, timeline, deep links, citação e exportação.
- `/normas/3/compare/`: comparação em shell canônico e contraste legível.
- `/pesquisa/?q=PHAN`: filtros e destaque de trecho.
- `/configuracoes/`: campos, chevron de select e persistência local.

As capturas de viewport móvel realizadas nesta sessão ficaram limitadas pela
API de viewport do navegador automatizado, que manteve o layout CSS de desktop
em uma imagem física estreita; portanto não são consideradas prova de
responsividade. Uma rodada com runner mobile real permanece necessária.
