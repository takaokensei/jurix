# RAG contract benchmark

Execute:

```powershell
python scripts/run_rag_contract_benchmark.py benchmarks/rag/production/contract-cases.v2.jsonl
```

These cases validate the deterministic engineering boundary only. For a legal-quality release, extend the dataset with expert-reviewed cases containing a corpus identifier, expected sources, temporal facts, accepted citations and a review rubric. Never replace expert data with generated examples solely to make CI green.
