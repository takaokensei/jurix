# Corpus municipal de Natal — Jurix 2.0

Este diretório formaliza o experimento principal do PIBIC/UFRN. O corpus de trabalho é **municipal e proveniente do SAPL de Natal/RN**; benchmarks federais são considerados apenas como generalização secundária e não como gate principal do projeto.

## Meta atual

- **300 normas** no corpus de trabalho.
- **20 normas-piloto dentro dessas 300** para gold standard/anotação detalhada.
- Cada registro deve preservar `sapl_id`, identificador jurídico, ementa e URL de origem.
- A seleção automática é assistida por software; ela não certifica correção jurídica.

## Preparação

```powershell
python manage.py ingest_sapl_corpus --limit 300 --year-start 2000 --year-end 2026 --auto-download
python manage.py build_pilot_manifest --corpus-limit 300 --pilot-size 20
```

Use `--sync` no primeiro comando para executar no processo atual durante testes locais; sem essa opção a tarefa é enfileirada no Celery.

## Piloto / gold standard

O `pilot.jsonl` gerado pelo comando contém estados separados para triagem assistida por IA, validação humana e anotação. A IA pode ajudar a detectar documentos incompletos, duplicados ou pouco adequados, mas a amostra científica deve ter revisão humana antes de virar referência.

O guia de anotação deve registrar pelo menos:

1. limites de artigo/parágrafo/inciso/alínea/item;
2. eventos `REVOGA`, `ALTERA`, `ADICIONA`, `REGULAMENTA` e `REFERENCIA`;
3. observações sobre texto ilegível/OCR;
4. casos ambíguos que não devem entrar no cálculo sem regra explícita.

## Critério de cobertura SAPL

O cliente tenta seguir os links `next` da API. Quando a instalação devolve repetidamente a mesma página de 10 itens, o modo de corpus particiona a busca por ano e, em seguida, por tipo de norma observado no próprio payload. O resultado é limitado a 300 e deduplicado por `sapl_id`.

Isso evita chamar uma lista parcialmente recuperada de "todo o corpus". O log informa explicitamente quando a meta de 300 não é atingida, para que a cobertura possa ser revista antes dos experimentos.
