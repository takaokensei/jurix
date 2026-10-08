# Scripts operacionais

Os scripts abaixo são utilitários mantidos para operação, release ou auditoria
manual. Os gates executados no CI estão listados em
[`docs/production-readiness.md`](../docs/production-readiness.md).

## Release e produção

- `validate_staging_contract.py` — valida os artefatos mínimos antes da promoção:
  `python scripts/validate_staging_contract.py`.
- `generate_release_report_v2.py` — gera o relatório de evidências de release;
  execute com `python scripts/generate_release_report_v2.py --help`.
- `backup_verify_v2.py` — verifica a existência e integridade dos artefatos de
  backup; consulte `--help` antes de apontar para um diretório.
- `storage_manifest_v2.py` — audita o manifesto de storage e retenção; use
  `python scripts/storage_manifest_v2.py --help`.

## Smoke tests

- `http_smoke_v2.py` — executa smoke checks HTTP contra um ambiente já
  iniciado; configure a URL/base e revise os endpoints antes de rodar.
- `run_legal_benchmark_v1.py` — executa o benchmark jurídico contra um endpoint
  configurado em `JURIX_BENCHMARK_URL`; só deve ser usado com corpus revisado.
- `run_rag_contract_benchmark.py` — executa o contrato determinístico local
  para `benchmarks/rag/production/contract-cases.v2.jsonl`. Para casos jurídicos
  com `question`/`expected_citations`, use `run_legal_benchmark_v1.py`.
- `evaluate_normative_graph.py` — compara predições JSONL com anotações humanas
  ligadas a hashes; retorna `not_evaluated` enquanto não atingir o mínimo de
  normas adjudicadas. Exemplo: `python scripts/evaluate_normative_graph.py
  --gold <gold.jsonl> --predictions <predictions.jsonl>`.
- `run_normative_rag_experiment.py` — analisa resultados exportados em pares
  dos braços `baseline`, `graph` e `graph_temporal`; não chama modelo nem mede
  geração sozinho. Exemplo: `python scripts/run_normative_rag_experiment.py
  --input <predictions.jsonl> --output <report.json>`.
- `benchmark_normative_pipeline.py` — microbenchmark sintético, offline e
  limitado, de BFS/memória; não é medida de consultas SQL, API ou produção.
  Exemplo: `python scripts/benchmark_normative_pipeline.py`.
- `benchmark_normative_api_qa.py` — mede o endpoint de relações em cinco
  tamanhos de entrada (1/10/40/300/1000 eventos sintéticos), incluindo queries,
  latência fria/aquecida, memória Python, linhas de resposta, truncamento e cache
  Redis; usa somente o runner QA, cria dados em transação revertida e recusa
  banco/cache fora das portas isoladas. O alvo p50 de 300 ms se aplica às
  entradas que exercitam a resposta máxima de 40 nós/80 arestas. Exemplo:
  configure `JURIX_QA_ONLY=1` e `JURIX_QA_ROOT` em diretório temporário e execute
  `python scripts/normative_qa.py --run python scripts/benchmark_normative_api_qa.py`.
  Latência e memória são do Django test client em processo, não de tráfego TCP
  nem de carga de produção.
- `inventory_normative_archive.py` — inventaria ZIP de forma somente leitura e
  escreve manifesto no destino explícito; não extrai documentos. Use apenas
  em cópia permitida e revise limites/saída antes de executar.
- `normative_qa.py` — guard de comandos para banco/Redis QA isolados. Configure
  `JURIX_QA_ONLY=1` e `JURIX_QA_ROOT` temporário; consulte `--help`. Não é
  mecanismo de configuração de produção.
- `normative-product-smoke.mjs` fica em `tests/js/`, não neste diretório:
  browser smoke limitado ao host QA `127.0.0.1:8008`, fixture map sintético e
  diretório de evidências explícito. Nunca aponte para o banco de produto.

Scripts arquivados não são gates alternativos. A auditoria de segurança
canônica é `security_audit_v2.py`; não duplicar catálogos gerados para substituir
esse relatório.
