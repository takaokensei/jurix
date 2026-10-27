# Jurix 2.0 — Fases 2 e 3: avaliação e temporalidade

## Fase 2

O repositório agora possui um contrato para comparar eventos extraídos com
um piloto revisado por humanos. O avaliador calcula Precision, Recall e F1
por classe e macro-F1 para `REVOGA`, `ALTERA`, `ADICIONA`, `SUBSTITUI`,
`REGULAMENTA` e `REFERENCIA`.

Exemplo de caso:

```json
{"case_id":"pilot-001","norma_id":123,"gold_actions":["ALTERA","REFERENCIA"]}
```

Execução:

```bash
python manage.py evaluate_event_pilot benchmarks/corpus/municipal_natal/pilot-events.example.jsonl --output artifacts/event-eval.json
```

O gold standard deve ser congelado por versão do corpus e revisado por
especialista. O arquivo `.example.jsonl` é apenas contrato e não representa
um resultado jurídico.

## Fase 3

O RAG passa a aceitar os recortes:

- `as_of=AAAA-MM-DD`;
- `published_from=AAAA-MM-DD`;
- `published_to=AAAA-MM-DD`.

O recorte temporal entra no fingerprint do cache para impedir que uma resposta
histórica seja servida para uma consulta do presente.

A linha do tempo de uma norma fica disponível em:

```text
GET /api/v1/normas/<id>/timeline/
GET /api/v1/normas/<id>/timeline/?as_of=2024-12-31
```

O endpoint de sinais em `/conflicts/` é deliberadamente advisory-only. Ele
procura problemas de integridade da extração, duplicidade e sequências que
merecem revisão; não determina que existe conflito jurídico.

### Limitações explicitadas

O modelo atual não possui um campo jurídico próprio para a data de um evento
de alteração. Quando uma linha do tempo precisa datar um evento, usa a data de
publicação da norma-fonte, e o código marca a natureza dessa inferência na
documentação. Ausência de data não é tratada como prova de vigência.
