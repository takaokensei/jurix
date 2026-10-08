# Smoke de produto em browser — 05/10/2026

- Servidor: `http://127.0.0.1:8019`, Django QA isolado.
- Dataset de interface: `synthetic_not_gold`, no PostgreSQL QA; não é gold
  jurídico e não altera os 40 PDFs históricos.
- Smoke `tests/js/normative-product-smoke.mjs`: **36 verificações de rota em
  cinco larguras (320, 360, 768, 1280 e 1920 px), zero falhas**, sem erros de
  JavaScript; confirmou também identidade LO/LC, projeção temporal D−1/D,
  abstinência sem documento-base, relações agrupadas, retry de erro 503,
  sidebar persistente e alvo de toque de 44 px em 320 px.
- Mapfile de entrada regenerado com `seed_normative_qa` em staging QA. Uma
  segunda execução gerou exatamente o mesmo SHA-256 do mapfile (**idempotente**).
- Os nove PNGs deste diretório foram inspecionados visualmente por amostragem:
  relação revisada desktop, detalhe mobile 320 px e abstinência de histórico.
  O screenshot mobile é uma página longa; a imagem de contato foi reduzida para
  caber na visualização, então não serve para medir tamanho tipográfico real.
- Limites: páginas e relações usam fixtures sintéticas; isto não testa zoom real
  de 200%, tecnologia assistiva, contraste integral nem valida as leis históricas.
