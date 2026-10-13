# Protocolo de avaliação do grafo normativo municipal (v2)

## Unidade, estratos e limites

- A unidade documental é `document_key`; a unidade jurídica é `norma_key`. Uma norma com publicação, retificação e anexo conta como uma norma, mas como documentos distintos.
- O piloto técnico pretende inspecionar 40 documentos. Um recorte entre 30 e 50 pode ser usado se o relatório registrar composição, motivo de inclusão/exclusão e cobertura por tipo de documento. Isso **não** representa 40 normas adjudicadas.
- O conjunto científico de referência continua exigindo pelo menos 20 normas distintas com anotação e adjudicação humanas completas. A meta maior de 150–200 normas permanece separada e não é substituída pelo piloto documental.
- Estratificar por tipo do ato, período, documento nativo/OCR/misto, retificação/republicação/anexo e densidade de relações. Registrar `norma_key` e `document_key` anonimizados/estáveis, nunca contar arquivos duplicados como amostras jurídicas independentes.

## Rastreabilidade da anotação

Cada anotação v2 fixa `document_key`, SHA-256 do texto, `text_version`, extractor e escopo temporal. Cada span guarda offsets half-open `[start,end)` e quote literal; cada evento aponta para span de origem, chave tipada do alvo, ação, resolução e base/data de efeito. O validador deve provar `quote == texto[start:end]` e rejeitar texto, documento ou revisão divergente.

`SUBSTITUI` é uma ação distinta; não reinterpretar retroativamente rótulos de schemas v1. Similaridade temática não é relação normativa. Referência sem alvo confirmado permanece `unresolved`/`pending_review`.

## Manifesto de seleção de revisão

- O comando `build_pilot_manifest --schema-version 1` mantém o JSONL legado de candidatas a normas.
- `--schema-version 2` é opt-in e acrescenta registros `document_review_candidate` identificados por `document_key`, hash do documento, índice/entrada do arquivo, tipo do ato, faixa temporal, papel e status de extração/revisão. O primeiro registro informa contagens e estratos; candidatos nunca são aprovados pelo manifesto.
- A seleção documental é determinística: round-robin entre estratos disponíveis e ordenação estável por hash, entrada e `document_key`. `--document-sample-size` aceita 1–50; para o piloto planejado usar 40 e registrar o número efetivamente disponível. O recorte QA não é gold e não substitui 20 normas distintas adjudicadas por humanos.
- Arquivos sintéticos são excluídos da amostra documental e todas as linhas carregam `gold_eligible: false` até uma revisão humana posterior e o gate científico. Não incluir texto extraído, citações ou dados de revisão humana no manifesto de seleção.
- O caminho de saída deve ser novo; o comando recusa sobrescrever. No ambiente QA, saída só pode ficar sob `JURIX_QA_ROOT`.

## Separação de gates

1. **Estrutural:** JSON/schema, chaves, hashes, containment, offsets e vínculos coerentes. Saída inválida: exit 2.
2. **Revisão humana:** somente `review_kind=human`, identidade de revisor preenchida, timestamp e estado adjudicado/aprovado contam. Registros sintéticos/teste nunca incrementam a contagem. Estrutura válida mas gate humano insuficiente: exit 3.
3. **Científico/publicação:** exige o mínimo de normas distintas revisadas, condições de uso resolvidas e relatório de amostragem. Gate satisfeito: exit 0.

O avaliador exclui de todas as métricas qualquer caso sem `review_kind=human`, estado `adjudicated`/`approved`, `reviewer_id` não vazio e `reviewed_at` ISO 8601 com fuso horário. O limiar padrão da avaliação de grafo é 20 normas distintas e três cadeias de relação adjudicadas. A saída `evaluated` significa apenas que essa amostra mínima de gold humano foi alcançada; não substitui a verificação independente de licença/condição de uso, amostragem, divisão sem vazamento ou aprovação para publicação. Os casos excluídos são contabilizados e não podem contribuir como falso positivo ou falso negativo.

O relatório do experimento RAG só calcula métricas sobre esses casos adjudicados, exige anotações de gold idênticas entre braços e estima diferenças pareadas por bootstrap percentil agrupado em `norma_key`. Com menos de 20 normas independentes, o intervalo de confiança fica explicitamente `not_estimated_small_n`. Para habilitar `scientific_claim_allowed`, passe também `--sampling-report <arquivo.json>`: o avaliador calcula o SHA-256 dos bytes do arquivo e exige que corresponda a todas as linhas humanas, que as unidades `(norma_key, document_key, condition_of_use)` e cadeias declaradas coincidam exatamente com as adjudicadas e que o relatório tenha método, seed, estratos e `created_at` com fuso. O esquema mínimo é `schema_version: 1`, `selection_method`, `seed`, `strata`, `created_at`, `units: [{norma_key, document_key, condition_of_use}]` e `relation_chain_keys`. Hash isolado, sem esse arquivo correspondente, nunca habilita alegação científica. A validação confirma integridade e consistência, mas não autentica identidade real do revisor, aprovação institucional nem veracidade da seleção; isso ainda exige auditoria humana independente.

Não usar resultado sintético como gold standard, não inferir licença a partir de acesso público, e não divulgar trechos de documento com condição de uso desconhecida. Mudança de hash/extractor/text version exige nova revisão da fonte e invalida adjudicações dependentes até revisão explícita.

## Relatório mínimo

Registrar versão do protocolo/schema, hash do manifesto, counts de documentos e normas distintos, distribuição dos estratos, revisões por estado, conflitos, documentos OCR pendentes, relações resolvidas/pendentes e motivos de exclusão. Separar métrica técnica de cobertura documental, revisão jurídica e qualidade científica. Não reportar precisão/recall sem conjunto humano adjudicado.
