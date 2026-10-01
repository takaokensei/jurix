# Protocolo de avaliação municipal v1

Este protocolo separa validação mecânica de julgamento jurídico. O runner não
consulta LLM, SAPL ou banco e não transforma similaridade textual em verdade legal.

## Congelamento e revisão

1. Validar manifesto/anotações com `scripts/validate_municipal_corpus.py` e exigir
   20 normas-piloto humanas aprovadas/adjudicadas.
2. Criar arquivos JSONL frozen de gold e predições; registrar SHA-256 dos arquivos,
   hash da revisão do corpus, versão do parser, modelos/versões e parâmetros.
3. Separar normas de desenvolvimento, ajuste e teste antes de ajustar limiares.
   Identificadores de fonte e dispositivos devem ser estáveis, não textos soltos.
4. Não executar o modo RAG científico até existir revisão humana de apoio às
   afirmações e possibilidade de abstenção. O runner informa `not_evaluated` se o
   gold não declara suporte revisado.

## Métricas

- `parser`: exact match de spans por `label/start/end`, micro precision/recall/F1
  por rótulo; offsets tolerantes são análise secundária e não substituem exact match.
- `events`: matriz de confusão por classe de evento, classe `unresolved` incluída;
  alvo é avaliado por igualdade de chave estável quando fornecido.
- `rag`: Recall@1/3/5 e MRR de IDs de dispositivos, precisão de citação por IDs,
  abstenção e erro temporal somente quando anotados/adjudicados por humano.
- Latência: listar observações TTFT/final, n e mediana; n pequeno não estima p95.

Os casos sem fonte esperada não recebem Recall/MRR artificial igual a 1. Resultados
sintéticos validam somente a matemática do runner. Resultado científico municipal
continua bloqueado até o manifesto cumprir o sign-off humano.

Exemplo de chamada:

```powershell
python scripts/evaluate_municipal_v1.py parser --gold parser-gold.jsonl --predictions parser-pred.jsonl --output parser-report.json --corpus-hash <sha256> --system-version <revision>
```

Subcomandos disponíveis: `parser`, `events` e `rag`. A execução não consulta nem
modifica a base de dados; todas as entradas são arquivos explícitos.
