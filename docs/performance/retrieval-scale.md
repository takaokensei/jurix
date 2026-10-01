# Benchmark de escala de recuperação

`scripts/lexical_scale_benchmark.py` compara consultas sintéticas de pgvector HNSW,
PostgreSQL FTS e `pg_trgm`, com filtro comum de tipo/ano/vigência. O gerador é
determinístico por seed; vetores 768D representam cinco tópicos artificiais. A
verdade de relevância é somente o tópico sintético conhecido, nunca relevância
jurídica.

## Segurança e execução

O runner recusa qualquer URL fora de `127.0.0.1:55432/jurix_audit`, cria tabela
temporária, mede `EXPLAIN ANALYZE BUFFERS`, executa somente leituras depois do seed
e encerra com rollback. Não rode contra `jurix`, `test_jurix`, produção ou qualquer
base cujo nome não seja exatamente `jurix_audit`.

```powershell
$env:DATABASE_URL = 'postgresql://jurix_audit:<fixture>@127.0.0.1:55432/jurix_audit'
python scripts/lexical_scale_benchmark.py --rows 10000 --runs 30 --seed 20261001 --output .\artifacts\retrieval-scale-10k.json
```

Para 100 mil linhas, execute somente em janela aprovada: dimensão 768 e índices
HNSW/GIN podem consumir vários GB e elevar CPU/IO. Não executar enquanto outros
trabalhos competem por CPU/GPU se latência for usada para decisão de produto.

## Leitura dos resultados

Cada modalidade informa Recall@10 e MRR sobre IDs sintéticos, distribuição de
latência warm-cache (n, mediana, p95 amostral, min/máx), plano, blocos shared e
tempo de seed/construção de índice. p95 com n=30 é exploratório, não estimativa
estável de cauda. O relatório não mede cold cache, concorrência, custo de escrita
contínua, qualidade jurídica nem ganho sobre corpus real. Não alterar índice ou
ranking de produção com base somente neste fixture.

## Execução local de referência — 2026-10-01

Foi executada uma rodada com 10.000 registros sintéticos, vetores 768D, 5
consultas e 30 repetições por modo em Windows 11 (12 CPUs reportadas pelo host).
O seed levou 5,63 s e a criação de índices 3,40 s. As medianas por consulta
ficaram em 15,1–16,5 ms para o modo vetorial, 1,7–1,8 ms para FTS e 56,2–59,4
ms para trigram; p95 amostral, respectivamente, 16,1–22,5 ms, 1,8–2,4 ms e
66,2–77,8 ms. Esses valores são somente observações locais, warm-cache e
sintéticas; não representam corpus jurídico nem a latência de produção.

**Limitação observada no plano:** nas três modalidades o PostgreSQL escolheu
`jurix_scale_fixture_norma_type_publication_year_is_active_idx` (Index Scan,
seguido de Sort), não HNSW nem os índices GIN. Portanto, esta rodada não compara
o desempenho dos índices HNSW/FTS/trigram e seus tempos refletem o plano escolhido
pelo otimizador. O Recall@10/MRR de 1,0 é consequência da construção sintética
por tópico e não valida relevância jurídica. O relatório bruto está em
[`retrieval-scale-10k-2026-10-01.json`](retrieval-scale-10k-2026-10-01.json).

**Conclusão operacional:** não há base neste resultado para trocar ranking ou
índices da aplicação. Uma comparação válida exigirá confirmar planos que usem os
índices pretendidos (ou desenhar controles explícitos sem distorcer o workload),
corpus representativo, consultas anotadas por revisores e medições concorrentes
em condições documentadas.
