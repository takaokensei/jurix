# Auditoria visual das rotas principais

Auditoria realizada no ambiente local com viewport desktop de 1440×900 e
mobile de 390×844.

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
