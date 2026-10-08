# R15 — medição de streaming e drawer

Execução local no servidor QA `127.0.0.1:8017`, com PDFs históricos reais do acervo em `archive-qa`, banco PostgreSQL QA isolado e provider Ollama local (`llama3:latest`). Nenhum documento, estado de revisão ou banco de produto foi alterado.

## Evidência principal

- `stream-with-drawer-open.png`: drawer aberto durante a geração e ainda aberto depois do evento `done`.
- `sources-drawer-800-settled.png`: drawer em viewport 800×900, após aguardar 500 ms a transição de entrada; bounds x=320–800 (480 px), sem overflow horizontal no documento.
- `sources-drawer-1440.png`: drawer em viewport 1440×1024; bounds x=960–1440 (480 px), sem overflow horizontal.

## Capturas exploratórias

`assistant-answer.png`, `sources-drawer.png` e `sources-drawer-800.png` foram feitas em viewport padrão 800×600 ou durante a transição do drawer. Não as use como evidência de geometria final. O deslocamento temporário observado antes da transição terminar não persistiu na medição após 500 ms.
