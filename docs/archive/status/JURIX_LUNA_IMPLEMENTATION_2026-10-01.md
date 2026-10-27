# Jurix — plano de implementação executável

Data: 01/10/2026. Base auditada: `C:/Jurix`, branch `ui/pro-polish`, HEAD `1895d3f`, com alterações locais preservadas. Leia primeiro [a reavaliação](./JURIX_RESEARCH_PRODUCT_REASSESSMENT.md). Este documento propõe mudanças; **não é autorização para implementá-las, fazer commits ou modificar dados**.

## 1. Decisões e fronteiras

- Manter Python 3.12, Django, templates, JS modular, PostgreSQL/pgvector, Redis/Celery e Ollama. Não migrar para React nem introduzir framework de agentes.
- Priorizar verdade jurídica, identidade das fontes e dados estáveis. A UI premium não compensa uma resposta incorreta apresentada como fundamentada.
- Executar com **GPT 6 Luna em alto**. Médio é suficiente somente nas tarefas marcadas `médio permitido`. Alto é recomendação de engenharia, não garantia de acerto: a orientação oficial admite médio/alto para raciocínio sobre código e diagnóstico ([OpenAI — deployment checklist](https://developers.openai.com/api/docs/guides/deployment-checklist), [modelo Luna](https://developers.openai.com/api/docs/models/gpt-6-luna)). Pedir revisão humana nos gates jurídicos e de dados.
- Não alterar o ranking do histórico. A antiga T-014 continua **adiada**; ordenar os recentes por atualização não significa substituir o algoritmo de pesquisa do histórico.
- Ordenação do catálogo deve continuar por publicação decrescente, fallback ano e número. `Norma.data_publicacao` existe; tratar número como identificador textual com parser explícito, não ordenação lexicográfica ou cast SQL indiscriminado. Esta auditoria não comprovou novo defeito de ordenação que justifique reescrever esse contrato.
- Não iniciar ingestão na abertura do aplicativo. A sincronização periódica já existente deve permanecer operacionalmente opt-in; não executar beat, coleta bruta ou reparação real como consequência de testes.
- Não preencher gold standard por LLM. Não chamar compatibilidade de endpoint de experimento AirLLM. Não transformar benchmark federal ou fixture sintética em validação municipal.
- Contrato compatível primeiro: adicionar campos de versão, manter nomes atuais JSON/SSE durante migração dos consumidores e testar clientes antigos.
- Não usar porcentagem de recuperação como probabilidade de correção jurídica. Mostrar origem do sinal, revisão humana e limitações separadamente.
- Nenhuma promessa de WCAG AA ou nota 9 ao terminar. Aprovação depende dos testes, evidência municipal e operação observados depois.

## 2. Regras de execução comuns a TODAS as tarefas

1. Ler `C:/Jurix/AGENTS.md` se existir; ler o arquivo-alvo completo e o teste correspondente antes de editar. Conferir se o achado ainda existe; se já corrigido, demonstrar e registrar `não necessário`, sem reintroduzir mudança.
2. Registrar `git status --short`, `git branch --show-current`, `git rev-parse HEAD` e `git diff --stat`. Não usar pull, fetch, push, merge, switch, stash, clean, reset ou checkout de arquivos nesta sequência sem nova autorização específica.
3. Preservar os dois arquivos já modificados: `C:/Jurix/src/apps/core/static/js/jurix-rag.js` e `C:/Jurix/tests/js/chat.security.test.mjs`. Preservar `GOAL.md` e documentos anteriores. Quando uma tarefa precisar desses arquivos, inspecionar o diff inicial, editar sobre ele e não incluir mudanças preexistentes em commit próprio sem autorização.
4. Uma tarefa por vez. Produzir um diff coerente. **Um commit local por tarefa somente se autorizado pelo usuário na etapa de implementação.** Sem push/merge. Não fazer commit para tornar uma tarefa aparentemente concluída quando algum gate falhou.
5. Rodar o teste específico antes e depois; registrar comando, exit code e resumo. Usar banco de testes/fixtures. Teste verde com skip obrigatório de PostgreSQL não libera o gate PostgreSQL.
6. Não substituir `.env`, não imprimir credenciais, não persistir API keys em banco/log/artefatos. Não executar comandos de dados com `--apply`, migrações na base real ou ingestão real sem aprovação operacional própria.
7. Se houver ambiguidade jurídica, erro de serviço, migration incompatível, conflito de arquivo ou falha inesperada: **parar a tarefa, mostrar a evidência e pedir decisão; não improvisar**. Tarefas independentes só podem continuar com registro explícito da pendência e sem declarar a fase concluída.
8. Rollback comum: com commit isolado e autorização, reverter esse commit; sem commit, entregar diff para revisão. Não apagar alterações do usuário. Rollback de dados é restauração validada do backup ou compensação revisada, **não** `git revert`.
9. Novos arquivos devem ser criados apenas se ausentes. Números de migrations abaixo pressupõem execução na ordem; conferir o último número antes de gerar. Se outra mudança ocupar o número esperado, parar para reconciliar, não renomear migrations aplicadas.

### Baseline e gates reutilizáveis

Executar em PowerShell, em `C:/Jurix`. Não concatenar comandos para mascarar exit codes.

```powershell
.venv/Scripts/python.exe -m pytest -q --tb=short -o addopts=''
node tests/js/run-tests.mjs
.venv/Scripts/python.exe manage.py check
.venv/Scripts/python.exe manage.py makemigrations --check --dry-run
.venv/Scripts/python.exe -m ruff check src config scripts
.venv/Scripts/python.exe -m ruff format --check src config scripts
.venv/Scripts/python.exe scripts/architecture_budget_v2.py
.venv/Scripts/python.exe scripts/validate_documentation_contract.py
.venv/Scripts/python.exe scripts/run_rag_contract_benchmark.py benchmarks/rag/production/contract-cases.v2.jsonl --json
```

Baseline observado: Python 699 passed/6 skipped; JS 152 passed; check/schema/lint/documentação/contrato aprovados; formatter falha em 32 arquivos; orçamento falha em `rag_service.py` 864/850. Não chamar esses dois gates de regressão nova antes de comparar o baseline. O teste específico mencionado em cada tarefa usa `python -m pytest ARQUIVOS -q -o addopts=''`; não usa banco de desenvolvimento.

## 3. Ordem global e gates de fase

- **Fase A — RP-001 a RP-009:** dependências suportadas, limites honestos e guardrails conservadores. Gate: três contradições da sonda não podem receber grounded=true; texto não enviado não pode validar resposta.
- **Fase B — RP-010 a RP-018:** identidade normativa, contexto, revisão e temporalidade honesta. Gate: artigo/inciso correto por identidade; instrução alteradora não vira redação; texto experimental não vira oficial.
- **Fase C — RP-019 a RP-027:** derivados estáveis, proveniência, cache e providers. Gate: reprocessar preserva IDs/revisão; auditoria HTTP é reproduzível; término remoto inválido não vira completed.
- **Fase D — RP-028 a RP-035:** turno idempotente e interação consistente. Gate: retry não duplica; cancelamento é explícito; fontes/restauração seguem contrato; histórico e retenção são previsíveis.
- **Fase E — RP-036 a RP-040:** design system e leitura jurídica premium. Gate: uma hierarquia, shell coerente, conteúdo antes de estatísticas, teclado/reflow e tema claro/escuro verificados.
- **Fase F — RP-041 a RP-046:** gates, ambiente isolado e evidência científica. Gate: suíte em dois bancos, matriz visual, piloto revisado ou bloqueio científico declarado. Não declarar validação municipal se só ferramentas foram entregues.
- **Fase G — RP-047 a RP-049:** versões temporais, condicionadas a revisão e fixtures aprovadas; marco previsto para janeiro/2027, não atraso em outubro. Gate: consultas antes/depois de alteração reproduzem a redação certa.
- **Fase H — RP-050:** experimento de escala, sem otimização prematura. Gate: relatório reproduzível, recall e custos de filtros medidos.

Se urgência for exclusivamente UI, RP-003, RP-033 e RP-036 podem antecipar-se respeitando dependências; não publicar como produto confiável antes de A–D. Esforços P/M/G representam tamanho relativo, não horas garantidas.

## 4. Tarefas atômicas

### RP-001 — Atualizar Django para linha suportada

Achados: SEC-001. Prioridade alta; M; alto; pré-requisito: baseline.

Arquivos: `C:/Jurix/requirements.txt`, `C:/Jurix/src/tests/test_dependencies.py`, `C:/Jurix/src/tests/test_deployment_config.py`, `C:/Jurix/README.md` somente versão suportada. Não tocar `.env`, migrations antigas ou dados.

1. Consultar tabela oficial de suporte e release de segurança de 5.2 LTS; nesta auditoria a linha suportada era 5.2 e o patch listado 5.2.17. Confirmar o patch vigente na execução antes de fixar a versão, sem saltar para 6.x.
2. Atualizar o pin e os testes que codificam 5.0.9. Instalar em ambiente de teste preservando a configuração local; não atualizar indiscriminadamente as demais dependências.
3. Rodar testes completos, `check`, `makemigrations --check --dry-run`, CSP e segurança de settings. Registrar incompatibilidades, sem gerar migration para mascarar mudança inesperada.
4. Executar ferramenta SCA no lock/dependências efetivas se disponível; se instalação de ferramenta for necessária, solicitar autorização. Registrar advisory, versão corrigida e caminho alcançável, sem afirmar exploração demonstrada.

Aceite: versão suportada; suíte sem regressão; nenhum schema inesperado; relatório de dependências ou limitação explícita. Verificação: testes citados + gates Python/JS/schema. Rollback/se falhar: regras comuns; dependência incompatível bloqueia tarefa.

### RP-002 — Remover conteúdo de perguntas dos logs normais

Achados: SEC-002. Alta; P; médio permitido; depende RP-001.

Arquivos: `C:/Jurix/src/processing/rag_service.py`, `C:/Jurix/src/processing/cache_service.py`, `C:/Jurix/src/apps/legislation/api_search.py`, `C:/Jurix/src/apps/legislation/views.py`; criar `C:/Jurix/src/tests/test_query_logging_privacy.py`. Não tocar formatos de resposta nem configurar captura de prompts.

1. Localizar logs que interpolam query/question e trechos de texto; substituir por request ID, tamanho, etapa, duração, cache hit e código de erro.
2. Não logar corpo completo de exceções de provider que possam ecoar prompt/chave. Sanitizar contexto de exceção antes do logger.
3. Adicionar testes caplog com sentinel sintético em pergunta e API key; nenhuma ocorrência em INFO/WARNING/ERROR. Debug não deve contornar a regra por padrão.

Aceite: diagnósticos continuam úteis sem pergunta/chave. Verificação: novo teste + `src/tests/test_api_security.py`, `test_cache_service.py`. Rollback/se falhar: regras comuns.

### RP-003 — Um limite do composer, validado pelo servidor

Achados: UX-001. Alta; P; médio permitido; depende RP-001.

Arquivos: `C:/Jurix/src/apps/legislation/templates/legislation/chatbot.html`, `C:/Jurix/src/apps/legislation/views.py`, `C:/Jurix/src/apps/core/static/js/jurix-chat-shell.js`, `C:/Jurix/tests/js/streaming.behavior.test.mjs`, `C:/Jurix/src/tests/test_api_limits_options.py`. Não ampliar arbitrariamente o limite em settings.

1. Renderizar `settings.LLM_MAX_QUESTION_LENGTH` em atributo data e maxlength; consumir o atributo no JS em vez de MAX10000 fixo. O valor efetivo nesta base é 2.000.
2. Atualizar contador em input, clear, envio, restore, retry e rejeição; preservar pergunta rejeitada e associar erro ao textarea por `aria-describedby`.
3. Testar limite−1/limite/limite+1, colagem, Shift+Enter e reset programático. A validação backend continua soberana.

Aceite: campo vazio mostra zero; frontend/backend aceitam o mesmo máximo; 400 não apaga pergunta. Verificação: testes citados e envio de texto sintético em navegador. Rollback/se falhar: regras comuns.

### RP-004 — Consertar transporte do benchmark jurídico

Achados: IA-011, parte instrumental. Alta; P; médio permitido; depende RP-001.

Arquivos: `C:/Jurix/scripts/run_legal_benchmark_v1.py`, `C:/Jurix/scripts/run_rag_contract_benchmark.py`, `C:/Jurix/benchmarks/rag/legal/v1/README.md`, `C:/Jurix/src/tests/test_rag_benchmark.py`. Não editar gold nem trocar resposta esperada para fazer passar.

1. Defaultar endpoint JSON para `/api/v1/search/answer/`, que está registrado; preservar override e base URL explícita.
2. Validar schema por tipo de caso, reportando ID/linha/campo ausente. Em SSE, usar o `done.answer` final uma vez, não concatenar resposta final com drafts; falha/EOF sem done é erro.
3. Mockar HTTP para JSON, SSE com chunks+done, failed, EOF e schema misto. Saída e exit code devem distinguir erro de infraestrutura de resultado incorreto.

Aceite: nenhum default inexistente; fixture determinística segue 4/4; não declarar qualidade federal/municipal por isso. Verificação: teste citado e benchmark determinístico do baseline. Rollback/se falhar: regras comuns.

### RP-005 — Grounding somente sobre contexto realmente enviado

Achados: IA-003. Alta; M; alto; depende RP-001.

Arquivos: `C:/Jurix/src/processing/rag_context_builder.py`, `C:/Jurix/src/processing/adaptive_rag_service.py`, `C:/Jurix/src/processing/strict_grounding.py`, `C:/Jurix/src/tests/test_bounded_pipeline.py`, `C:/Jurix/src/tests/test_strict_grounding.py`. Não alterar texto original no banco.

1. Construir cada fonte com campos separados: `full_text`, `snippet`, `evidence_text`, `context_start`, `context_end`; evidence_text deve ser exatamente o trecho de conteúdo incluído, não a totalidade antes do slicing.
2. Contabilizar cabeçalho e separadores no orçamento; não truncar código Unicode no meio nem incluir fonte com zero conteúdo disponível. Guardrail não pode recuperar full_text quando evidence_text existe vazio.
3. Aplicar a mesma regra a anexos. Metadados só validam afirmação se também enviados no contexto.
4. Fixture com sentinel depois do corte: afirmação do sentinel recebe unsupported; afirmação dentro do trecho continua verificável.

Aceite: `context_length <= budget`; nenhum texto invisível sustenta claim. Verificação: testes citados + `test_rag_grounding.py`, `test_rag_service.py`. Rollback/se falhar: regras comuns; revisão obrigatória do diff de contrato.

### RP-006 — Serializar integral e trecho de anexos separadamente

Achados: UX-006. Alta; P; médio permitido; depende RP-005.

Arquivos: `C:/Jurix/src/apps/legislation/serializers.py`, `C:/Jurix/src/tests/test_serializers.py`, `C:/Jurix/tests/js/chat.security.test.mjs` se necessário para expansão. Não tocar limites de upload/TTL nem mudanças preexistentes de hyperlinks.

1. Quando full_text válido existir, serializar como integral; text/snippet continuam resumo, evidence_text continua limite do RP-005.
2. Testar preview curto e full_text maior, full_text ausente, vazio e tipo inválido. Não copiar documento confidencial para logs.
3. No teste de card, expandir integral sem injetar HTML; manter textContent/sanitização existente.

Aceite: expansão não repete preview como se fosse integral; grounding continua limitado. Verificação: teste Python citado + JS completo. Rollback/se falhar: regras comuns.

### RP-007 — Contradição de polaridade deve falhar nos dois sentidos

Achados: IA-001. Crítica; M; alto; depende RP-005.

Arquivos: `C:/Jurix/src/processing/strict_grounding.py`, `C:/Jurix/src/tests/test_strict_grounding.py`, `C:/Jurix/src/tests/test_rag_adversarial_v2.py`. Não afrouxar thresholds para recuperar taxa de grounded.

1. Adicionar regressão exata: fonte “A lei não exige autorização.” versus resposta “A lei exige autorização.”; adicionar inversão contrária e exemplo sem contradição.
2. Associar polaridade ao predicado/frase de evidência, não só existência de “não” em qualquer parte do documento. Implementar helper conservador com retorno `compatible|conflicting|undetermined`.
3. Conflito/indeterminação não autoriza afirmação positiva; reportar motivo no claim report. Testar duas frases com polaridades distintas para evitar falso apoio cruzado.

Aceite: sondas contraditórias nunca grounded=true; casos positivos comprovados permanecem. Verificação: testes citados + contrato determinístico + testes grounding completos. Rollback/se falhar: regras comuns; revisão humana antes de seguir RP-008.

### RP-008 — Preservar modalidade e condições

Achados: IA-002, condições. Crítica; M/G; alto; depende RP-007.

Arquivos: `C:/Jurix/src/processing/strict_grounding.py`, `C:/Jurix/src/tests/test_strict_grounding.py`, `C:/Jurix/src/tests/test_rag_adversarial_v2.py`. Não introduzir NLI/LLM como aprovação automática.

1. Cobrir `se houver`, `desde que`, `quando`, `salvo`, `exceto` e diferença pode/deve/é obrigatório com fixtures revisadas.
2. Comparar qualificador na mesma afirmação/predicado; “pode conceder se houver dotação” não sustenta “concede benefício” incondicional.
3. Emitir motivos `condition_removed`, `modality_strengthened` ou `undetermined`; interpretação ambígua exige abstenção/revisão, não selo de certeza.

Aceite: condição omitida da sonda rejeitada; citação literal condicionada aceita. Verificação: testes de RP-007 e novos casos. Rollback/se falhar: regras comuns; revisão jurídica das fixtures obrigatória.

### RP-009 — Verificar número ligado à unidade e ao fato

Achados: IA-002, números. Crítica; M/G; alto; depende RP-008.

Arquivos: `C:/Jurix/src/processing/strict_grounding.py`, `C:/Jurix/src/tests/test_strict_grounding.py`, `C:/Jurix/src/tests/test_rag_adversarial_v2.py`. Não tratar número da lei como quantidade do fato.

1. Extrair tuplas conservadoras `(valor normalizado, unidade, âncora/predicado)` por frase; separar datas, artigo, número da norma e quantitativos.
2. Fonte prazo 10 dias/multa 20 reais versus resposta prazo 20 dias/multa 10 reais deve falhar, embora conjuntos numéricos coincidam.
3. Testar percentuais, moeda brasileira, datas e número por extenso suportado explicitamente. Normalização não reconhecida retorna indeterminado, sem inventar equivalência.

Aceite: troca relacional rejeitada e unidades preservadas; relatório explica falha. Verificação: testes grounding/adversariais e contrato. Rollback/se falhar: regras comuns; gate A exige revisão dos três conjuntos.

### RP-010 — Um parser de referência normativa

Achados: IA-004, IA-006. Alta; M; alto; depende RP-001.

Criar `C:/Jurix/src/processing/normative_reference.py` e `C:/Jurix/src/tests/test_normative_reference.py`; alterar `C:/Jurix/src/processing/adaptive_rag_service.py`, `C:/Jurix/src/processing/target_reconciliation.py` apenas consumidores equivalentes. Não alterar resolver sem testes de regressão.

1. Definir dataclass imutável com tipo canônico, número normalizado, ano, artigo, parágrafo, inciso, alínea e ambiguidade.
2. Normalizar `8.205`, `8205`, nº/n°/n., artigo ordinal °/º, algarismos romanos de inciso; não confundir “Lei complementar” com ordinária. Mapear tipos SAPL usando metadados presentes, não “qualquer dígito significa Lei”.
3. Número/ano iguais com tipos diferentes exigem resolução explícita; falta de ano não permite escolher arbitrariamente. Testar referências múltiplas.

Aceite: formas equivalentes geram identidade igual; colisões não viram a mesma norma. Verificação: novo teste + `test_target_reconciliation.py`, `test_target_resolver.py`, `test_adaptive_retrieval.py`. Rollback/se falhar: regras comuns.

### RP-011 — Selecionar dispositivo citado por identidade

Achados: IA-004. Alta; M; alto; depende RP-010, RP-005.

Arquivos: `C:/Jurix/src/processing/adaptive_rag_service.py`, `C:/Jurix/src/processing/adaptive_retrieval.py`, `C:/Jurix/src/processing/rag_context_builder.py`, `C:/Jurix/src/tests/test_adaptive_retrieval.py`, `C:/Jurix/src/tests/test_rag_policy_v3.py`. Não fabricar cosine similarity para seleção determinística.

1. Resolver norma/tipo/ano e árvore solicitada antes de semantic k. Pedido art. 7 deve priorizar art. 7 e seus filhos, não art. 8.
2. Retornar `match_kind=explicit_reference` e sinais reais separados; retirar `.98 - posição*.01` e campos que repetem esse valor como semantic/lexical.
3. Identidade explícita ausente/ambígua gera motivo próprio; não substituir por vizinha. Preservar modo semântico para perguntas sem referência.
4. Testar corpus >12 artigos, incisos iguais em pais diferentes, Lei/Decreto com mesmo número e parâmetro k pequeno.

Aceite: dispositivo correto primeiro; scores não simulam métricas. Verificação: testes citados + `test_rag_service.py` e pergunta Art. 7 da Lei 8206 em runtime após aprovação. Rollback/se falhar: regras comuns.

### RP-012 — Pesquisa normativa e chat com a mesma recuperação

Achados: IA-005. Alta; M; alto; depende RP-011.

Arquivos: `C:/Jurix/src/apps/legislation/workspace_views.py`, `C:/Jurix/src/processing/adaptive_retrieval.py`, `C:/Jurix/src/tests/test_workspace_routes.py`, `C:/Jurix/src/tests/test_adaptive_retrieval.py`. Não alterar ranking de conversas nem ordenação do catálogo.

1. Usar o serviço adaptativo/contrato comum em pesquisa; aplicar identidade e filtros antes de limitar candidatos.
2. Para pergunta temática, aplicar penalização limitada a cláusula genérica de vigência/fecho; para pergunta de vigência, não penalizar. Não excluir permanentemente dispositivos válidos.
3. Fixture municipal: Lei 8205 + educação retorna seus artigos úteis; pergunta de vigência retorna artigo final; referências inexistentes não retornam outra lei como resposta exata.

Aceite: mesmos filtros/identidade em pesquisa e chat; critérios de fallback visíveis. Verificação: testes citados + runtime `/pesquisa/` conforme rota real do workspace. Rollback/se falhar: regras comuns.

### RP-013 — Follow-up acrescenta contexto sem apagar intenção

Achados: IA-006. Alta; M; alto; depende RP-010.

Arquivos: `C:/Jurix/src/apps/legislation/api_search.py`, `C:/Jurix/src/processing/rag_prompt.py`, `C:/Jurix/src/tests/test_guest_chat_api.py`, `C:/Jurix/src/tests/test_chat_sessions_api.py`; criar `C:/Jurix/src/tests/test_followup_context.py`. Não confiar em session_id de outro proprietário.

1. Separar pergunta original, referência contextual e consulta de recuperação. Preservar “quem financia as atividades?” ao herdar Lei 8205.
2. Extrair contexto estruturado dos turnos anteriores em ordem temporal; referência explícita nova prevalece; múltiplas normas sem antecedente claro pedem esclarecimento.
3. Testar número pontuado, troca de norma, pergunta distante, inciso com mesmo número em artigos diferentes, sessão anônima e autenticada.

Aceite: “E o artigo 7?” herda norma correta; pergunta completa permanece no prompt e histórico. Verificação: testes citados + conversa de dois turnos em runtime. Rollback/se falhar: regras comuns.

### RP-014 — Separar consolidação aprovada de experimental

Achados: COD-002. Alta; M/G; alto; depende RP-001.

Arquivos: `C:/Jurix/src/processing/consolidation_engine.py`, `C:/Jurix/src/apps/ingestion/consolidation_tasks.py`, `C:/Jurix/src/tests/test_consolidation_safety.py`, `C:/Jurix/src/tests/test_consolidation_engine.py`. Não marcar eventos como validados em massa.

1. Default oficial aplica somente eventos `validado=True`; experimental exige opção explícita e resultado rotulado, sem sobrescrever o derivado aprovado.
2. Registrar pendências/unresolved e conjunto de eventos usados. Target resolvido não é aprovação jurídica.
3. Fixtures iguais com evento aprovado/não aprovado devem produzir derivado oficial distinto e aviso de pendência.

Aceite: evento extraído não revisado nunca altera texto oficial por default. Verificação: testes citados + `test_event_evaluation_v4.py`. Rollback/se falhar: regras comuns; pedir decisão sobre compatibilidade de comandos existentes.

### RP-015 — Extrair redação nova igualmente para alvo já vinculado

Achados: COD-003. Alta; M; alto; depende RP-014.

Arquivos: `C:/Jurix/src/processing/consolidation_engine.py`, `C:/Jurix/src/tests/test_consolidation_safety.py`. Não substituir texto pela instrução “Altera…” se extração falhar.

1. Reutilizar o extrator de redação citada nos caminhos com/sem FK preenchida.
2. Validar conteúdo extraído e identidade do alvo; se ausente/ambíguo, manter redação anterior e emitir pendência verificável.
3. Testar mesma norma alteradora nos dois caminhos e conteúdo com aspas/ordinal; resultados devem ser equivalentes.

Aceite: instrução alteradora nunca vira corpo do artigo; fallback conserva versão. Verificação: teste citado + `test_consolidation_engine.py`. Rollback/se falhar: regras comuns.

### RP-016 — Um contrato de vigência/revogação, sem certezas inventadas

Achados: IA-008, UI-002. Alta; G; alto; depende RP-014.

Arquivos: `C:/Jurix/src/processing/temporal_scope.py`, `C:/Jurix/src/apps/legislation/serializers.py`, `C:/Jurix/src/apps/legislation/temporal_api.py`, `C:/Jurix/src/tests/test_temporal_scope_v4.py`, `C:/Jurix/src/tests/test_temporal_retrieval_v5.py`, `C:/Jurix/src/tests/test_temporal_timeline_v5.py`. Não inferir revogação total de alvo parcial.

1. Definir estados `vigência registrada`, `revogada`, `parcialmente revogada`, `indeterminada`, `pendente de revisão`, com motivo/proveniência; não usar status de processamento como status jurídico.
2. Eventos aprovados e data efetiva governam efeito; publication não substitui data de vigência desconhecida. Evento de dispositivo afeta somente a subárvore identificada.
3. Filtro temporal explícito não aceita data ausente silenciosamente: excluir do conjunto confirmado e reportar incerteza; data desconhecida não prova vigência.
4. Reutilizar regras em recuperação atual/as_of, serializer e timeline. Testar antes/no/depois do início, revogação parcial, total, evento não validado e conflitos.

Aceite: apresentação e seleção não se contradizem; revisão jurídica das fixtures documentada. Verificação: testes citados + `test_temporal_scope_v4.py`. Rollback/se falhar: regras comuns; sem revisão não liberar estado “confirmado”.

### RP-017 — Não oferecer texto histórico sem versão histórica

Achados: IA-009. Alta; P/M; alto; depende RP-016.

Arquivos: `C:/Jurix/src/processing/adaptive_rag_service.py`, `C:/Jurix/src/apps/legislation/api_search.py`, `C:/Jurix/src/apps/core/static/js/jurix-search-controls.js`, `C:/Jurix/src/tests/test_temporal_retrieval_v5.py`. Não criar versões fictícias por filtro de publicação.

1. Quando consulta exige redação em data e não há versão materializada, retornar `historical_version_unavailable` com explicação e fontes contemporâneas claramente rotuladas.
2. Permitir pesquisa documental por publicação sem chamá-la de redação vigente naquela data.
3. UI mostra limitação, não “alta correspondência” de uma redação atual aplicada ao passado.

Aceite: as_of sem versão não recebe confirmação histórica; RP-047–049 podem liberar capacidade depois. Verificação: teste citado + `tests/js/search-controls.test.mjs`. Rollback/se falhar: regras comuns.

### RP-018 — Validação e defesa de hierarquia

Achados: COD-005. Média; M; alto; depende RP-001.

Arquivos: `C:/Jurix/src/apps/legislation/models.py`, `C:/Jurix/src/apps/operations/management/commands/check_corpus_integrity_v2.py`, `C:/Jurix/src/tests/test_target_resolver_hierarchy.py`; criar `C:/Jurix/src/tests/test_hierarchy_integrity.py`. Não reparar dados automaticamente.

1. Validar pai da mesma norma, não self, sem ciclo; lembrar que bulk_create/update não chamam clean, portanto validar no serviço de gravação também.
2. Em get_caminho/get_nivel usar visited e limite defensivo; erro deve produzir diagnóstico controlado, não loop infinito.
3. Comando de integridade somente leitura identifica IDs e tipo de problema; fixtures incluem ciclo, pai externo e árvore válida.

Aceite: dado inválido não trava renderização; teste bulk não contorna serviço. Verificação: testes citados + `test_backfill_caminho.py`. Rollback/se falhar: regras comuns.

### RP-019 — Reprocessar dispositivos com identidade estável

Achados: COD-004. Alta; G; alto; depende RP-018, RP-014.

Arquivos: `C:/Jurix/src/apps/legislation/models.py`, `C:/Jurix/src/apps/ingestion/segmentation_tasks.py`; criar `C:/Jurix/src/processing/device_revision.py`, `C:/Jurix/src/tests/test_segmentation_revision.py`, `C:/Jurix/src/apps/legislation/migrations/0016_device_revision_identity.py`. Não editar migrations antigas nem apagar dispositivos em lote.

1. Adicionar campos de fingerprint do conteúdo e chave estrutural canônica calculada por cadeia pai/tipo/número; detectar colisões antes de declarar unicidade. Migration não resegmenta corpus real.
2. Parsear em memória e validar toda a árvore antes de atomic; fazer upsert por identidade com lock por norma. Manter PK quando conteúdo muda; registrar retirados como inativos/revisão, não cascade delete.
3. FK de evento/citação permanece válida; retrieval ignora dispositivos retirados. Mudança ambígua de identidade gera needs_review, não religa por texto parecido.
4. Executar reprocessamento duas vezes em fixtures: mesmos IDs, pais, contagem e links; erro intermediário reverte transação.

Aceite: fonte URL/dispositivo estável; nenhuma perda de evento após reprocessar. Verificação: novo teste + `test_ingestion_tasks.py`, `test_legal_parser.py`, `makemigrations --check`. Rollback: código + plano de dados próprio; não apagar revisão para rollback. Se falhar: regras comuns, revisar migration antes de aplicar fora dos testes.

### RP-020 — Reextração preserva revisão de eventos

Achados: COD-004, COD-002. Alta; M/G; alto; depende RP-019.

Arquivos: `C:/Jurix/src/apps/legislation/models.py`, `C:/Jurix/src/apps/ingestion/ner_tasks.py`; criar `C:/Jurix/src/processing/event_revision.py`, `C:/Jurix/src/apps/legislation/migrations/0017_event_provenance.py`; alterar `C:/Jurix/src/tests/test_reextract_events.py`.

1. Identificar evento por origem estável, trecho/offset, classe, alvo e versão do extrator; guardar fingerprint e proveniência.
2. Substituir delete-all por reconciliação: repetido mantém ID e aprovação; evidência mudada cria revisão pendente; evento aprovado que sumiu permanece auditável, não é apagado.
3. Testar reextração idêntica, alteração textual, alvo ausente e tarefa duplicada; nunca promover automaticamente validado.

Aceite: aprovação/revisor não desaparecem por reextração; diferenças têm trilha. Verificação: teste citado + `test_ner_extractor.py`, `test_event_evaluation_v4.py`, schema. Rollback/se falhar: mesmas regras de dados de RP-019.

### RP-021 — Embeddings vinculados à revisão do texto

Achados: COD-004, COD-001. Alta; M; alto; depende RP-019.

Arquivos: `C:/Jurix/src/apps/ingestion/management/commands/repair_legal_colophons.py`, `C:/Jurix/src/apps/ingestion/management/commands/bulk_embed_batch.py`, `C:/Jurix/src/processing/device_revision.py`, `C:/Jurix/src/processing/adaptive_retrieval.py`; criar `C:/Jurix/src/tests/test_embedding_revision_integrity.py`. Não rodar bulk real.

1. Qualquer mudança de texto invalida embedding/model timestamp e corpus cache via serviço único; persistir fingerprint que originou o vetor.
2. Gravação do embedding compara fingerprint lido e atual dentro da transação; se mudou durante geração, descartar resultado antigo e reagendar explicitamente.
3. Retrieval vetorial usa somente vetor da revisão atual; lexical pode operar no texto atual e reportar degradação.

Aceite: reparação não deixa vetor antigo elegível; corrida não salva vetor obsoleto. Verificação: novo teste + `test_bulk_embed_batch.py`, `test_corpus_cache_signals.py`, schema. Rollback/se falhar: regras comuns; não repor vetor sem correspondência comprovada.

### RP-022 — Preparar reparação reversível dos colofões antigos

Achados: COD-001. Alta operacional; M; alto; depende RP-020, RP-021.

Arquivos: `C:/Jurix/src/apps/ingestion/management/commands/repair_legal_colophons.py`; criar `C:/Jurix/src/tests/test_colophon_repair_plan.py`, `C:/Jurix/docs/operations/colophon-repair-runbook.md`. Não executar apply no corpus nesta tarefa.

1. Dry-run produz manifesto com IDs, hashes antes/depois, artigos afetados, datas SAPL/OCR e divergências; preserva raw text e referência ao documento.
2. Data conflitante não sobrescreve metadata silenciosamente; proposta pede revisão. Data da sessão não vira publicação ou vigência por aproximação.
3. Apply futuro deve exigir manifesto aprovado/hash coincidente, backup verificado e opção explícita; incluir roteiro de reversão de texto/metadados e reembedding, sem SQL destrutivo genérico.
4. Testar manifesto stale, falha/rollback e execução idempotente em fixtures. Registrar sete casos do dry-run auditado como pendências, não como correções já aplicadas.

Aceite: runbook distingue patch de operação; nenhum dado real alterado. Verificação: novo teste + `manage.py repair_legal_colophons --all` somente dry-run. Rollback/se falhar: regras comuns; apply só em nova janela aprovada.

### RP-023 — Identidade durável do corpus

Achados: IA-010, COD-007. Alta; M/G; alto; depende RP-019, RP-020.

Arquivos: `C:/Jurix/src/apps/operations/models.py`, `C:/Jurix/src/processing/cache_service.py`; criar `C:/Jurix/src/processing/corpus_identity.py`, `C:/Jurix/src/apps/operations/migrations/0003_corpus_revision.py`, `C:/Jurix/src/tests/test_corpus_identity.py`. Não incluir documentos/chaves na identidade pública.

1. Modelo CorpusRevision guarda ID durável, digest ordenado de norma/dispositivo/evento aprovado+revisão, contagens, schema/segmentation version e timestamp. Distinguir completude declarada de atualidade; número de normas sozinho não prova corpus completo.
2. Atualizar geração/digest após commit de mutações legais; LocMem/Redis tornam-se aceleradores, não fonte de verdade. Recuperação retorna ID/revisão consistente com os dados usados.
3. Testar duas instâncias/cache vazio, mudança em texto/evento, transação revertida e corpus parcial. Não recalcular todo corpus em cada token/consulta.

Aceite: resposta de dois workers identifica o mesmo corpus estável; alteração aprovada muda revisão. Verificação: novo teste + `test_corpus_cache_signals.py`, schema. Rollback/se falhar: regras comuns; rever custo de digest e concorrência.

### RP-024 — Contrato auditável JSON/SSE/persistência

Achados: IA-010, UX-005. Alta; G; alto; depende RP-009, RP-011, RP-013, RP-023.

Arquivos: `C:/Jurix/src/apps/legislation/api_search.py`, `C:/Jurix/src/apps/legislation/serializers.py`, `C:/Jurix/src/processing/rag_service.py`, `C:/Jurix/src/tests/test_rag_contract.py`, `C:/Jurix/src/tests/test_streaming_incremental.py`; criar `C:/Jurix/src/processing/answer_contract.py`. Não quebrar tipos de eventos atuais.

1. Construir DTO único: `schema_version`, `request_id`, `corpus_revision`, `question`, `retrieval_query`, filtros, provider/model reais, prompt/policy version, timings, sources, discarded_sources/reasons e grounding claim report.
2. Registrar texto enviado/offset por source; linkar claim ID a source ID e correspondência confirmada. Modelo persistido deve ser o efetivo, não default request quando provider substitui.
3. Adaptar JSON final, done SSE e metadata_json usando o mesmo DTO; mensagens antigas sem campos continuam restauráveis. Não persistir API key/base URL com credenciais, prompt privado redundante ou exceções brutas.
4. Fontes candidatas podem ser enviadas provisoriamente ao transporte, mas UI só revela confirmadas no fim. `completed` identifica término técnico; `grounded=false`/insufficient_evidence continua explícito.

Aceite: JSON/SSE/histórico retêm procedência equivalente; mesmo modelo externo descrito corretamente; draft não vira evidência aprovada. Verificação: testes citados + `test_serializers.py`, `test_chat_sessions_api.py`, JS completo. Rollback/se falhar: regras comuns; revisão de schema/compatibilidade antes de liberar fase.

### RP-025 — Cache identifica geração e política sem secrets

Achados: COD-007. Média/alta; M; alto; depende RP-023, RP-024.

Arquivos: `C:/Jurix/src/processing/cache_service.py`, `C:/Jurix/src/processing/rag_service.py`, `C:/Jurix/src/tests/test_cache_service.py`. Não reutilizar respostas anteriores à nova política por fallback.

1. Fingerprint canônico inclui endpoint normalizado permitido sem credenciais, provider, modelo, temperatura, k/filtros, corpus revision, prompt version e grounding policy version.
2. Credencial nunca entra em fingerprint/log. Cache de conteúdo privado deve ser particionado por proprietário e anexos autorizados; não deduplicar entre usuários por texto.
3. Testar dois endpoints com mesmo model ID, políticas diferentes, cache de usuário/anexo e corpus alterado. Resposta failed/cancelled/provisional não é cacheável.

Aceite: nenhuma colisão entre configurações/usuários distintos; mudança de política invalida. Verificação: teste citado + `test_rag_stream_safety_v2.py`, `test_api_security.py`. Rollback/se falhar: regras comuns.

### RP-026 — Término remoto explícito e falhas estruturadas

Achados: COD-008. Alta; M; alto; depende RP-024.

Arquivos: `C:/Jurix/src/processing/llm_provider.py`, `C:/Jurix/src/processing/rag_service.py`, `C:/Jurix/src/tests/test_llm_provider.py`, `C:/Jurix/src/tests/test_rag_stream_safety_v2.py`. Não adicionar novos providers nesta tarefa.

1. Adapters distinguem chunk, erro e término confirmado. OpenAI-compatible: finish_reason permitido/terminador conforme protocolo; Anthropic: message_stop. `length` é truncamento, não conclusão jurídica aprovada.
2. EOF prematuro, JSON inválido de evento de conteúdo e erro do provider geram exceção tipada. Heartbeat/metadados sem texto são permitidos; não engolir erro de protocolo.
3. Fechar requests em finally/cancel; não cachear nem persistir partial como completed. Testar sequências boas, error, length, EOF, timeout e redirects ainda proibidos.

Aceite: partial nunca recebe done final aprovado; erro mostra código seguro. Verificação: testes citados; integração cloud real continua não testada sem chave aprovada. Rollback/se falhar: regras comuns.

### RP-027 — Endpoint local aprovado com autenticação opcional

Achados: UX-007. Média; M; alto; depende RP-026.

Arquivos: `C:/Jurix/config/settings.py`, `C:/Jurix/src/processing/llm_provider.py`, `C:/Jurix/src/apps/core/static/js/workspace.js`, `C:/Jurix/src/apps/legislation/templates/legislation/workspace/settings.html`, `C:/Jurix/src/tests/test_llm_provider.py`, `C:/Jurix/tests/js/search-controls.test.mjs`. Não relaxar allowlist/redirects, nem presumir toda rede privada confiável.

1. Adicionar configuração explícita de endpoints aprovados que permitem auth opcional, separada da allowlist de destinos. Default vazio; provedor público continua exigindo chave.
2. Backend revalida destino e capability; frontend explica chave opcional somente para capability permitida, sem tomar decisão de autorização por hostname digitado.
3. Sem chave omitir Authorization, não enviar Bearer fictício. Testar loopback opt-in, destino não permitido e endpoint aprovado que ainda exige auth.

Aceite: servidor local sem auth funciona quando autorizado; demais destinos continuam fechados. Verificação: testes citados + `test_settings_security.py`. Rollback/se falhar: regras comuns; não alterar .env para desbloquear teste.

### RP-028 — Modelo de turno idempotente

Achados: COD-006. Alta; G; alto; depende RP-024.

Arquivos: `C:/Jurix/src/apps/legislation/models.py`; criar `C:/Jurix/src/apps/legislation/migrations/0018_chat_turn_identity.py`, `C:/Jurix/src/tests/test_chat_turn_identity.py`, `C:/Jurix/src/processing/chat_turns.py`. Não migrar mensagens antigas por adivinhação nem remover sessões.

1. Modelo ChatTurn com owner autenticado ou namespace anônimo assinado, client_session UUID, client_turn UUID, payload digest, estado, mensagens/resultados associados e timestamps; unique por namespace+session+turn.
2. Primeiro POST deve reservar sessão e turno em uma única transação, usando UUID de cliente para impedir criação duplicada de sessão. Não usar ID público fornecido como autenticação.
3. Repetição mesma identidade/payload devolve estado existente; payload diferente retorna 409. Lock/conflito de inserção não permite duas gerações.
4. Testar duas requisições concorrentes no banco PostgreSQL isolado; SQLite cobre lógica, não prova concorrência.

Aceite: constraint durável, isolamento por proprietário e migration reversível em teste. Verificação: novo teste + `test_chat_session_slug.py`, schema; gate concorrência depende RP-043. Rollback/se falhar: regras comuns; revisão de migration obrigatória.

### RP-029 — HTTP/SSE consomem turno reservado uma vez

Achados: COD-006. Alta; G; alto; depende RP-028, RP-026.

Arquivos: `C:/Jurix/src/apps/legislation/api_search.py`, `C:/Jurix/src/processing/chat_turns.py`, `C:/Jurix/src/tests/test_chat_sessions_api.py`, `C:/Jurix/src/tests/test_guest_chat_api.py`, `C:/Jurix/src/tests/test_streaming_incremental.py`. Não mudar proprietário de sessão por parâmetro.

1. Reservar turno antes de criar user message; gerar uma vez. Expor session identity antes dos chunks, salvar final antes do done e associar tudo ao turn.
2. Repetição completed entrega resultado final sem regenerar; in-progress entrega estado e estratégia explícita de retomada/poll, não segundo stream concorrente. failed/cancelled exigem tentativa nova vinculada ao turno original.
3. Desconexão nunca aprova draft; registrar interrupted com recuperação. Não prometer retomada por offset de token se transporte não a suporta.
4. Testar primeiro POST duplicado, retry após final, queda antes de done e owner diverso.

Aceite: exatamente uma pergunta/final persistida por turno; contrato antigo tem transição documentada. Verificação: testes citados + `test_api_security.py`. Rollback/se falhar: regras comuns; revisão de SSE/primeiro POST obrigatória.

### RP-030 — Retry e botão Parar na máquina de estados do chat

Achados: UX-002, COD-006. Alta; M/G; alto; depende RP-003, RP-029.

Arquivos: `C:/Jurix/src/apps/core/static/js/jurix-chat-api.js`, `C:/Jurix/src/apps/core/static/js/jurix-chat-state.js`, `C:/Jurix/src/apps/core/static/js/jurix-chat-controller.js`, `C:/Jurix/src/apps/core/static/js/chat.js`, `C:/Jurix/src/apps/legislation/templates/legislation/chatbot.html`, `C:/Jurix/tests/js/streaming.behavior.test.mjs`. Não criar segundo controlador do composer.

1. Gerar client_turn_id antes do primeiro fetch; guardar com mensagem pendente e manter no retry da mesma tentativa. Nova geração explícita usa attempt ligado ao original.
2. Botão enviar vira Parar com nome acessível durante generating; abortar transporte, fechar generator e rotular draft interrompido. Não chamar cancelamento local de cancelamento remoto confirmado se servidor ainda processa.
3. Estados mínimos: idle/submitting/streaming/finalizing/completed/failed/cancelled; um owner controla habilitação, contador e retry.
4. F5 em estado interrompido recupera mensagem segura sem duplicar, drawer não bloqueia nova pergunta e fontes só surgem após final válido.

Aceite: stop imediato, retry sem duplicação, teclado funcional e pergunta preservada. Verificação: testes citados + JS completo; runtime pergunta→parar→retry→F5 em sessão sintética. Rollback/se falhar: regras comuns.

### RP-031 — Título baseado no assunto corroborado, sem atrasar done

Achados: IA-007. Média; M; alto; depende RP-013, RP-024.

Arquivos: `C:/Jurix/src/apps/legislation/api_search.py`; criar `C:/Jurix/src/processing/conversation_titles.py`, `C:/Jurix/src/tests/test_conversation_titles.py`; alterar `C:/Jurix/src/apps/core/static/js/jurix-chat-sessions.js` somente recepção do título. Não adicionar Celery obrigatório a modo SQLite local.

1. Fallback imediato usa assunto/ementa da fonte confirmada e número quando pertinente, 3–7 palavras, sem repetir pergunta inteira.
2. Título LLM recebe assunto evidenciado e tem orçamento curto; candidato com entidades/tema não sustentados é rejeitado. Caso Lei 8205 não pode virar proteção animal.
3. Não executar chamada de até 120 s depois do done no mesmo generator. Refinamento opcional usa job quando disponível ou mecanismo separado com limite/erro isolado; fallback suficiente quando indisponível.

Aceite: final do stream não depende de titulação; títulos inventados rejeitados; sidebar/histórico sincronizam. Verificação: novo teste + `test_chat_sessions_api.py`, JS completo. Rollback/se falhar: regras comuns; manter fallback em vez de inventar serviço background.

### RP-032 — Resposta e fontes explicam afirmações, não porcentagens

Achados: UX-005, IA-010, IA-004. Alta; M/G; alto; depende RP-024, RP-030.

Arquivos: `C:/Jurix/src/processing/rag_prompt.py`, `C:/Jurix/src/apps/core/static/js/jurix-rag.js`, `C:/Jurix/src/apps/core/static/css/jurix-rag.css`, `C:/Jurix/tests/js/chat.security.test.mjs`, `C:/Jurix/src/tests/test_rag_contract.py`. Preservar bare-law URL sem fragmento e links artigo/inciso com fragmento.

1. Prompt pede resposta direta, sem “resposta à pergunta do usuário”, repetição da pergunta ou conclusão idêntica; limitações são campos determinísticos fora do texto do modelo.
2. Usar claim map para “fundamenta afirmação X”; fonte apenas recuperada recebe “contexto recuperado”, não contribuição inventada por LLM.
3. Badge sem percentual jurídico: “referência identificada”, “apoio parcial”, “evidência insuficiente”, com explicação técnica opcional. Texto e ícone acompanham cor.
4. Manter grupo por norma e atualizar Expandir todas quando disclosures individuais mudam. Links só de fontes confirmadas/permitidas; never invent URL. Fade-in 160–200 ms no término, reduced-motion sem atraso.

Aceite: fonte sustenta claim identificável; sem98% fabricado; F5 e conclusão imediata mostram mesmas fontes. Verificação: testes citados + `test_source_urls.py`, runtime drawer/links/Escape. Rollback/se falhar: regras comuns; inspecionar diff preexistente antes de editar JS/teste.

### RP-033 — Um renderer de recentes para todas as rotas

Achados: UX-003, UI-003. Média; M; alto; depende RP-031.

Arquivos: `C:/Jurix/src/apps/core/static/js/jurix-sidebar.js`, `C:/Jurix/src/apps/core/static/js/chat.js`, `C:/Jurix/src/apps/legislation/templates/legislation/workspace/_sidebar.html`, `C:/Jurix/tests/js/sidebar.unification.test.mjs`. Não alterar algoritmo de pesquisa do histórico.

1. Remover renderização de recentes particular do chat; expor um único renderer que recebe sessões e sessão ativa.
2. Ordenar updated_at desc com desempate estável; link de sessão e botão delete irmãos, nunca botão/role=button contendo outro botão.
3. Escutar eventos comuns de create/title/update/delete; não duplicar listeners ao navegar. Gear de configurações, rail com ícones e collapsed preference iguais em todas as rotas.

Aceite: mesmas conversas/ordem em assistente, normas e configurações; Tab chega a link/delete separados. Verificação: teste citado + `unified-sidebar-smoke.mjs` após ler opções; runtime três rotas. Rollback/se falhar: regras comuns.

### RP-034 — Preview limpo e exclusão no histórico anônimo

Achados: UX-004. Média; M; alto; depende RP-033, RP-030.

Arquivos: `C:/Jurix/src/apps/core/static/js/jurix-anonymous-history-page.js`, `C:/Jurix/src/apps/core/static/js/jurix-history-actions.js`, `C:/Jurix/src/apps/core/static/js/jurix-anonymous-history.js`, `C:/Jurix/src/apps/legislation/templates/legislation/workspace/history.html`, `C:/Jurix/tests/js/pagination.and.storage.test.mjs`. Não alterar ranking nem autenticar usuário por localStorage.

1. Preview usa texto puro a partir da renderização sanitizada/extração segura, sem `###`, links Markdown ou repetição literal do título.
2. Usar mesma confirmação de exclusão para local e autenticado, com adaptador de armazenamento; botão de excluir acessível sempre disponível, swipe opcional não é único caminho.
3. Modal arredondado, fade-in160ms, Escape/cancel restaura foco; confirmar remove somente sessão escolhida e atualiza sidebar/pesquisa.

Aceite: local delete não chama endpoint autenticado; swipe vertical não exclui; modal não deixa foco preso. Verificação: teste citado + JS completo; runtime sessão de teste criada para excluir, sem apagar conversas preexistentes. Rollback/se falhar: regras comuns.

### RP-035 — Retenção local honesta e controle do usuário

Achados: SEC-003. Média; M; alto; depende RP-034.

Arquivos: `C:/Jurix/src/apps/legislation/templates/legislation/chatbot.html`, `C:/Jurix/src/apps/legislation/templates/legislation/workspace/settings.html`, `C:/Jurix/src/apps/core/static/js/jurix-anonymous-history.js`, `C:/Jurix/src/apps/core/static/js/workspace.js`, `C:/Jurix/tests/js/pagination.and.storage.test.mjs`. Não apagar histórico existente sem confirmação/consentimento.

1. Copy informa armazenamento neste navegador e permanência até exclusão/limite; não dizer “só durante a sessão” para localStorage sem TTL.
2. Oferecer apagar dados locais com confirmação, exportar JSON validado e aviso de dispositivo compartilhado. Opção sessão temporária usa mecanismo/TTL explícito somente após consentimento.
3. Chaves continuam fora do histórico/export; limpar chave de sessionStorage tem ação própria e explicação de limite de proteção contra XSS.

Aceite: export sem secrets, clear só após confirmar e escopo exato; storage indisponível preserva UX com aviso. Verificação: teste citado + `test_frontend_static.py`; runtime em perfil de teste. Rollback/se falhar: regras comuns.

### RP-036 — Fundação visual: tokens com dono único

Achados: UI-003, A11Y-001, UI-001. Média; M; alto para primeira revisão; médio permitido em migração mecânica posterior; depende RP-003.

Arquivos: `C:/Jurix/src/apps/core/static/css/swiss-design-system.css`, `C:/Jurix/src/apps/core/static/css/jurix-components.css`, `C:/Jurix/tests/js/visual_contracts.test.mjs`; criar `C:/Jurix/docs/design-system-current.md`. Não instalar fonte externa, copiar ícones/marca nem alterar CSP.

1. Inventariar tokens atuais; nomear por semântica `bg/canvas/surface/elevated`, `text/primary/secondary`, `border/default/focus`, `action/primary`, `state/error/warning/success`. Manter mapeamento legado temporário, não criar segunda paleta concorrente.
2. Escala: body1rem/line-height1.6–1.7; UI0.875rem/1.4; metadata0.75rem somente não essencial; títulos1.25/1.5/2rem responsivos. Stack local `system-ui, -apple-system, Segoe UI, sans-serif`; serif só texto editorial deliberado, não alternância acidental entre shells.
3. Espaço4/8/12/16/24/32/48 px, raios8/12/16, sombra só em overlays, borda1px. Área de ação alvo44CSSpx em toque; WCAG mínimo24 ou exceção documentada, não equivaler44pt a obrigação AA.
4. Foco2px com offset2 e contraste≥3:1; texto normal≥4.5:1, grande≥3:1; estados hover/focus/pressed/disabled reconhecíveis sem só cor. Motion120–220ms, reduced-motion elimina deslocamento/atraso.
5. Registrar valores reais claros/escuros após medir combinações; não copiar hex arbitrário sem contraste. Base: HIG hierarquia/alvos, M3 tokens/estados, WCAG contraste/reflow.

Aceite: um mapa de tokens; nenhum componente novo depende de hardcode solto; documentação com valores medidos e estados. Verificação: teste citado + CSS inspect no navegador claro/escuro. Rollback/se falhar: regras comuns; não “passar” contraste só lendo nomes.

### RP-037 — Consolidar shell e cascata sem reescrever o aplicativo

Achados: UI-003. Média; M/G; alto; depende RP-033, RP-036.

Arquivos: `C:/Jurix/src/apps/legislation/templates/legislation/chatbot.html`, `C:/Jurix/src/apps/legislation/templates/legislation/workspace/base.html`, `C:/Jurix/src/apps/core/static/css/workspace.css`, `C:/Jurix/src/apps/core/static/css/jurix-chat-shell.css`, `C:/Jurix/src/apps/core/static/css/jurix-sidebar.css`, `C:/Jurix/tests/js/sidebar.unification.test.mjs`. Não retirar CSS sem demonstrar consumidor.

1. Definir _sidebar/_topbar como únicos donos do chrome; composer/chat mantém comportamento especializado em região main, não segundo shell.
2. Catalogar seletores duplicados e consolidar só regras equivalentes; trocar overrides tardios por classe de componente/estado explícita. Remover blocos mortos comprovados, não folha inteira presumida.
3. Estado collapsed aplicado antes da primeira pintura pelo mecanismo externo CSP já existente; navegação à rota atual é no-op, URLs profundas distintas continuam funcionando.
4. Comparar screenshots de assistente/normas/configurações nas quatro larguras, incluindo desktop expandido/recolhido e mobile drawer.

Aceite: sem flicker/reflow de sidebar; composer nunca sobrepõe rail; rolagem continua por área correta. Verificação: teste citado + `test_workspace_routes.py`, JS completo e matriz RP-046. Rollback/se falhar: regras comuns.

### RP-038 — Cabeçalho da norma orientado à leitura

Achados: UI-001. Média; M; alto; depende RP-016, RP-036.

Arquivos: `C:/Jurix/src/apps/legislation/templates/legislation/norma_detail.html`, `C:/Jurix/src/apps/legislation/templates/legislation/norma_list.html`, `C:/Jurix/src/apps/core/static/css/jurix-legal-detail.css`, `C:/Jurix/src/apps/core/static/css/jurix-norma-list.css`, `C:/Jurix/tests/js/norma_ui_v3.test.mjs`. Não ocultar fonte oficial/revisão por estética.

1. Detalhe: identificação oficial→ementa→status com procedência/publicação/vigência→ações→texto. Cards de caracteres/contagem ficam em “Informações técnicas” disclosure fechado.
2. Uma ação primária “Perguntar sobre esta norma”; SAPL/Comparar/Árvore como secundárias. Mobile: até duas ações visíveis e menu “Mais”, em vez de seis linhas antes da lei.
3. Metadados visualmente secundários mas legíveis; título1.5–2rem, corpo1rem, coluna legal68–78ch. Não baixar publicação/vigência a contraste insuficiente.
4. Catálogo coloca filtros e resultados antes de cards decorativos; preserve ordenação e filtros existentes.

Aceite: em360px cabeçalho não é dominado por estatística; leitor alcança texto sem atravessar seis botões; vigência também no topo. Verificação: teste citado + `test_dynamic_suggestions_and_norma_list_v3.py`; screenshots360/1280. Rollback/se falhar: regras comuns.

### RP-039 — Índice confortável e timeline em português

Achados: A11Y-001, UI-002. Média; P/M; médio permitido; depende RP-016, RP-038.

Arquivos: `C:/Jurix/src/apps/legislation/templates/legislation/norma_detail.html`, `C:/Jurix/src/apps/core/static/css/jurix-legal-detail.css`, `C:/Jurix/src/apps/core/static/js/jurix-legal-detail.js`, `C:/Jurix/src/tests/test_temporal_timeline_v5.py`, `C:/Jurix/tests/js/norma_ui_v3.test.mjs`. Não transformar dado desconhecido em vigente.

1. Índice com área de44px em toque e espaçamento8px, disclosure compacto no mobile; desktop pode usar densidade menor com exceção WCAG documentada. Scroll-margin considera topbar e foco da âncora fica visível.
2. Mapear kind para rótulos: publication→Publicação, effective→Início de vigência registrado; estado revisado/pendente aparece como texto, não só badge colorido.
3. Datas legíveis pt-BR com datetime ISO no `<time>`; distinguir origem oficial, extraída e inferida. Tab/Enter/Escape não perdem foco.

Aceite: nenhum kind interno cru; índice sem alvos diminutos em toque; foco não encoberto. Verificação: testes citados + teclado e320/200% na matriz. Rollback/se falhar: regras comuns.

### RP-040 — Comparação estrutural em vez de linhas OCR

Achados: UI-001, UX-005; melhoria estrutural da comparação observada. Média; M/G; alto; depende RP-019, RP-036.

Arquivos: `C:/Jurix/src/apps/legislation/views.py`, `C:/Jurix/src/apps/legislation/templates/legislation/norma_compare.html`, `C:/Jurix/src/apps/core/static/css/jurix-legal-detail.css`; criar `C:/Jurix/src/processing/legal_diff.py`, `C:/Jurix/src/tests/test_legal_diff.py`. Não chamar diferença visual de alteração jurídica validada.

1. Parear por chave estrutural do dispositivo; normalizar somente whitespace/linhas OCR, preservando palavras, números, pontuação relevante e negação.
2. Distinguir texto mudado, dispositivo incluído/retirado e formatação apenas; raw OCR segue disponível em modo técnico separado.
3. Eventos aprovados sustentam rótulo jurídico; sem eles dizer “Diferença textual”, não “lei alterada”. Mobile leitura empilhada com rótulos original/derivado e controles por teclado.

Aceite: quebra de linha não produz dezenas de falsas alterações; troca não/quantidade continua destacada. Verificação: novo teste + `test_workspace_routes.py`; runtime comparação mobile. Rollback/se falhar: regras comuns.

### RP-041 — Formatação como mudança mecânica isolada

Achados: COD-009. Média; P; médio permitido; depende fases A–E concluídas ou escopo mecânico aprovado.

Arquivos: somente arquivos apontados por `ruff format --check src config scripts`; registrar lista exata antes do diff. Não tocar arquivos fora dessa lista, configs/budgets nem alterações JS preexistentes.

1. Capturar lista atual (baseline tinha32), aplicar formatter somente aos arquivos Python declarados, sem refatoração manual no mesmo commit.
2. Conferir diff e AST quando houver dúvida; não converter falha funcional em “era formatação”.
3. Testar suite e lint; alterações científicas/contratos permanecem em suas tarefas próprias.

Aceite: format-check passa, diff mecânico revisável. Verificação: `ruff format --check src config scripts`, `ruff check src config scripts`, Python completo. Rollback/se falhar: regras comuns.

### RP-042 — Reduzir hotspot por responsabilidade coesa

Achados: COD-009. Média; M; alto; depende RP-024, RP-025, RP-041.

Arquivos: `C:/Jurix/src/processing/rag_service.py`; criar `C:/Jurix/src/processing/rag_generation.py`; alterar `C:/Jurix/src/tests/test_rag_service.py`, `C:/Jurix/src/tests/test_rag_stream_safety_v2.py`. Não aumentar budget nem dividir arquivo por corte de linhas.

1. Extrair orchestration de geração/finalização comum JSON/SSE para helper que recebe provider/context/policy explicitamente; manter retrieval/cache fora do helper.
2. Preservar métodos públicos de RAGService delegando; evitar importar service de volta e criar ciclo. Mocks dos testes devem apontar para dependência real, não suprimir execução.
3. Rodar contratos, streaming, fallback e cache; verificar módulo<=850 e nenhuma classe-helper com acoplamento oculto igual ao original.

Aceite: orçamento verde com comportamento igual e responsabilidade legível. Verificação: testes citados + `test_rag_grounding.py`, arquitetura e Python completo. Rollback/se falhar: regras comuns.

### RP-043 — Stack de integração descartável e isolada

Achados: OPS-001. Alta operacional; M/G; alto; depende RP-001, RP-019, RP-028.

Criar `C:/Jurix/docker-compose.audit.yml`, `C:/Jurix/docs/operations/audit-stack.md`, `C:/Jurix/src/tests/test_audit_stack_config.py`; ler `C:/Jurix/docker-compose.yml` sem substituir. Não usar volumes/nomes/portas da stack existente, nem ligar beat.

1. Perfil audit com PostgreSQL+pgvector e Redis em portas exclusivas, projeto/volumes identificados `jurix-audit`, worker sem agendamento de ingestão. Validar portas livres antes de subir; sem container_name fixo compartilhado.
2. Usar credenciais efêmeras somente para fixture, não imprimir nem copiar .env. Runner define DATABASE/CACHE/CELERY explicitamente para stack de teste; migration aplica somente nessa base descartável.
3. Executar tests PostgreSQL de índice/cosseno/filtros, constraint/concorrência ChatTurn e tarefas sintéticas; verificar health de Redis/worker e retry/cache compartilhado.
4. Runbook ensina conferir mounts antes de cleanup. Nunca `down -v` na stack real; remoção audit só com alvos conferidos/autorizados.

Aceite: serviços saudáveis e testes sem skips PG críticos; nenhuma tarefa afeta corpus real. Verificação: config-test, `docker compose -f docker-compose.audit.yml config --quiet`, suite no runner audit com manifesto de DB usado. Rollback/se falhar: parar serviços audit sem remover dados reais; limitação não vira aprovação.

### RP-044 — Corpus/piloto municipal com procedência humana

Achados: IA-011, gap científico. Alta para pesquisa; G, inclui trabalho humano; alto; depende RP-022, RP-023.

Arquivos: `C:/Jurix/benchmarks/corpus/municipal_natal/README.md`, `C:/Jurix/docs/pibic-gap-plan.md`; criar `C:/Jurix/benchmarks/corpus/municipal_natal/manifest.schema.json`, `annotation.schema.json`, `C:/Jurix/scripts/validate_municipal_corpus.py`, `C:/Jurix/src/tests/test_municipal_corpus_contract.py`. Não gerar gold preenchido pela LLM.

1. Schema manifesta norma/tipo/número/ano/URL oficial/hash documento, modalidade OCR, datas/proveniência, licença/condição de divulgação e seleção intencional. Diferenciar150–200 aprovadas de expansão opcional300.
2. Schema anotação: spans de artigo/parágrafo/inciso/alínea/item, evento, alvo/cadeia, efeito temporal, evidência, annotator ID pseudônimo/revisor/adjudicação. Vinte normas-piloto devem ser revisadas por pessoa; máquina pode sugerir, não assinar gold.
3. Validator detecta duplicidade, spans fora do texto, parent externo, referência inexistente, conflito não adjudicado e missing signoff. Exemplo permanece exemplo e nunca satisfaz gate de20.
4. Entregar roteiro de seleção/anotação; marcar bloqueado científico enquanto20revisadas não existirem. Expansão real por ingestão é operação separada aprovada.

Aceite: validator e documentação honestos; piloto real só aprovado com evidência de revisão. Verificação: novo teste e validator contra exemplos (deve sinalizar incompletude para gate de release). Rollback/se falhar: regras comuns; não baixar exigência para publicar resultados.

### RP-045 — Avaliadores científicos municipal/parser/eventos/RAG

Achados: IA-011, gap científico. Alta para pesquisa; G; alto; depende RP-004, RP-024, RP-044.

Criar `C:/Jurix/scripts/evaluate_municipal_v1.py`, `C:/Jurix/benchmarks/corpus/municipal_natal/evaluation-protocol.md`, `C:/Jurix/src/tests/test_municipal_evaluation.py`. Reusar lógica válida de `C:/Jurix/scripts/validate_rag_benchmark.py`/`run_legal_benchmark_v1.py`; não declarar accuracy por substring de lei.

1. Subcomandos parser/events/rag com inputs frozen e output JSON versionado. Parser: precision/recall/F1 por tipo/span exato e política de tolerância separada; eventos: alvo/classe e matriz de confusão incluindo unresolved.
2. RAG: Recall@k e precisão de citação por IDs/dispositivo, apoio de claim revisado, abstenção correta, erro temporal, latência TTFT/final e configuração/corpus hash. Não usar overlap textual como verdade jurídica final.
3. Separar gold/testset de tuning; fixed seeds/config e repetição≥3 para latência com n pequeno declarado. Não converter média de três amostras em p95 estatisticamente robusto.
4. Fixtures sintéticas verificam matemática e denominadores; caso sem fontes esperadas não ganha score1 automaticamente. Live runner requer corpus e signoff; sem isso retorna bloqueio, não relatório de qualidade fabricado.

Aceite: métricas reproduzíveis e resultados humanos separados do guardrail automático. Verificação: novo teste + validators; execução municipal real só após gate RP-044. Rollback/se falhar: regras comuns.

### RP-046 — Auditoria E2E, acessibilidade e desempenho com gates honestos

Achados: UX/UI/A11Y, OPS-001, PERF-001; hipóteses remanescentes. Alta; M/G; alto; depende RP-030–040, RP-043.

Criar `C:/Jurix/tests/js/product-runtime-smoke.mjs`, `C:/Jurix/docs/audit/product-acceptance-matrix.md`; alterar `C:/Jurix/.github/workflows/ci.yml` somente gates aprovados. Não substituir fixture tests por live Ollama não determinístico obrigatório em todo PR.

1. Runner em base descartável cria sessões/usuário sintéticos: perguntar→chunks→fontes depois final→F5, retry/queda, stop, links lei base/artigo marcado, fontes agrupadas, delete, pesquisa, settings, coleção, detalhe/árvore/compare. Cada assert identifica rota e estado.
2. Matrix360/768/1280/1920 e320reflow; zoom real200%, claro/escuro/reduced-motion, Tab/Shift+Tab/Escape, focus-return, disabled/loading/errors/empty. Checar overflow e alvos; complemento manual de leitor de tela, não “axe passou=AA”.
3. Screenshots só de fixtures sem dados privados; baseline revisado, não atualizar automaticamente após falha. Indicar desktop/touch/browser/version.
4. Medir bytes transferidos/compressão por rota, requests, LCP/CLS laboratório e latência de interações medida; INP de campo não é atestado por script único. Referências2.5s/200ms/0.1 são objetivos, reportar máquina e n.
5. CI: lint/format/arquitetura, SQLite+PostgreSQL, nodefixtures, contrato; live Ollama/cloud/visual manual como job opt-in/release e relatório separado. Secrets nunca em artifacts.

Aceite: matriz tem passou/falhou/não executado com motivo e evidência; release bloqueia falhas centrais, não skips ocultos. Verificação: runner `--help` primeiro, depois base audit explícita; gates completos. Rollback/se falhar: regras comuns; não mexer nos thresholds para silenciar erro.

### RP-047 — Modelo de versões jurídicas com intervalos

Achados: IA-009. Entrega estrutural futura; G; alto; depende RP-016, RP-019, RP-020, RP-044. Executar somente após aprovação do desenho temporal por humano; marco janeiro/2027.

Arquivos: `C:/Jurix/src/apps/legislation/models.py`; criar `C:/Jurix/src/apps/legislation/migrations/0019_legal_text_versions.py`, `C:/Jurix/src/tests/test_legal_text_versions.py`, `C:/Jurix/docs/temporal-version-contract.md`. Não backfill automático com data presumida.

1. NormaTextVersion e DeviceTextVersion imutáveis com identidade, valid_from/valid_to semiaberto, data/desconhecimento, texto/hash, eventos aprovados, fonte e build version. Versões desconhecidas não se encaixam artificialmente em intervalo.
2. Constraints evitam intervalo invertido; overlap validado no serviço e PostgreSQL quando aplicável. Separar tempo de efeito jurídico do timestamp da extração/registro.
3. Documento define revogação parcial/total, vacatio e retificação sob aprovação humana; fixtures cobrem duas alterações no mesmo dia e data desconhecida.

Aceite: schema registra redação e origem sem falsa cronologia; nenhuma consulta legada perde texto atual. Verificação: novo teste em ambos bancos + schema. Rollback/se falhar: regras comuns de migrations/dados; sem regra jurídica aprovada, deixar adiada.

### RP-048 — Materializar versões por eventos aprovados

Achados: IA-009, COD-002. Futura; G; alto; depende RP-047, RP-015.

Criar `C:/Jurix/src/processing/temporal_materializer.py`, `C:/Jurix/src/apps/ingestion/management/commands/build_temporal_versions.py`, `C:/Jurix/src/tests/test_temporal_materializer.py`. Não escrever no texto histórico original nem processar corpus real por default.

1. Ordenar efeitos juridicamente conhecidos e aprovados; produzir versão imutável por boundary com proveniência/event IDs e hash.
2. Default comando dry-run/fixture; conflitos simultâneos/unresolved invalidam somente conjunto afetado e geram revisão, não ordenação arbitrária por PK.
3. Reexecução mesmo input/buildversion é idempotente; mudança de aprovação cria novo build auditável, preservando anterior.

Aceite: antes/depois deALTERA/REVOGA/ADICIONA reproduz fixtures revisadas; partial afeta só alvo. Verificação: novo teste + consolidação/temporal completos. Rollback/se falhar: regras comuns; build real exige backup e autorização.

### RP-049 — RAG e comparação usam versão vigente na data

Achados: IA-009. Futura; G; alto; depende RP-048, RP-024, RP-040.

Arquivos: `C:/Jurix/src/processing/temporal_scope.py`, `C:/Jurix/src/processing/adaptive_rag_service.py`, `C:/Jurix/src/apps/legislation/temporal_api.py`, `C:/Jurix/src/apps/legislation/templates/legislation/norma_compare.html`, `C:/Jurix/src/tests/test_temporal_retrieval_v5.py`; criar `C:/Jurix/src/tests/test_temporal_answer_versions.py`.

1. as_of seleciona versão materializada e intervalo; fonte/claim/cache incluem version ID/hash. Vetor de texto atual não substitui silenciosamente texto histórico.
2. Se versão/embedding não existe, lexical sobre versão exata ou limitação explícita; nunca respostas atuais travestidas de históricas.
3. Comparação por duas datas usa semantic diff estrutural de RP-040 e evidencia eventos aprovados. Unknown permanece indisponível como em RP-017.

Aceite: mesma pergunta em duas datas retorna respectivas redações e fontes auditáveis; cache não mistura versões. Verificação: novo teste + temporal/contrato/cache e evaluator municipal. Rollback/se falhar: regras comuns; manter bloqueio de RP-017 onde cobertura insuficiente.

### RP-050 — Medir escala antes de escolher índice/FTS

Achados: PERF-001, OPS-001. Média estrutural; G; alto; depende RP-043, RP-011, RP-045.

Arquivos: `C:/Jurix/scripts/vector_search_benchmark.py`; criar `C:/Jurix/scripts/lexical_scale_benchmark.py`, `C:/Jurix/docs/performance/retrieval-scale.md`, `C:/Jurix/src/tests/test_retrieval_benchmark_contract.py`. Não gerar100kdispositivos no banco real nem habilitar índice sem EXPLAIN/revisão.

1. Seed sintético10k/100k no banco audit, com filtros tipo/ano/vigência e distribuição declarada; não usar apenas documentos repetidos para afirmar recall jurídico.
2. Medir baseline lexical/pgvector com EXPLAIN ANALYZE BUFFERS, latência n≥30, consumo/máquina/cache quente/frio e Recall@k contra conjunto conhecido.
3. Comparar PostgreSQL FTS/trigram e índice vetorial suportado instalado em experimento isolado; reportar custo de write/build/filter recall. Escolher melhoria somente com ganho medido e fallback SQLite mantido.
4. Mudança de produção de índice/ranking é nova tarefa revisada, não consequência automática do benchmark.

Aceite: relatório reproduzível separa números medidos de recomendação; nenhum SLA inferido do corpus10normas. Verificação: novo teste + runner audit e commands vector existentes. Rollback/se falhar: parar experimento isolado; preservar dados reais.

## 5. Cobertura e decisões humanas que NÃO podem ser substituídas por código

- IA-001→RP-007; IA-002→RP-008/009; IA-003→RP-005; IA-004→RP-010/011/032; IA-005→RP-012; IA-006→RP-010/013; IA-007→RP-031; IA-008→RP-016/039; IA-009→RP-017/047–049; IA-010→RP-023/024/032; IA-011→RP-004/044/045.
- COD-001→RP-021/022; COD-002→RP-014/020; COD-003→RP-015; COD-004→RP-019–022; COD-005→RP-018; COD-006→RP-028–030; COD-007→RP-023/025; COD-008→RP-026; COD-009→RP-041/042.
- SEC-001→RP-001; SEC-002→RP-002; SEC-003→RP-035. OPS-001→RP-043/046; PERF-001→RP-050.
- UX-001→RP-003; UX-002→RP-030; UX-003→RP-033; UX-004→RP-034; UX-005→RP-024/032/040; UX-006→RP-006; UX-007→RP-027. UI-001→RP-038/040; UI-002→RP-016/039; UI-003→RP-033/036/037; A11Y-001→RP-036/039/046.

Dependências não resolvidas que exigem pessoas/ambiente: revisor de20normas/gold, política aprovada de vigência, configuração real de endpoints permitidos/auth, janela debackup/reparação, credenciais voluntárias para cloud, orçamento de hardware/experimentos e aprovação visual. Luna pode entregar instrumentos e indicar bloqueio, não simular essas decisões.

### Marcos futuros do escopo 2026–2027, fora da correção imediata

Não executar automaticamente após RP-050; preparar backlog no mês pertinente e revisar escopo/hardware com orientador.

- Fevereiro: comparar local/nuvem com o mesmo gold congelado, configuração declarada, qualidade revisada, TTFT/tempo final/custo e decisão de privacidade. A compatibilidade já suportada é ponto de partida, não resultado.
- Março: experimento AirLLM/modelo>30B, versões/máquina/VRAM/RAM/tokens por segundo/estabilidade. Não instalar por “revamp” nem exigirGPU para fluxo normal.
- Abril: pelo menos500exemplos revisados com splits/licenças e LoRA/QLoRA controlados, comparação com modelo base. Não misturar exemplos de avaliação no treinamento.
- Abril/maio: classificação sensível e mascaramentoPII com substituição estável; avaliar vazamento, qualidade, coerência e recall. Não inventar anonimização garantida por regex.
- Junho/agosto: notebooks/configs/artefatos públicos revisados, vídeo e artigo. Guardar hashes dos resultados e corrigir README para o que foi realmente medido.

## 6. Critérios finais de entrega da implementação

1. Relatório por tarefa: status, achado ainda presente?, diff, comando/exit code, screenshot quando pertinente e pendências. Contagem de testes não substitui matriz de cenários.
2. Gates A–F cumpridos para produto experimental mais confiável; G explicitamente adiada ou aprovada, sem alegar RAG temporal pronto por simples filtro de data.
3. Antes/depois dos mesmos fluxos e fontes públicas/sintéticas; avaliação visual clara/escura/mobile real. Core Web Vitals de campo e WCAG integral continuam sujeitos a auditoria própria.
4. Pesquisa: corpus e gold revisados, métricas e protocolos reproduzíveis; se intervenção humana ainda falta, nota de pesquisa não sobe automaticamente por aumento de código.
5. Estado Git final comparado ao inicial. Nenhum arquivo/config/dado preexistente descartado. Commit/push/merge somente na autorização daquela etapa.

## 7. Prompt inicial para o Luna

```text
Leia C:/Jurix/docs/audit/2026-10-01/JURIX_RESEARCH_PRODUCT_REASSESSMENT.md
e C:/Jurix/docs/audit/2026-10-01/JURIX_LUNA_IMPLEMENTATION_2026-10-01.md.
Use GPT 6 Luna em alto. Trabalhe no workspace atual, sem clone nem sincronização.
Primeiro confirme branch, HEAD, status e diff, preserve as mudanças locais e rode
o baseline. Confira se RP-001 ainda se aplica. Se o usuário autorizou a etapa
de implementação, execute somente RP-001, verifique e entregue diff/resultados.
Não execute apply de dados, push, merge ou troca de branch. Commit local só com
autorização específica. Pare para revisão após RP-001; a próxima tarefa depende
do aceite, não do seu julgamento de que tudo provavelmente está bem.
```

Depois de aprovar a primeira tarefa, o usuário pode autorizar fases inteiras com gates; tarefas de grounding, migrations/SSE, reparação e gold continuam com revisão explícita. Essa cadência evita transferir ambiguidades jurídicas a um modelo menos capaz.
