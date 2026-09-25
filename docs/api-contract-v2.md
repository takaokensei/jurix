# Contrato da API de produção v2

## Busca

`GET /api/v1/search/semantic/`

Parâmetros:

- `query`: texto obrigatório;
- `k`: limitado pelo servidor;
- `norma_id`: filtro opcional;
- `min_similarity`: intervalo fechado [0,1].

O servidor nunca deve confiar no `k` vindo do cliente para alocar recursos sem
limite.

## Resposta RAG

Campos relevantes:

- `answer`;
- `sources`;
- `grounded`;
- `grounding`;
- `model`;
- `cached`.

`confidence` não deve ser apresentado como probabilidade calibrada se não existir
calibração estatística documentada.

## Streaming

Eventos válidos:

1. `sources`;
2. `chunk`;
3. `done`;
4. `error`.

Chunks intermediários são provisórios. Apenas o evento `done` pode ser usado para
persistência definitiva da resposta.

## Sessões

Um `session_id` informado deve ser validado contra o usuário autenticado. IDs
inexistentes ou de outro usuário retornam erro sem revelar detalhes internos.

## Erros

Produção deve retornar mensagens genéricas. Logs podem conter detalhes de
exceção, mas não secrets, tokens ou cabeçalhos de autenticação.

## Cache

O cache de resposta só pode ser preenchido quando:

- fontes estão válidas;
- grounding passou;
- política de aceitação passou;
- versão do corpus está correta;
- fingerprint de retrieval corresponde à configuração usada.
