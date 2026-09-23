# Operação pós-hardening do Jurix

Este conjunto de mudanças reduz três classes de falha que apareciam juntas no ambiente de desenvolvimento: histórico anônimo perdido em refresh, retrieval excessivamente rígido e ingestão SAPL que sobrecarrega a fila.

## Normalizar URLs já existentes

Depois de aplicar o patch, registros antigos com `/norma/normajuridica/<id>/` deixam de ser enviados pela API porque o serializer corrige a URL em runtime. Para também corrigir o banco:

```bash
python manage.py normalize_sapl_urls --dry-run
python manage.py normalize_sapl_urls
```

## Diagnosticar SAPL antes de uma carga grande

```bash
python manage.py diagnose_sapl --limit 10 --max-pages 4
```

O comando não grava dados. Ele mostra se o endpoint está devolvendo páginas diferentes, se a paginação entrou em repetição e se a API está retornando uma coleção válida.

## Ingestão em lotes limitados

Para uma carga controlada:

```bash
python manage.py ingest_sapl_bounded --max-normas 1000 --batch-size 25
```

A ideia é evitar que a task antiga coloque centenas de mensagens no Redis de uma vez. Em produção, prefira manter workers separados para I/O/OCR/embedding e observar CPU, memória, Redis e o número de jobs pendentes.

## Índice vetorial

Em PostgreSQL + pgvector:

```bash
python manage.py ensure_vector_index
```

O índice criado é HNSW com `vector_cosine_ops`. O comando não faz nada em SQLite.

## Estado jurídico

Uma consolidação com eventos não resolvidos passa a ficar em estado de revisão/falha, e não em `consolidated`. Isso é deliberadamente fail-closed. A saída parcial continua disponível para diagnóstico/auditoria, mas não deve ser tratada pelo produto como consolidação definitiva.

## Histórico anônimo

Visitantes não autenticados usam histórico local limitado e versionado no navegador. O servidor continua sem criar `ChatSession` para guest, portanto a separação de dados permanece explícita. Ao autenticar, o histórico passa a ser persistido no banco normalmente.
