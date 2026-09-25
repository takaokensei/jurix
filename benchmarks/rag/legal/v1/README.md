# Benchmark jurídico de produção — v1

Este conjunto usa perguntas derivadas de legislação federal brasileira em fontes oficiais do Planalto. O snapshot é de 2026-09-25. Cada caso traz a lei, artigo e URL oficial.

O conjunto é um benchmark de engenharia e factualidade baseado em fontes reais; antes de um release jurídico, um revisor qualificado deve confirmar os casos e marcar a revisão no manifest.

O executor live chama uma instância Jurix e verifica fonte citada + conteúdo mínimo esperado. Ele registra commit, modelo, endpoint e resultados.

Limiares de release: 90% dos casos aceitos e 95% de correspondência de fonte.

Execução:

```powershell
python scripts/run_legal_benchmark_v1.py --base-url http://127.0.0.1:8000 --strict
```
