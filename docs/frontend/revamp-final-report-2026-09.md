# Relatório final do revamp do Jurix — 2026-09-27

## Resultado executivo

O primeiro ciclo do revamp elevou o produto para um shell jurídico escuro,
responsivo e orientado a evidências, mantendo Django + templates + JavaScript
modular. O `jurix-figma.css` é a referência visual do produto; o shell legado
foi migrado para a mesma estrutura e os tokens hexadecimais fora da baseline
canônica passaram a ser verificados por gate.

## Backlog A — consistência estrutural

Concluído e verificado:

- `norma_list`, `norma_detail`, `norma_compare` e `norma_tree` usam
  `legislation/workspace/base.html`.
- O topbar compartilhado está em
  `legislation/workspace/_topbar.html` e é usado pelo workspace e pelo
  chatbot, preservando os hooks de `Ctrl+K` e sidebar.
- As rotas principais foram capturadas em desktop e mobile real:
  `/assistente/`, `/normas/`, `/pesquisa/`, `/colecoes/`, `/historico/`,
  `/configuracoes/`, `/normas/3/`, `/normas/3/compare/` e
  `/normas/3/tree/`.
- Chromium em `390×844` confirmou `scrollWidth = 390px` em todas as rotas
  auditadas, sem overflow horizontal.
- Sidebar mobile, command palette, foco, `Escape` e retorno de foco foram
  exercitados interativamente.

## Backlog B — funcionalidades entregues

Mais de cinco itens foram implementados e verificados visualmente:

1. Links oficiais para o SAPL em cards, detalhe e fontes do assistente.
2. Deep links para dispositivos normativos.
3. Diff visual de versões com linhas, números e marcadores de alteração.
4. Exportação de norma para PDF formatado.
5. Destaque de termos em resultados de pesquisa.
6. Índice compacto de dispositivos em normas longas.
7. Persistência de conversas, F5 e paginação histórica com retenção de scroll.
8. Fontes deferidas até o fim do streaming, com drawer e foco acessível.

O compartilhamento público de conversas não foi implementado neste ciclo: ele
exige uma decisão explícita de modelo de autorização, retenção e exposição de
dados antes de ser seguro em produção.

## Backlog C — polimento e resiliência

Concluído neste ciclo:

- Auditoria parcial de contraste dos tokens principais, documentada em
  `docs/current-status.md`, sem alegar conformidade WCAG global.
- Estados de erro, retry, offline e interrupção de streaming verificados.
- Banner offline corrigido para não sobrepor breadcrumb, banner anônimo ou
  conteúdo do assistente.
- Estados de fontes e carregamento do chatbot cobertos pelos testes reais.
- Responsividade real das rotas principais verificada com Puppeteer/Chromium.

Pendente de auditoria formal completa:

- Combinações de contraste de todos os componentes e temas alternativos.
- Estados de erro que dependem de serviços externos reais, como SAPL fora do
  ar e Ollama indisponível em ambiente de produção.

## Evidência automatizada final

- Testes Python: `656 passed, 2 skipped`.
- Testes JavaScript: `65 passed`.
- Ruff: passou.
- `scripts/check_design_tokens.py`: passou, zero ocorrências legadas na
  baseline.
- `scripts/architecture_budget_v2.py`: `passed: true`.
- `git diff --check`: passou.

## Decisões e itens descartados

- Não foi introduzido React: os fluxos existentes são atendidos por Django e
  JavaScript modular, evitando bundle e risco de migração desnecessários.
- A atualização automática do corpus SAPL não foi implementada, conforme o
  escopo definido para este ciclo.
- A auditoria mobile foi feita com runner Chromium real depois que a API de
  screenshot integrada se mostrou incapaz de controlar viewport.

## Riscos remanescentes

- O benchmark jurídico continua dependente de dados e aprovação humana.
- A atualização completa do corpus SAPL permanece uma decisão operacional
  futura.
- Uma auditoria de acessibilidade assistiva completa ainda requer leitor de
  tela e validação humana especializada.
