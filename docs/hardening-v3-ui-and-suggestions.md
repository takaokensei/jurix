# Jurix — Hardening V3: sugestões dinâmicas e biblioteca de normas

## Objetivo

Este patch remove a última fonte conhecida de perguntas jurídicas estáticas da tela inicial do assistente e transforma a biblioteca `/normas/` em uma superfície de leitura dedicada.

### Contrato de sugestões

A UI não mantém mais uma lista fixa de perguntas de domínio. O ciclo é:

```text
Norma consolidada + ementa + SAPL ID
             |
             v
 suggestion_service.py
             |
   cache por assinatura do corpus
             |
             v
 /api/v1/suggestions/
             |
             v
 jurix-dynamic-suggestions.js
             |
             v
 cartões da página inicial
```

Uma falha do endpoint não reintroduz conteúdo jurídico hardcoded. A interface mostra apenas o estado neutro de indisponibilidade.

## Geração contextual

Cada pergunta é montada com identificador e tema obtidos da própria ementa. Os textos de perguntas são moldes estruturais, e não exemplos de conteúdo jurídico específico.

O serviço evita N+1 para verificar eventos usando `Exists`, reutiliza uma assinatura construída dos objetos candidatos para o cache e limita o número de sugestões.

## Biblioteca `/normas/`

A listagem recebeu:

- busca por ementa, tipo e número;
- filtro por tipo;
- filtro por ano;
- ordenação recente/antiga;
- visualização grade/lista persistida no navegador;
- paginação que preserva filtros;
- tipografia específica para textos jurídicos;
- cartões com identificação, ementa, publicação, vigência e links;
- foco de teclado e alvos de toque maiores;
- layout de uma coluna em telas estreitas;
- redução de movimento respeitada em CSS;
- superfície visual isolada dos componentes do assistente.

## Auditoria operacional

Execute:

```powershell
python manage.py audit_norma_library
python manage.py audit_norma_library --strict
```

A auditoria identifica dados que prejudicam descoberta e sugestões: ementas vazias, identificadores incompletos, ausência de SAPL ID e chaves duplicadas.

## Testes

A suíte `test_dynamic_suggestions_and_norma_list_v3.py` garante que:

1. sugestões apontem para dados presentes no corpus;
2. o endpoint sinalize a fonte do corpus;
3. perguntas jurídicas conhecidas anteriormente não permaneçam hardcoded no JS/template;
4. filtros da biblioteca funcionem no backend;
5. a página use o novo contrato de layout.

## Critérios de aceite visual

Desktop:

- título e resumo não ocupam mais do que uma faixa horizontal confortável;
- busca permanece estável sem overflow;
- três cartões por linha em larguras grandes;
- dois cartões em tablet;
- um cartão em celular;
- ementas nunca expandem horizontalmente sem limite;
- ações permanecem acessíveis sem depender de hover.

Mobile:

- nenhuma rolagem horizontal;
- filtros em coluna única;
- botões com área de toque >= 42px;
- títulos quebram sem sobrepor outros elementos;
- paginação permanece utilizável.

## Limitações conhecidas

As sugestões continuam sendo perguntas geradas por regras determinísticas; isso não é um gerador LLM. O objetivo aqui é garantir que todo conteúdo apresentado seja ancorado no corpus disponível.

Uma etapa posterior pode introduzir classificação de tópicos ou geração por LLM, desde que o resultado continue sujeito a validação e não invente norma, número ou tese.

## Checklist operacional

- [ ] Verificar dados do corpus
- [ ] Verificar sugestões
- [ ] Verificar api
- [ ] Verificar cache
- [ ] Verificar pesquisa
- [ ] Verificar filtros
- [ ] Verificar paginação
- [ ] Verificar tipografia
- [ ] Verificar dark mode
- [ ] Verificar light mode
- [ ] Verificar mobile
- [ ] Verificar tablet
- [ ] Verificar teclado
- [ ] Verificar leitor de tela
- [ ] Verificar redução de movimento
- [ ] Verificar impressão
- [ ] Verificar auditoria
- [ ] Verificar testes
- [ ] Verificar ci
- [ ] Verificar deploy
- [ ] Verificar rollback
- [ ] Verificar observabilidade
- [ ] Verificar logs
- [ ] Verificar performance
- [ ] Verificar segurança
- [ ] Verificar acessibilidade
- [ ] Verificar documentação
- [ ] Verificar revisão humana
- [ ] Verificar release
- [ ] Verificar smoke test
- [ ] Verificar staging
- [ ] Verificar produção
- [ ] Verificar backup
- [ ] Verificar recuperação
- [ ] Verificar compatibilidade
- [ ] Verificar browser
- [ ] Verificar cache invalidation
- [ ] Verificar dados faltantes
- [ ] Verificar duplicidade
- [ ] Verificar sapl
- [ ] Verificar rag
- [ ] Verificar grounding
- [ ] Verificar fontes
- [ ] Verificar citações
- [ ] Verificar contratos
- [ ] Verificar métricas
- [ ] Verificar slo
- [ ] Verificar runbook
- [ ] Verificar incident response
