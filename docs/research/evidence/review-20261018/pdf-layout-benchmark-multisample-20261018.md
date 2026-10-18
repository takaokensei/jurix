# QA: comparação de estrutura em três PDFs reais do acervo

Data: 18/10/2026. Ambiente: imagem web do Compose `jurix-normative-qa`, banco/armazenamento QA isolados. Escopo: comparação somente de leitura entre os candidatos tabulares já persistidos, texto extraído atual, Poppler `pdftotext -layout`/`pdftohtml` e células serializadas localmente em HTML semântico/Markdown.

## Amostra e resultados

O benchmark verificou o SHA-256 de cada PDF e recusou documentos que não estivessem pendentes, sem extração aceita e sem `Norma` vinculada. Os três documentos continuaram `pending`; nenhuma extração, identidade, relação ou projeção foi gravada.

| Documento | Páginas | Candidatos tabulares avaliados | Células candidatas não vazias | Correspondências por substring em `pdftotext -layout` | Tamanho do texto salvo / layout | Tabelas semânticas no HTML do Poppler |
|---|---:|---:|---:|---:|---:|---:|
| Lei Ordinária 7.425/2022 | 17 | 12 | 56 | 43/56 (76,8%) | 30.900 / 34.729 caracteres | 0 |
| Lei Complementar 175/2018 | 7 | 12 | 203 | 160/203 (78,8%) | 17.391 / 23.072 caracteres | 0 |
| Lei Complementar 257/2024 | 17 | 12 | 334 | 264/334 (79,0%) | 36.077 / 52.474 caracteres | 0 |

No agregado, 467 de 593 células candidatas (78,8%) apareceram como substring normalizada no texto do Poppler. Os candidatos foram serializados em tabelas HTML com `<thead>/<th>` e `<tbody>/<td>`, além de linhas Markdown. IDs QA usados, respectivamente: `b01eaa84-a0c7-48d2-a3a5-c409e755f0ff`, `f8ceabf4-65dd-4a6e-bac4-1487b31a4017` e `f5502545-9dfc-405d-883d-32bc131189b2`.

## Reprodução

Executar cada amostra no container QA que contém o checkout atual:

```sh
docker exec -e JURIX_QA_ONLY=1 \
  -e DJANGO_SETTINGS_MODULE=config.settings_normative_container_qa \
  -e JURIX_QA_ROOT=/app/data/normative-qa \
  jurix-normative-qa-web-1 \
  python scripts/benchmark_pdf_layout_qa.py \
  --document-public-id b01eaa84-a0c7-48d2-a3a5-c409e755f0ff --timeout 60
```

Repetir com os outros dois IDs listados acima. O script lê as extrações e PDFs QA e imprime JSON; não grava resultado em arquivo ou banco.

## Interpretação e limites

- A taxa mede somente a presença de cada string candidata em um texto normalizado; não confere posição, ordem, cabeçalho, célula mesclada, precisão OCR, relação linha-coluna, seleção do trecho operativo ou validade jurídica. A contagem de candidatos é o conjunto persistido pela heurística, não um inventário de todas as tabelas do PDF.
- `pdftohtml` produziu HTML posicionado, mas nenhum elemento `<table>` semântico nos três PDFs. Isso não demonstra que o HTML seja inútil para inspeção visual; demonstra apenas que essa execução não fornece tabelas estruturadas para ingestão.
- As correspondências parciais e a diferença entre contagens de caracteres reforçam que nenhum destes formatos deve substituir automaticamente o texto armazenado. Os candidatos existentes não foram aprovados, corrigidos, vinculados a normas ou promovidos.
- São três amostras selecionadas por disponibilidade de candidatos tabulares, não uma amostra aleatória ou representativa do acervo. O resultado não é uma métrica de acurácia do corpus nem justifica trocar o extrator.
