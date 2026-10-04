# Corpus municipal de Natal — Jurix 2.0

Este diretório formaliza o experimento principal do PIBIC/UFRN. O corpus de trabalho é **municipal e proveniente do SAPL de Natal/RN**; benchmarks federais são considerados apenas como generalização secundária e não como gate principal do projeto.

## Meta científica do ciclo atual

- A amostra intencional aprovada pelo plano de pesquisa é de **150–200 normas**.
- **20 normas-piloto** devem receber anotação e adjudicação humanas antes de serem usadas como gold standard.
- A expansão para **300 normas** é uma meta operacional opcional; não substitui a seleção intencional nem o aceite do plano de pesquisa.
- Cada registro deve preservar identificador, PDF e texto extraído com hashes, proveniência SAPL, condição de uso, status OCR e revisão humana.
- A seleção automática é assistida por software; nunca certifica correção jurídica.

Os contratos por registro estão em `manifest.schema.json` e `annotation.schema.json`.
Valide um manifesto/anotações JSONL com `python scripts/validate_municipal_corpus.py
--manifest benchmarks/corpus/municipal_natal/manifest.jsonl --annotations
benchmarks/corpus/municipal_natal/annotations.jsonl`. O validator diferencia erro
estrutural (exit 2) de gate humano ainda incompleto (exit 3). Um exemplo sintético
ou uma sugestão de IA não satisfaz a contagem de 20 normas revisadas.

Os contratos incrementais `manifest.v2.schema.json` e
`annotation.v2.schema.json` preservam identidade por jurisdição/tipo/número/ano,
hashes e spans de evidência. O protocolo de avaliação está em
`graph-evaluation-protocol.md`; os schemas `rag-experiment-*.v1.schema.json`
descrevem entradas e predições para comparação controlada do RAG. Esses arquivos
definem formatos, não contêm gold humano nem resultados experimentais.

O catálogo de casos difíceis sintéticos do QA é apenas uma lista de cenários para
testes de regressão. Não é amostra municipal, anotação jurídica, rótulo gold ou
evidência de precisão/recall.

## Preparação

```powershell
python manage.py ingest_sapl_corpus --limit 300 --year-start 2000 --year-end 2026 --auto-download
python manage.py build_pilot_manifest --corpus-limit 300 --pilot-size 20
```

Use `--sync` no primeiro comando para executar no processo atual durante testes locais; sem essa opção a tarefa é enfileirada no Celery. A ingestão de 300 itens é expansão opcional e requer avaliação de licença, cobertura e capacidade antes de ser chamada.

## Piloto / gold standard

O `pilot.jsonl` gerado pelo comando contém estados separados para triagem assistida por IA, validação humana e anotação. A IA pode ajudar a detectar documentos incompletos, duplicados ou pouco adequados, mas a amostra científica deve ter revisão humana antes de virar referência.

O guia de anotação deve registrar pelo menos:

1. limites de artigo/parágrafo/inciso/alínea/item;
2. eventos `REVOGA`, `ALTERA`, `ADICIONA`, `REGULAMENTA` e `REFERENCIA`;
3. observações sobre texto ilegível/OCR;
4. casos ambíguos que não devem entrar no cálculo sem regra explícita.

Cada anotação referencia o hash exato do texto, spans por offsets e citação literal,
IDs pseudônimos de anotador/revisor e status de adjudicação. Eventos resolvidos
precisam apontar para norma e dispositivo do manifesto; referências incertas ficam
`unresolved` ou `pending_review`, sem alvo inventado.

## Critério de cobertura SAPL

O cliente tenta seguir os links `next` da API. Quando a instalação devolve repetidamente a mesma página de 10 itens, o modo de corpus particiona a busca por ano e, em seguida, por tipo de norma observado no próprio payload. O resultado é limitado a 300 e deduplicado por `sapl_id`.

Isso evita chamar uma lista parcialmente recuperada de "todo o corpus". O log informa explicitamente quando a meta de 300 não é atingida, para que a cobertura possa ser revista antes dos experimentos.
