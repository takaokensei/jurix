# Norma Library UI and Dynamic Suggestions v3

## Objetivo

Esta etapa elimina o catálogo fixo de perguntas da tela inicial do assistente e remodela a
listagem `/normas/` para leitura jurídica em telas grandes, laptops, tablets e celulares.

## Sugestões

As sugestões visíveis no hero devem nascer de registros `Norma` elegíveis no corpus. O serviço
consulta somente normas com `sapl_id`, `ementa` e status de processamento suportado. Eventos
relacionados são avaliados em uma única consulta anotada para evitar o padrão N+1.

A geração é determinística e baseada em metadata real: identificador, ementa, vigência e
existência de alterações. O sistema não injeta assuntos municipais arbitrários apenas para
preencher quatro cartões. Quando o corpus estiver vazio, a UI exibe estado vazio e deixa o campo
de pergunta livre disponível.

### Contrato HTTP

`GET /api/v1/suggestions/?limit=4` retorna: \n+
```json
{
  "success": true,
  "source": "municipal_natal_corpus",
  "count": 2,
  "suggestions": [
    {
      "question": "...",
      "title": "...",
      "description": "...",
      "identifier": "Lei 123/2026",
      "norma_id": 1,
      "sapl_id": 123,
      "source": "municipal_natal_corpus",
      "topic": "..."
    }
  ]
}
```

O endpoint aplica o rate limit compartilhado da API e sinaliza `Cache-Control: private` para
permitir revalidação no navegador sem transformar o conteúdo em cache público.

### Hardening contra regressão

Use: 

```powershell
python manage.py validate_suggestion_contract
python manage.py warm_dynamic_suggestions --limit 4 --json
```

O primeiro comando falha se `chat.js` voltar a conter `SUGGESTION_QUESTIONS`,
`renderFallbackChips` ou `fetchDynamicSuggestions`, ou se o container visível da sugestão voltar
a ter `data-question` hardcoded.

## Listagem de normas

`NormaListView` agora possui filtros de texto, tipo, ano e ordenação. A paginação continua no
servidor para evitar carregar todo o acervo no navegador. As opções de tipo/ano e a contagem total
do acervo são cacheadas por um intervalo curto; a contagem do resultado filtrado reutiliza a contagem
calculada pelo paginator.

### UX

O novo layout usa uma hierarquia explícita:

1. hero compacto com contexto do acervo;
2. pesquisa principal;
3. filtros secundários;
4. barra de resultados e alternador de densidade;
5. cards de leitura com metadados e ação de detalhe;
6. paginação persistente.

Em telas menores, os filtros ocupam uma coluna e os cards mudam para uma leitura linear. O JS
mantém a opção grid/list no `localStorage`, sem impedir navegação quando JavaScript estiver desativado.

### Acessibilidade

Os filtros têm labels explícitos, o campo de pesquisa possui nome acessível, o estado vazio é
semântico e o alternador usa `aria-pressed`. O CSS inclui suporte para `prefers-reduced-motion` e
uma folha de impressão que remove controles desnecessários.

## Checklist de rollout

1. Rode `python manage.py validate_suggestion_contract`.
2. Rode `python manage.py test src.tests.test_dynamic_suggestions_and_norma_list_v3 src.tests.test_suggestion_contract_v3`.
3. Rode `npm test --prefix tests/js`.
4. Confirme que `/api/v1/suggestions/?limit=4` retorna `source=municipal_natal_corpus`.
5. Abra `/assistente/` com o corpus vazio e confirme que nenhum assunto jurídico inventado aparece.
6. Com corpus populado, confirme que os cartões exibem identificadores reais e tópicos retirados das ementas.
7. Verifique `/normas/` em 1440px, 1024px, 768px e 390px.
8. Teste teclado, zoom de 200% e `prefers-reduced-motion`.

## Troubleshooting

### Sugestões continuam iguais

1. Execute `python manage.py warm_dynamic_suggestions --limit 4 --json`.
2. Verifique `source`, `identifier` e `topic` na resposta.
3. Limpe o cache Redis da chave dinâmica se a aplicação estiver sendo atualizada durante rollout.
4. Confirme no DevTools que o documento não contém cards com `data-question` antes da resposta da API.

### Nenhuma sugestão aparece

Isso é esperado quando não existem normas elegíveis no corpus. O contrato de UI não usa placeholders
jurídicos para mascarar uma base vazia. A caixa de pergunta continua funcionando normalmente.

### Filtros não persistem ao navegar

A paginação é construída no servidor e deve preservar `q`, `tipo`, `ano` e `ordenar`. Verifique se
o template não foi customizado removendo o helper de query-string.

## Critério de aceite

A feature é considerada concluída quando:

- não existem catálogos fixos de perguntas no frontend;
- o contrato de sugestões passa no comando de validação;
- o endpoint retorna apenas conteúdo de corpus;
- a lista `/normas/` é utilizável sem JavaScript;
- a listagem é legível em viewport móvel;
- os testes Python e Node permanecem verdes.

