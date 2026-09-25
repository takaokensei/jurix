# Contrato de resposta RAG

O Jurix separa a relevância das evidências de uma estimativa calibrada de
confiabilidade da resposta.

```json
{
  "answer": "...",
  "sources": [],
  "source_relevance": 0.87,
  "confidence": null,
  "confidence_calibrated": false,
  "grounded": true,
  "grounding": {
    "grounded": true,
    "score": 1.0,
    "claims": [],
    "failed_claims": []
  }
}
```

`source_relevance` resume a qualidade das evidências recuperadas. Não é uma
probabilidade de correção da resposta.

`confidence` permanece `null` até existir um modelo de calibração validado.

Durante streaming, chunks são marcados como `provisional: true`. Apenas o evento
`done` representa o resultado final; respostas que falham no grounding são
substituídas pelo fallback seguro e não entram no cache durável.

O grounding é feito por claim e dispositivo, permitindo auditoria do trecho
específico que sustenta cada afirmação.
