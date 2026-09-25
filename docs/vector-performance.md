# Performance vetorial

## Objetivo

Evitar que a busca `<=>` cresça para full scan silencioso conforme o corpus
cresce.

## Procedimento

1. `python manage.py ensure_vector_index`;
2. se ausente, executar `python manage.py ensure_vector_index --create` em janela
   de manutenção;
3. usar `scripts/vector_search_benchmark.py` contra staging com o mesmo corpus
   e modelo de embeddings;
4. guardar o EXPLAIN ANALYZE em um artefato de release.

## Critério

O limiar padrão é um ponto de partida operacional. Deve ser recalibrado para o
hardware real. A função do gate é impedir regressão, não afirmar desempenho
universal.
