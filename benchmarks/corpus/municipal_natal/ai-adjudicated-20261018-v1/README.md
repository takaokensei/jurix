# Referência documental de 20 normas — adjudicação por IA

Data: 18/10/2026. Esta entrega contém **20 normas distintas, 20 decisões de
adjudicação documental por IA, 41 recortes, 13 relações e 28 perguntas**.
Os rótulos provêm da leitura das fontes; não de respostas do RAG usadas como
gabarito. Há três famílias de relações: CTM, urbanismo e PPA.

O conjunto está pronto para desenvolvimento e avaliações técnicas com autoria
de IA explícita. Não possui dois anotadores humanos independentes, adjudicador
jurídico ou autorização institucional registrada. A amostra é intencional e
retrospectiva: os casos centrais já foram usados no desenvolvimento. Portanto,
o conjunto não satisfaz o gold humano científico de `PGM_GOLD_ADJUDICATION.md`
nem permite estimar acurácia jurídica no acervo inteiro. Essa limitação não
impede seu uso no piloto autorizado pelo responsável do projeto.

## Arquivos de trabalho

Usar **`reference/`**, a versão final validada. Os builds intermediários desta
etapa foram preservados em `L:/temp/jurix-ai-adjudication-20261018-v1/`.

- `reference/manifest.jsonl`: 20 identidades, hashes e proveniência dos PDFs.
- `reference/annotations.ai-adjudicated.jsonl`: rótulos finais documentais e
  a decisão de IA vinculada a cada norma e revisão textual.
- `reference/adjudications.ai.jsonl`: 20 decisões, com justificativa, citações,
  autoria, data e limites. `independent_review=false` em todas.
- `reference/candidate-decisions.jsonl`: origem e decisão sobre as propostas
  de relações previamente levantadas; divergências não foram apagadas.
- `reference/annotations.pending-human.jsonl`: os mesmos recortes e evidências
  na fila do contrato v2. As relações permanecem `pending_review` nessa fila;
  a resolução documental da IA está no arquivo adjudicado acima.
- `reference/texts/`: somente os textos legais selecionados. Não são as leis
  inteiras, nem uma segmentação exaustiva utilizável como gold de parser.
- `reference/source-origins.jsonl`: offsets `[start,end)` das fontes completas,
  mapas para os recortes, hashes originais, epígrafes e divergência de ementa.
- `reference/supporting-evidence.jsonl`: DOMs auxiliares e o Art. 34 da
  compilação SEMURB de 2019. Não contam como novas normas.
- `reference/queries.ai.jsonl`: 20 perguntas por norma e oito contraprovas,
  com fontes, versões, citações e abstenções esperadas.
- `reference/splits.json`: partições por família inteira, sem separar normas
  relacionadas entre treino/desenvolvimento, validação e teste.
- `reference/selection.json` e `SHA256SUMS.json`: seleção congelada e integridade.
- `VALIDATION.json`: resultado efetivamente executado, incluindo conferência
  dos 20 PDFs e textos originais disponíveis no cache local.

## Normas e escopos adjudicados

1. **n01 — Lei 3.882/1989:** Art. 20 na compilação municipal de 2024.
2. **n02 — LC 271/2025:** Art. 1º, cotejo específico do CTM, Art. 20; Art. 6º.
3. **n03 — LC 258/2024:** Arts. 259, 260, 262 e 266; sete referências de revogação.
4. **n04 — LC 55/2004:** Art. 34 da reprodução histórica e conflito posterior.
5. **n05 — LC 173/2017:** Arts. 2º e 3º; acréscimo dos §§ 3º e 4º do Art. 34.
6. **n06 — LC 185/2019:** Arts. 87 e 92; numeração conflitante com a compilação.
7. **n07 — LC 208/2022:** Art. 18, inclusive § 2º.
8. **n08 — LC 261/2025:** Arts. 118 e 120; alteração do § 2º acima.
9. **n09 — Lei 4.885/1997:** Arts. 1º e 8º; decreto agregado ao PDF excluído do alvo.
10. **n10 — LP 275/2009:** Art. 21; alvo parcial da LC 258, Art. 260, V.
11. **n11 — LP 562/2018:** Arts. 1º e 2º; divergência entre ementa e dispositivo.
12. **n12 — Lei 1.894/1969:** Arts. 1º e 4º; espécie divergente na cláusula de 2024.
13. **n13 — LC 141/2014:** Art. 1º e diferença entre epígrafe e filename.
14. **n14 — Lei 7.805/2025:** Arts. 1º, 3º e 6º; isenção e revogação genérica.
15. **n15 — Lei 7.806/2025:** Arts. 1º e 5º; data comemorativa e vigência.
16. **n16 — Lei 7.807/2025:** fragmento operativo do Art. 1º e Art. 2º; revisão do PPA.
17. **n17 — Lei 7.808/2025:** Arts. 1º e 6º; semana de exames de rotina.
18. **n18 — Lei 7.810/2025:** Arts. 1º–3º; regulamentação de 90 dias versus vigência.
19. **n19 — Lei 7.811/2025:** Arts. 1º e 4º; data do ato versus nome de arquivo.
20. **n20 — Lei 7.280/2021:** Arts. 1º, 10, 16 e 18 no DOM; PPA e efeitos temporais.

A família `urbanismo` agrupa conservadoramente todos os casos de obras,
revogações e Plano Diretor, inclusive quando uma relação é incerta. A família
`ctm` inclui a LC 141 como documento relacionado ao caso tributário. A família
`ppa` contém o ato-base e a revisão de 2025. As demais leis têm partições
determinísticas pelo seed declarado. Isso reduz vazamento interno ao pacote;
não desfaz a exposição prévia dos casos ao desenvolvimento.

## O que foi decidido e o que permanece aberto

- A LP 275 não foi rotulada como integralmente revogada: o alvo é só Art. 21.
- Os alvos I, II e VII da LC 258, Art. 260, continuam `unresolved`. A Lei 1.894
  tem identidade própria legível; a equivalência com a espécie citada não foi forçada.
- A LC 185, Art. 87, e a compilação de 2019 divergem em § 3º/§ 5º. A relação
  fica `pending_review`; a IA adjudicou que o conflito deve ser preservado.
- O rótulo preliminar que confundia o Art. 34 da LC 55 com Alvará de Construção
  foi rejeitado na releitura: o texto trata das etapas da Licença Ambiental.
  A rejeição e a citação estão em `candidate-decisions.jsonl`.
- A revogação genérica de disposições em contrário não gera alvo inventado.
- Um decreto agregado ao PDF da Lei 4.885 não foi incluído na revogação da lei.
- O prazo de regulamentação da Lei 7.810 não foi transformado em vacância.
- A publicação no DOM, a data do ato e os efeitos em 2022 do PPA são distintos.
- Valores/tabulações do PPA e geometria dos anexos urbanísticos não foram
  adjudicados. Há perguntas que exigem abstenção justamente por esse limite.
- Nenhum evento recebe data efetiva confirmada apenas por nome de arquivo,
  sessão, colofão conflitante ou ausência de notícia de modificação posterior.
- O conjunto não afirma vigência universal de nenhuma das 20 normas.

## Validar em outro checkout

A validação interna depende somente do repositório e de `jsonschema`, usado
em ambiente temporário pelo `uv`; nenhuma dependência do app foi alterada.

```powershell
uv run --with jsonschema python scripts/validate_pgm_ai_adjudicated.py --reference benchmarks/corpus/municipal_natal/ai-adjudicated-20261018-v1/reference
```

Para repetir também a verificação dos PDFs e textos completos desta máquina:

```powershell
uv run --with jsonschema python scripts/validate_pgm_ai_adjudicated.py --reference benchmarks/corpus/municipal_natal/ai-adjudicated-20261018-v1/reference --inputs L:/temp/jurix-ai-adjudication-20261018-v1/frozen-inputs
```

O segundo comando requer o cache externo. Os PDFs integrais e os Diários
Oficiais completos não foram copiados para o repositório. O primeiro comando
verifica schemas, hashes dos artefatos distribuídos, spans, relações, referências,
contagens, autoria e partições. Não equivale a nova inspeção dos PDFs.

Os scripts `export_pgm_ai_review_sources_qa.py`, `prepare_pgm_ai_adjudication.py`
e `build_pgm_ai_adjudicated.py` documentam a preparação. O exportador roda no
container QA com transação `READ ONLY` e não exporta predições do Jurix. O
rebuild exige o pacote documental anterior e as cópias públicas congeladas;
ele recusa substituir diretórios finais existentes.

## Usar na próxima avaliação

1. Congelar o digest `reference/SHA256SUMS.json` antes de coletar respostas.
2. Executar as mesmas 28 perguntas em cada braço e salvar predições separadas.
3. Avaliar os dispositivos selecionados e a resolução dos 13 eventos; não usar
   ausência de evento não anotado como falso positivo automático, pois a
   anotação é focal e não exaustiva.
4. Julgar a resposta com `expected_answer_points` e os limites, não por
   igualdade literal com uma frase modelo. Conferir citações e abstenções.
5. Informar resultados como avaliação técnica contra referência de IA,
   mantendo negativos e não solucionáveis no denominador.

Não foi executado nesta entrega um benchmark completo de geração Ollama ou
uma avaliação independente de acurácia jurídica. Não há resultado de
baseline/grafo/grafo temporal a relatar como se já tivesse sido medido.
O estado jurídico dos documentos e normas no banco não foi promovido por
esta geração de arquivos. A anotação focal de uma norma também não significa
que todos os seus artigos foram consolidados.
