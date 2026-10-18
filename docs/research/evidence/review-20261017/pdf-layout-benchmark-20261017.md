# QA: comparação de extração tabular em PDF real

Data: 17/10/2026. Escopo: uma amostra do acervo PDF local, somente leitura, no banco/armazenamento QA. Não é adjudicação jurídica nem avaliação estatística do corpus.

## Amostra e método

- Registro documental QA: `0d04a476-595e-45a6-86c5-67d5c6d48218`, arquivo `Decreto_20120328_9666_.pdf`.
- Extração candidata existente: ID `7510`, uma página, estado técnico `complete`, texto legal com 2.121 caracteres. O documento continua `pending`, sem `Norma` vinculada e sem extração aceita.
- O script verifica a raiz de armazenamento e o SHA-256 do PDF antes de comparar. Em seguida lê a extração atualmente armazenada, roda `pdftotext -layout` e `pdftohtml` do Poppler, compara as células dos candidatos de tabela por texto normalizado e verifica serialização local em Markdown/HTML semântico.
- Comando executado dentro do container QA:

```sh
docker compose -p jurix-normative-qa -f docker-compose.audit.yml exec -T \
  -e JURIX_QA_ONLY=1 \
  -e DJANGO_SETTINGS_MODULE=config.settings_normative_container_qa \
  -e JURIX_QA_ROOT=/app/data/normative-qa web \
  python scripts/benchmark_pdf_layout_qa.py \
  --document-public-id 0d04a476-595e-45a6-86c5-67d5c6d48218 --timeout 60
```

## Resultado observado

- O extrator atual registrou **2 candidatos de tabela**, cada qual com 3 linhas e até 5 colunas. Um tem 1 célula multilinha; o outro, 5. Isso é evidência de estrutura candidata, não de conteúdo revisado.
- Para os 12 valores textuais não vazios de cada tabela, a correspondência por substring normalizada foi: primeira tabela **11/12** nos três textos comparados; segunda **7/12** nos três. O comparador não avalia posição visual, células mescladas, cabeçalhos corretos nem semântica jurídica.
- `pdftotext -layout` retornou 3.075 caracteres. `pdftohtml` retornou 14.209 caracteres, mas **0 `<table>`, 0 linhas e 0 células semânticas**: gerar HTML, por si só, não preservou a tabela como dados tabulares.
- A serialização dos candidatos já detectados produziu por tabela HTML com `<thead>/<th>` e `<tbody>/<td>` e Markdown com linha separadora. O teste verifica a estrutura serializada, não a fidelidade do PDF.

## Decisão e limites

O resultado justifica continuar a comparação estruturada em outras amostras; **não** justifica substituir o pipeline atual. A segunda tabela tem cinco valores candidatos que não foram encontrados como substring nas três saídas. A identificação desses valores, a posição das células e a distinção entre dispositivo operativo e anexo exigem inspeção humana do PDF; esta rodada não a fez. Não se conclui que HTML/Markdown estejam corretos, nem que haja cobertura completa.

O benchmark só aceita explicitamente `config.settings_normative_qa`/`config.settings_normative_container_qa`, banco `jurix_audit`, armazenamento QA isolado, documento de origem archive pendente, sem vínculo e sem extração aceita. Nesta execução não criou arquivos, extrações, vínculos ou decisões no banco; não consultou o banco de produto.
