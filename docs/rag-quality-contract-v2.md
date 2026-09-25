# Contrato de qualidade RAG v2

## Objetivo

O sistema não deve transformar similaridade vetorial em afirmação de correção
jurídica. Uma resposta apta a cache durável precisa passar por uma sequência de
controles independentes.

## Pipeline obrigatório

```text
pergunta
  -> normalização de entrada
  -> retrieval híbrido
  -> filtragem temporal/status
  -> construção do contexto
  -> geração
  -> extração de claims
  -> limite de citações às fontes
  -> grounding estrito
  -> política de aceitação
  -> cache somente se aceita
```

## Grounding estrito

A implementação v2 exige, por claim:

- pelo menos uma evidência correspondente;
- citações presentes na evidência;
- todos os números do claim presentes na evidência;
- compatibilidade de negação;
- correspondência de termos acima do limiar configurado;
- compatibilidade de linguagem de certeza quando usada pelo modelo.

Isso é um guardrail determinístico. Não é uma prova semântica de validade
jurídica e não deve ser descrito como tal.

## Respostas sem evidência

Uma resposta sem evidência suficiente deve retornar a mensagem de fallback e
não pode entrar no cache durável.

## Métricas mínimas

A baseline precisa medir, no mínimo:

- recall@1;
- recall@3;
- MRR;
- precisão/recall de citações;
- groundedness;
- taxa de respostas `no_answer` corretamente abstidas.

## Regra de regressão

Uma mudança de modelo, prompt, embedding, retrieval, normalização ou corpus
exige nova execução da baseline. O CI não deve aceitar apenas o fato de que os
testes unitários estão verdes.
