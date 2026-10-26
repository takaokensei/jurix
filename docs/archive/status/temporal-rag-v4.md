# Runbook — RAG temporal e avaliação de eventos

## Verificar histórico de uma norma

```bash
python manage.py export_norma_timeline 123 --output artifacts/norma-123-timeline.json
curl "http://localhost:8000/api/v1/normas/123/timeline/"
```

## Procurar sinais de integridade

```bash
python manage.py detect_norma_conflicts 123 --json
curl "http://localhost:8000/api/v1/normas/123/conflicts/"
```

## Executar avaliação do parser

```bash
python manage.py evaluate_event_pilot benchmarks/corpus/municipal_natal/pilot-events.example.jsonl
```

## Consulta histórica

```text
GET /api/v1/search/semantic/?query=zoneamento&as_of=2024-12-31&k=10
```

Use `as_of` quando a pergunta fizer referência explícita a um ponto no tempo.
Não interprete `temporal_status=vigente` como decisão jurídica quando o
corpus possuir lacunas de data.
