# Protocolo de avaliação do grafo normativo municipal (v2)

## Unidade, estratos e limites

- A unidade documental é `document_key`; a unidade jurídica é `norma_key`. Uma norma com publicação, retificação e anexo conta como uma norma, mas como documentos distintos.
- O piloto técnico pretende inspecionar 40 documentos. Um recorte entre 30 e 50 pode ser usado se o relatório registrar composição, motivo de inclusão/exclusão e cobertura por tipo de documento. Isso **não** representa 40 normas adjudicadas.
- O conjunto científico de referência continua exigindo pelo menos 20 normas distintas com anotação e adjudicação humanas completas. A meta maior de 150–200 normas permanece separada e não é substituída pelo piloto documental.
- Estratificar por tipo do ato, período, documento nativo/OCR/misto, retificação/republicação/anexo e densidade de relações. Registrar `norma_key` e `document_key` anonimizados/estáveis, nunca contar arquivos duplicados como amostras jurídicas independentes.

## Rastreabilidade da anotação

Cada anotação v2 fixa `document_key`, SHA-256 do texto, `text_version`, extractor e escopo temporal. Cada span guarda offsets half-open `[start,end)` e quote literal; cada evento aponta para span de origem, chave tipada do alvo, ação, resolução e base/data de efeito. O validador deve provar `quote == texto[start:end]` e rejeitar texto, documento ou revisão divergente.

`SUBSTITUI` é uma ação distinta; não reinterpretar retroativamente rótulos de schemas v1. Similaridade temática não é relação normativa. Referência sem alvo confirmado permanece `unresolved`/`pending_review`.

## Separação de gates

1. **Estrutural:** JSON/schema, chaves, hashes, containment, offsets e vínculos coerentes. Saída inválida: exit 2.
2. **Revisão humana:** somente `review_kind=human`, identidade de revisor preenchida, timestamp e estado adjudicado/aprovado contam. Registros sintéticos/teste nunca incrementam a contagem. Estrutura válida mas gate humano insuficiente: exit 3.
3. **Científico/publicação:** exige o mínimo de normas distintas revisadas, condições de uso resolvidas e relatório de amostragem. Gate satisfeito: exit 0.

Não usar resultado sintético como gold standard, não inferir licença a partir de acesso público, e não divulgar trechos de documento com condição de uso desconhecida. Mudança de hash/extractor/text version exige nova revisão da fonte e invalida adjudicações dependentes até revisão explícita.

## Relatório mínimo

Registrar versão do protocolo/schema, hash do manifesto, counts de documentos e normas distintos, distribuição dos estratos, revisões por estado, conflitos, documentos OCR pendentes, relações resolvidas/pendentes e motivos de exclusão. Separar métrica técnica de cobertura documental, revisão jurídica e qualidade científica. Não reportar precisão/recall sem conjunto humano adjudicado.
