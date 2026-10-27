# Gold Standard Jurix v1 — adjudicação por IA

Em 18/10/2026, o responsável pelo projeto determinou: “Eu quero consolidar
como um gold standard.” O conjunto de 20 normas passa a ser o **gabarito
oficial interno do Jurix**, identificado por `jurix-pgm-gold-v1` e pelo
registro versionado
[`project-gold.v1.json`](../../benchmarks/corpus/municipal_natal/project-gold.v1.json).
A adoção permite usá-lo imediatamente como referência das avaliações do projeto.

## Conteúdo congelado e uso

São **20 normas distintas, 20 decisões, 41 recortes, 13 relações e 28 perguntas**,
com três famílias de relações: CTM, urbanismo e PPA. O registro aponta para o
pacote já conferido em
[`ai-adjudicated-20261018-v1/`](../../benchmarks/corpus/municipal_natal/ai-adjudicated-20261018-v1/README.md).
Os índices SHA-256 fixam os arquivos adotados. A decisão não altera seus
textos, rótulos, versões documentais, partições ou resultados de validação.

Usar os seguintes arquivos como gabarito:

- `reference/queries.ai.jsonl`: perguntas, fontes e citações esperadas,
  versões, pontos de resposta e comportamento de abstenção.
- `reference/annotations.ai-adjudicated.jsonl`: dispositivos e relações
  documentais adotadas; `adjudications.ai.jsonl` registra cada decisão.
- `reference/texts/`, `source-origins.jsonl` e `supporting-evidence.jsonl`:
  evidências e correspondência com as fontes.
- `reference/splits.json`: partições por família de relações, mantidas em
  qualquer comparação entre baseline, grafo e grafo temporal.

As predições e medições ficam em arquivos de execução próprios, com o ID do
gold, hash do registro, hash do corpus/modelo, parâmetros e data. Nomear os
resultados **“Avaliação contra o Gold Standard Jurix v1, adjudicado por IA”**.
Qualquer percentual descreve concordância com este gabarito, no escopo anotado.
Não há percentual de desempenho medido nesta adoção.

As 28 perguntas permanecem no conjunto, incluindo contraprovas e questões
cuja resposta exige abstenção. O estado não resolvido de um alvo ou data faz
parte do gabarito. Não excluir um caso por falha de recuperação ou resposta.
Na métrica de recuperação, reportar explicitamente os casos sem fonte esperada
e seu denominador; na abstenção, manter todas as perguntas aplicáveis.

A anotação é focal: não usar os recortes como gold de segmentação exaustiva
de PDFs inteiros. Um evento encontrado fora do recorte precisa de conferência;
sua ausência na anotação não o torna automaticamente falso positivo. Os pontos
de resposta exigem comparação semântica e conferência da evidência, não
igualdade literal de strings.

## Proveniência e relação com o protocolo anterior

O registro declara `review_kind=ai`, `independent_review=false` e
`human_approved=false`. O responsável adotou o conjunto; a análise documental
e a adjudicação foram feitas por IA na mesma sessão. A amostra é intencional,
retrospectiva e parcialmente exposta ao desenvolvimento.

Esta decisão amplia o adendo
[`AI_CONSOLIDATION_ACCEPTANCE_2026-10-18.md`](AI_CONSOLIDATION_ACCEPTANCE_2026-10-18.md)
para permitir a designação **gold standard interno do projeto** para as 20
normas, em substituição à restrição anterior dessa designação no piloto.
A autoria e os limites continuam registrados. Não há necessidade de esperar
revisão humana para usar este gabarito nas avaliações técnicas autorizadas.

O protocolo
[`PGM_GOLD_ADJUDICATION.md`](PGM_GOLD_ADJUDICATION.md)
continua sendo o procedimento de revisão humana independente para eventual
estudo científico. Esse documento histórico e seus hashes foram preservados.
Os resultados têm dois estados explícitos: `project_gold_ready=true` após
validação do pacote e `scientific_human_gold_ready=false`. Nenhuma pessoa foi
registrada como revisora jurídica nem houve estudo com procuradores.

A adoção cobre os dispositivos selecionados. Os conflitos § 3º/§ 5º da LC 55,
os alvos não resolvidos da LC 258 e as datas sem prova ficam registrados.
O gold não determina redação integral atualmente vigente de todas as normas.
A designação também não promove documentos nem preenche revisões no banco.

## Validação reproduzível

Na raiz do checkout, executar:

```powershell
uv run --with jsonschema python scripts/pgm_project_gold.py
```

O comando resolve o registro adotado, confere os dois índices fixados, verifica
os 37 arquivos do pacote e executa a validação existente de identidades,
recortes, relações, citações, decisões e partições. Não depende de servidor
web, Docker, Ollama ou acesso ao banco. `--output CAMINHO_NOVO.json` registra
uma execução e recusa substituir um arquivo existente.

Para conferir novamente também os PDFs e textos completos no cache local:

```powershell
uv run --with jsonschema python scripts/pgm_project_gold.py --inputs L:/temp/jurix-ai-adjudication-20261018-v1/frozen-inputs
```

Sem `--inputs`, o comando confere os arquivos distribuídos no repositório.
O relatório distingue explicitamente PDFs e textos originais verificados nesta
execução; não reutiliza contagens de uma execução anterior como se fossem novas.

A execução desta adoção está em
[`PROJECT_GOLD_VALIDATION.v1.json`](../../benchmarks/corpus/municipal_natal/PROJECT_GOLD_VALIDATION.v1.json):
`valid=true`, `project_gold_ready=true`, zero erros, 37 arquivos do pacote,
20 PDFs e 20 textos completos conferidos. Os testes focados dos contratos
municipais, da referência documental e da adoção passaram: **27 passed**.

## Correções futuras

Uma correção de rótulo, nova fonte ou mudança de amostra exige uma nova versão
com motivo, evidência, impacto nas perguntas e hashes novos. Manter a v1 e
suas medições para comparação. Nunca ajustar silenciosamente o gold depois
de observar as respostas do Jurix. Uma revisão independente futura recebe
autoria e decisões próprias vinculadas à versão que efetivamente conferiu.
