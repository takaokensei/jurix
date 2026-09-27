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

Scripts arquivados não são gates alternativos. A auditoria de segurança
canônica é `security_audit_v2.py`; não duplicar catálogos gerados para substituir
esse relatório.
