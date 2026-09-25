# Benchmark jurídico de produção

Este diretório é o **contrato**, não um corpus jurídico inventado pelo projeto.
Os casos devem ser adicionados por uma pessoa responsável pelo conteúdo jurídico
e aprovados antes de serem usados como baseline de release.

## Requisitos mínimos

Cada linha do dataset JSONL deve conter:

```json
{
  "id": "case-0001",
  "question": "pergunta jurídica real",
  "expected_sources": ["dispositivo-id"],
  "expected_citations": ["Lei 1234/2025"],
  "answer_policy": "grounded|no_answer"
}
```

O manifesto deve fixar:

- hash SHA-256 do dataset;
- modelo de embeddings;
- modelo de geração;
- quantidade mínima de casos;
- limites de recall, MRR, precisão/recall de citações e groundedness;
- versão do esquema.

## Classes de casos

O conjunto deve conter representantes de:

1. recuperação direta de artigo;
2. paráfrase da regra;
3. perguntas sem resposta no corpus;
4. números, prazos e datas;
5. citações explícitas;
6. conflitos entre documentos ou versões temporais;
7. perguntas adversariais que tentem introduzir fatos não presentes nas fontes;
8. anexos fornecidos pelo usuário.

## Baseline

Uma baseline só deve ser publicada depois da revisão dos casos. O CI deve falhar
quando o hash do corpus mudar sem uma nova baseline ou quando qualquer métrica
ficar abaixo do limite registrado no manifesto.

Não use respostas geradas automaticamente como verdade de referência.
