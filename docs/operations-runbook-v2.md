# Runbook operacional v2

## Diagnóstico inicial

```bash
python manage.py check --deploy
python manage.py production_validation --strict
python manage.py audit_attachment_storage --verify-hash --fail-on-missing
python manage.py ensure_vector_index
```

## Criar índice

```bash
python manage.py ensure_vector_index --create
```

Faça isso em janela de manutenção quando o corpus for grande.

## Limpar anexos expirados

Primeiro:

```bash
python manage.py prune_attachment_storage --json
```

Depois, somente após revisar o resultado:

```bash
python manage.py prune_attachment_storage --execute --json
```

## Investigar RAG

Verificar, nesta ordem:

1. modelo de embedding;
2. resultados de retrieval;
3. status/vigência das normas;
4. contexto enviado ao modelo;
5. grounding report;
6. cache/fingerprint;
7. benchmark RAG.

## Rollback

A aplicação pode ser revertida sem remover objetos do storage. Mantenha banco e
storage em compatibilidade de leitura durante a janela de rollback.
