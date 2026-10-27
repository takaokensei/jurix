# MVP — Consulta de Normas Municipais Consolidadas (Natal/RN)

> **Status**: RASCUNHO, aguarda aprovação do dono.

## 1. Problema e Público-Alvo

Procuradores e assessores da Procuradoria-Geral do Município (PGM) de Natal/RN precisam consultar a redação consolidada de leis e decretos municipais sabendo, por artigo e dispositivo, quais trechos estão vigentes, alterados ou revogados e qual ato normativo produziu cada alteração.

Hoje o motor determinístico existe em `src/processing/consolidation_engine.py`, mas a aplicação ainda não entrega uma visão consolidada auditável e bloqueada contra extrações não verificadas (*fail-closed*).

## 2. Escopo Fechado do MVP (O que ENTRA)

1. **Consulta de texto consolidado por norma e por artigo**:
   - Busca e visualização de norma municipal pelo tipo, número e ano, com navegação direta aos artigos e dispositivos (`caput`, parágrafos, incisos, alíneas).
2. **Estado explícito por dispositivo**:
   - Cada dispositivo exibe obrigatoriamente um dos 4 estados:
     - `VIGENTE` — texto base ou alterado cuja cadeia de eventos modificadores foi integralmente validada por humano (`validado=True`).
     - `ALTERADO` — dispositivo com nova redação validada, mantendo referência explícita ao ato modificador.
     - `REVOGADO` — dispositivo revogado por ato posterior validado, preservando histórico/anotação da norma revogadora.
     - `NAO_VERIFICADO` — norma sem extração humana concluída ou dispositivo afetado por evento pendente de validação (`validado=False` ou `unresolved`).
3. **Fonte oficial visível**:
   - Exibição obrigatória do metadado da fonte oficial (Diário Oficial do Município / DOM, data de publicação, identificador do documento de origem e link/hash do artefato fonte).
4. **Política *Fail-Closed* estrita**:
   - Sem validação humana (`validado=True` em todos os eventos aplicáveis e documento base verificado), **nenhum dispositivo pode ser exibido como `VIGENTE`**.
   - Eventos modificadores com `validado=False`, citações sem aspas verificáveis ou alvos não resolvidos nunca alteram silenciosamente o texto vigente e rebaixam o estado de confiabilidade para revisão explícita.

## 3. Fora do Escopo do MVP (O que NÃO ENTRA)

- **Chat generativo / RAG conversacional**: respostas geradas por LLM não fazem parte do caminho crítico do MVP de consolidação.
- **Polimento estético de frontend**: animações, temas visuais extras, refatorações cosméticas de CSS/JS ou novos fluxos de onboarding.
- **Benchmarks acadêmicos e suítes pesadas de avaliação de LLM**: execuções de RAGAS, baterias de latência de modelos generativos e relatórios de PIBIC.

## 4. Critérios de Pronto do MVP (Definition of Done)

1. Motor `src/processing/consolidation_engine.py` coberto por testes fim a fim determinísticos (`REVOGA`, `ALTERA`, `ADICIONA`, `SUBSTITUI` em ordem cronológica) e validação explícita da regra *fail-closed* para eventos não validados (`T-009`).
2. Endpoint/view somente leitura que entrega a norma consolidada com estado por dispositivo, metadados da fonte oficial e bloqueio *fail-closed* (`T-010`).
3. Zero dispositivo exibido como `VIGENTE` quando houver extração não validada ou evento pendente na cadeia normativa.
4. Contratos `validate_documentation_contract.py`, `validate_release_contract.py` e `validate_staging_contract.py` passando (código `0`).
