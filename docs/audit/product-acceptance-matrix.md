# Matriz de aceite de runtime do produto

Execução do smoke runner em `http://127.0.0.1:8005` em 01/10/2026. Ele usou um
perfil de navegador temporário, não reutilizou nem alterou o histórico do usuário.

| Rota / fluxo | 320 | 360 | 768 | 1280 | 1920 | Resultado verificado |
| --- | --- | --- | --- | --- | --- | --- |
| `/assistente/` | passou | passou | passou | passou | passou | HTTP 200, `main`, sem overflow horizontal, sem exceção JS |
| `/normas/` | passou | passou | passou | passou | passou | HTTP 200, shell/sidebar comum, sem overflow horizontal |
| `/normas/3/` | passou | passou | passou | passou | passou | detalhe carregou como Lei nº 8206/2026; sem overflow |
| `/pesquisa/` | passou | passou | passou | passou | passou | HTTP 200, `main`, sem overflow horizontal |
| `/colecoes/` | passou | passou | passou | passou | passou | HTTP 200, `main`, sem overflow horizontal |
| `/historico/` | passou | passou | passou | passou | passou | HTTP 200, `main`, sem overflow horizontal |
| `/configuracoes/` | passou | passou | passou | passou | passou | HTTP 200, `main`, sem overflow horizontal |
| Sidebar recolhível em `/normas/` e `/configuracoes/` | — | — | — | passou | — | preferência persistiu entre rotas; 7 ícones presentes |

Comando: `node tests/js/product-runtime-smoke.mjs`. O runner coleta exceções JS,
status HTTP, presença de landmark `main`, largura do documento e preferência de
sidebar. Não mede transferência de bytes nem Web Vitals.

## Não executado / revisão manual necessária

- Login e permissões autenticadas, geração com Ollama, worker Celery/PostgreSQL
  antes da stack isolada e integração com SAPL: requerem fluxos/serviços dedicados.
- 200% de zoom real, contraste em todas as combinações, leitor de tela, toque em
  dispositivo e auditoria WCAG completa: não certificados por este smoke.
- Tema claro/escuro, reduced motion e teclado foram verificados em testes de
  navegador com fixtures, não nesta navegação runtime de todas as rotas.
- Estados de erro e streaming foram exercitados nas fixtures Puppeteer; o smoke
  runtime não enviou perguntas para não consumir recursos locais do Ollama.
- CLS/LCP/INP de campo e orçamento de bytes não foram medidos.

O resultado “passou” é somente um gate estrutural/visual inicial. Não equivale a
aprovação jurídica, conformidade WCAG AA, nem substitui revisão humana.
