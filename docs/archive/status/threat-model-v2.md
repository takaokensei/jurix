# Threat model de produção v2

## Ativos

- dados legislativos consolidados;
- anexos de usuários;
- sessões e mensagens;
- credenciais de banco, Redis, storage e Ollama;
- embeddings;
- logs e traces;
- resultados RAG que podem influenciar trabalho jurídico.

## Atores

### Usuário autenticado

Pode consultar legislação e operar os próprios recursos autorizados.

### Usuário não autenticado

Pode usar apenas endpoints explicitamente públicos e rate-limited. Não deve
possuir acesso indireto a sessões ou anexos de terceiros.

### Fonte remota SAPL

É uma fonte externa não confiável do ponto de vista operacional. Downloads são
tratados como dados hostis: tamanho, tempo, páginas e tipo devem ser limitados.

### Documento anexado

Conteúdo pode conter instruções destinadas ao modelo. Essas instruções nunca
possuem autoridade sobre o sistema.

## Abuso de recursos

Controles necessários:

1. limite de bytes de download;
2. limite de páginas;
3. timeout de OCR;
4. subprocesso isolado para parsers;
5. limite de concorrência Celery;
6. rate limit da API LLM;
7. limite de contexto;
8. cache somente para respostas aceitas.

## Isolamento

As fronteiras críticas são:

```text
HTTP request
  -> identidade
  -> autorização
  -> serviço de domínio
  -> storage/database

RAG request
  -> retrieval
  -> contexto não confiável
  -> LLM
  -> grounding
  -> política
  -> cache
```

Nenhum componente abaixo deve pular uma camada de autorização para acessar
recursos pertencentes a outro usuário.

## Prompt injection

Uma instrução encontrada em um PDF, artigo ou anexo deve ser tratada como texto.
O modelo deve seguir somente as instruções de sistema/prompt e o contrato de
saída. A existência de frases como “ignore as instruções anteriores” não altera
permissões, ferramentas ou acesso a segredos.

## Data exfiltration

Logs devem evitar:

- tokens de autenticação;
- cookies;
- prompts completos com anexos sensíveis;
- segredos de ambiente;
- conteúdo jurídico desnecessário para diagnóstico.

## Disponibilidade

O sistema deve degradar de modo controlado quando Redis, Ollama ou SAPL não
estiverem disponíveis. Readiness deve distinguir processo vivo de dependências
prontas.
