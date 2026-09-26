# Patch 5 — suggestions corpus-backed + temporal RAG end-to-end

## Correção das sugestões hardcoded

O problema observado na tela vinha de duas fontes simultâneas:

1. `chatbot.html` ainda entregava quatro cards jurídicos diretamente no HTML;
2. `chat.js` ainda mantinha outra lista `SUGGESTION_QUESTIONS` e um fallback local.

O módulo `jurix-dynamic-suggestions.js` já existia, mas não estava carregado pelo
template. Por isso a existência do serviço dinâmico não garantia uma UI dinâmica.

Patch 5 torna o endpoint `/api/v1/suggestions/` a única fonte de perguntas exibidas
na tela de boas-vindas. Quando o endpoint falha, a tela mostra estado vazio, nunca
uma pergunta jurídica inventada localmente.

## RAG temporal

Os parâmetros `as_of`, `published_from` e `published_to` agora entram no
`TemporalScope`, são transportados por `RetrievalOptions` e entram no fingerprint
de cache. O retriever semântico e o lexical filtram as normas pelo período e
respeitam revogações de norma e de dispositivo separadamente.

Uma revogação dirigida a um dispositivo não invalida mais toda a norma.

## Verificação

```powershell
python scripts/validate_dynamic_suggestions_v5.py
python -m pytest
npm test --prefix tests/js
```

Para verificar em execução, abrir `/assistente/` e confirmar no Network que
`/api/v1/suggestions/` retorna `source=municipal_natal_corpus` e que os cards
visíveis possuem os identificadores reais das normas atuais.
