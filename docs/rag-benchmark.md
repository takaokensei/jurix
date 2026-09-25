# RAG benchmark

The benchmark is an offline evaluator over an expert-reviewed gold corpus. It does not generate labels automatically.

Run:

```bash
python scripts/run_rag_benchmark.py --cases benchmarks/rag/cases.jsonl --results results/rag.jsonl
```

It reports Recall@1/3/5/10, Precision@1/3/5/10, MRR, Citation Precision, Citation Recall and Groundedness.
