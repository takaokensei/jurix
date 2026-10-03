# Jurix — plano mestre de implementação proposto (02/10/2026)

## Escopo e autorização

Planejamento sobre **C:/Jurix, branch main**, HEAD **3d6d428e5a92f9c516418018e21fe6bf11a90d41**, incluindo 39 alterações tracked preexistentes. Sem correções da aplicação nesta auditoria. A criação deste documento não autoriza implementar, fazer commit, trocar branch ou modificar dados.

Fonte de evidência: [auditoria completa](C:/Jurix/docs/audit/JURIX_FULL_AUDIT.proposed.md), [baseline](C:/Jurix/docs/audit/2026-10-02/git-baseline.json) e [verificação final](C:/Jurix/docs/audit/2026-10-02/git-final.json). Execução exata por tarefa: [guia Luna](C:/Jurix/docs/audit/JURIX_LUNA_EXECUTION_GUIDE.proposed.md). Layout/tokens/estados: [design system](C:/Jurix/docs/audit/JURIX_DESIGN_SYSTEM_SPEC.proposed.md).

Há **27 achados comprovados** e **28 tarefas atômicas**. Nem todos são bugs de aparência: PDF íntegro, validade das claims, cobertura honesta e cancelamento pertencem à experiência do usuário. Não prometer “qualidade Apple” somente por trocar cor e raio.

## Decisões consolidadas

- Manter Django/templates/JavaScript modular. Nenhum React, fonte nova, icon pack, serviço pago ou schema novo necessário para as tarefas aprovadas.
- Preservar a experiência moderna já existente: shell unificado, menus de conversa, fontes agrupadas, copyMarkdown, URL estável, ausência de F5 para revelar fontes. Regressões reais apenas, não reproduzir correções antigas desnecessariamente.
- Follow-up já resolve o contexto da lei no probe. Corrigir o falso claim de referência, **não** reescrever memória por suposição.
- Overview já ampliou recuperação: 24 dispositivos/8 artigos no caso pequeno. Não aumentar top-k global por reflexo; corrigir grounding e truncamento.
- Fontes/cópia devem revelar-se juntas **depois de validação**, com fade discreto, conforme preferência mais recente; sources continua associando IDs internamente. Streaming bruto não validado permanece oculto.
- Ausência de evidência não é falha a esconder. Distinguir norma não localizada no corpus, insuficiência de evidência e erro do provedor; oferecer próximo passo útil sem inventar interpretação.
- Ranking do histórico fora de escopo. Ordenação por data de publicação já existe e é preservada. IDs T-014/T-016 deste plano não representam as tarefas antigas de mesmo número.
- Vigência atual não é deduzida somente de data de início de vigência.
- Dados reais não são reparados automaticamente. T-027 prepara e testa procedimento reversível em QA.
- Uma mudança coerente por tarefa; um commit local por tarefa **somente após autorização futura**. Nenhum push/merge.

## Porta e serviços

Navegação real foi feita em **http://127.0.0.1:8006** sobre cópia SQLite temporária. Não confundir com a porta8005 do usuário nem com Docker8000. [audit_server.py](C:/Jurix/docs/audit/2026-10-02/audit_server.py) inicia ambiente de auditoria isolado; não representa configuração production-grade.

Ollama respondeu. PostgreSQL/Redis estavam parados e Celery unhealthy; não foram iniciados para evitar consumir fila real. Readiness503/liveness200. Testes independentes foram executados; integração desses serviços continua gate operacional. Antes de rodá-la: usar dados sintéticos, fila QA vazia e confirmar endereços/banco em processo isolado, sem exibir credenciais.

## Priorização por impacto × esforço

Quick wins (P, impacto alto): T-002 ações da norma; T-003 diff; T-004 busca; T-005 referência pura; T-006 cobertura; T-007 correspondência exata; T-008 pill móvel; T-010 temporalidade. T-009 e T-024 são pequenos, mas com prioridade de experiência/integridade inferior ao PDF.

T-001 é primeira mesmo com esforço M: **a exportação perde conteúdo jurídico**, achado crítico. Melhorias estruturais: T-011–T-019. Refatoração e ambiente: T-020–T-024. Mudanças grandes com revisão: T-013, T-025, T-026. Fechamento QA: T-027–T-028.

A ordem numérica é a sequência padrão para Luna; dependências abaixo permitem reorganização somente após revisão. Não misturar upgrade de dependência, design tokens e grounding no mesmo commit.

## Fase 1 — Integridade do documento e quick wins

Objetivo: Eliminar perda de texto e falhas pequenas com evidência reproduzível antes de ampliar a interface.

Achados cobertos: UX-A-008, COD-A-002, UX-A-003, UX-A-004, UX-A-001, IA-A-002, IA-A-004, IA-A-005, UI-A-001, UX-A-006, UX-A-007.

Dependências: Revalidação do baseline, autorização de implementação e ambiente QA.

Riscos e revisão: PDF exige regressão textual e visual; parser não pode confundir números/artigos; grounding deve continuar rejeitando fatos falsos.

Tarefas, em ordem:

- **T-001 (M)** — Impedir perda de texto ao exportar PDF. Dependência: Nenhuma; revalidar depois da T-020.
- **T-002 (P)** — Restaurar ações secundárias da norma em desktop. Dependência: Nenhuma.
- **T-003 (P)** — Alinhar incisos OCR e consolidado no diff. Dependência: Nenhuma.
- **T-004 (P)** — Aceitar referências formatadas na biblioteca. Dependência: Nenhuma.
- **T-005 (P)** — Excluir referências puras da lista de claims sem dispensar fatos. Dependência: Nenhuma.
- **T-006 (P)** — Registrar truncamento real na cobertura do contexto. Dependência: Nenhuma.
- **T-007 (P)** — Distinguir recuperação exata de similaridade. Dependência: Nenhuma.
- **T-008 (P)** — Conter ações de fontes em qualquer coluna. Dependência: Nenhuma.
- **T-009 (P)** — Criar título identificável para pergunta formatada recusada. Dependência: T-004.
- **T-010 (P)** — Qualificar situação temporal na norma. Dependência: Nenhuma.

Critério de conclusão da fase: PDF íntegro em todas as páginas; ações descobríveis; busca formatada funcionando; referência pura não vira claim; cobertura parcial explicitada; pill móvel sem clipping; temporalidade qualificada.

Verificação: reproduzir cada achado antes, rodar testes direcionados e depois suíte Python/JS da fase; guardar screenshots/saídas sanitizadas. Se um critério não passar, interromper a liberação e registrar o bloqueio, sem ampliar escopo.

## Fase 2 — Recuperação jurídica, rastreabilidade e ergonomia estrutural

Objetivo: Fazer a mesma referência jurídica funcionar na pesquisa, no assistente e nas fontes; reduzir densidade sem esconder controles.

Achados cobertos: UX-A-002, IA-A-003, IA-A-001, UI-A-005, UI-A-002, UI-A-003, UI-A-004, A11Y-A-001, PERF-A-001.

Dependências: T-004/T-005/T-006/T-007/T-008/T-002 conforme dependência individual.

Riscos e revisão: T-013 afeta segurança jurídica e precisa revisão do Sol/humana. Claims compostos não podem mascarar ausência de condição. Sources recebidos cedo não significam fatos já validados.

Tarefas, em ordem:

- **T-011 (M)** — Resolver norma exata antes da pesquisa por assunto. Dependência: T-004.
- **T-012 (M)** — Não gerar resposta com leis substitutas quando a norma exata falta. Dependência: T-004,T-006.
- **T-013 (G)** — Validar sínteses de incisos por família de artigo sem enfraquecer segurança. Dependência: T-005,T-006.
- **T-014 (M)** — Expor associação entre claims verificados e fonte. Dependência: T-007,T-013.
- **T-015 (M)** — Reduzir composer móvel sem perder controles. Dependência: T-008.
- **T-016 (P)** — Compactar cabeçalho da biblioteca normativa. Dependência: T-004.
- **T-017 (M)** — Tornar índice normativo tocável sem produzir mural de chips. Dependência: T-002.
- **T-018 (M)** — Usar renderer canônico para conversa temporária. Dependência: Nenhuma.
- **T-019 (M)** — Mostrar espera e recusa com motivo útil sem rascunho jurídico. Dependência: T-012,T-013,T-014.

Critério de conclusão da fase: Consulta exata prioriza a norma; norma ausente gera zero chamadas ao LLM; síntese multi-inciso válida passa e síntese falsa falha; fonte explica o claim; composer compacto; menus/foco consistentes; feedback honesto de espera/recusa.

Verificação: reproduzir cada achado antes, rodar testes direcionados e depois suíte Python/JS da fase; guardar screenshots/saídas sanitizadas. Se um critério não passar, interromper a liberação e registrar o bloqueio, sem ampliar escopo.

## Fase 3 — Dependências e redução de dívida técnica

Objetivo: Validar ambiente reprodutível, remover hotspot e centralizar fundações sem migrar framework.

Achados cobertos: SEC-A-001, SEC-A-002, COD-A-001, PERF-A-003, COD-A-003.

Dependências: T-022 depende de T-005/T-006/T-012/T-013; T-023 depende de T-008/T-015/T-016. T-020/T-021/T-024 podem antecipar-se depois de T-001 se houver revisão do risco.

Riscos e revisão: Pins precisam confirmação oficial de compatibilidade; upgrade Puppeteer major pode afetar fixtures. Não mudar a .venv original ou incluir dependência de teste no bundle. Aliases CSS previnem regressão.

Tarefas, em ordem:

- **T-020 (M)** — Alinhar dependências Python num ambiente QA separado. Dependência: Nenhuma.
- **T-021 (M)** — Atualizar cadeia de testes browser sem fix--force. Dependência: Nenhuma.
- **T-022 (M)** — Extrair orquestração de geração/validação de RAGService. Dependência: T-005,T-006,T-012,T-013.
- **T-023 (M)** — Centralizar tokens e retirar downloads de fontes desnecessários. Dependência: T-008,T-015,T-016.
- **T-024 (P)** — Validar entradas de coleção no servidor. Dependência: Nenhuma.

Critério de conclusão da fase: Auditoria de dependências QA e testes completos registrados; arquitetura passed:true sem elevar limite; fonts externas removidas sem perda de legibilidade; servidor valida coleção e ownership.

Verificação: reproduzir cada achado antes, rodar testes direcionados e depois suíte Python/JS da fase; guardar screenshots/saídas sanitizadas. Se um critério não passar, interromper a liberação e registrar o bloqueio, sem ampliar escopo.

## Fase 4 — Cancelamento completo e seguro

Objetivo: Separar abort do navegador de cancelamento autorizado do trabalho upstream.

Achados cobertos: PERF-A-002.

Dependências: T-019 e T-022; cache QA verificado, com contrato de backend compartilhado para release multiworker.

Riscos e revisão: Nova API exige CSRF, assinatura, autorização e isolamento por turno. Cancelamento entre tokens não equivale a interrupção instantânea de leitura bloqueada; timeout limitado é gate explícito. Revisar cada uma das duas tarefas antes da próxima.

Tarefas, em ordem:

- **T-025 (G)** — Criar contrato de cancelamento por turno com autorização. Dependência: T-019,T-022.
- **T-026 (G)** — Propagar cancelamento autorizado até consumo do LLM. Dependência: T-025.

Critério de conclusão da fase: Outro usuário/sessão não cancela turno alheio; token expirado é recusado; cancel fecha consumo upstream sem salvar completed nem iniciar retry; terminal único e retry posterior funcional.

Verificação: reproduzir cada achado antes, rodar testes direcionados e depois suíte Python/JS da fase; guardar screenshots/saídas sanitizadas. Se um critério não passar, interromper a liberação e registrar o bloqueio, sem ampliar escopo.

## Fase 5 — Preparação de reparo de dados e aceitação integrada

Objetivo: Demonstrar saneamento reversível em cópia QA e transformar falhas vistas no navegador em regressões.

Achados cobertos: UX-A-005, COD-A-002.

Dependências: T-020 para reparo QA; demais tarefas aceitas para gate integrado, com pendências operacionais nomeadas.

Riscos e revisão: Não confundir cópia QA de navegador com banco usado pelo manage.py. Reparo real exige nova autorização e manifesto aprovado. Sem runtime PostgreSQL/Celery, não declarar aplicação completamente validada.

Tarefas, em ordem:

- **T-027 (M)** — Preparar reparação reversível dos sete colofões sem tocar acervo real. Dependência: T-020.
- **T-028 (M)** — Adicionar smoke integrado dos fluxos que a suíte atual não cobre. Dependência: T-001–T-027 aceitas; gates operacionais QA podem permanecer explicitamente pendentes.

Critério de conclusão da fase: Sete colofões separados na cópia QA sem sobrescrever datas em conflito; PDF/busca/overview/follow-up/fontes/cópia/F5/teclado/matriz visual cobertos; gates não executados explicitados.

Verificação: reproduzir cada achado antes, rodar testes direcionados e depois suíte Python/JS da fase; guardar screenshots/saídas sanitizadas. Se um critério não passar, interromper a liberação e registrar o bloqueio, sem ampliar escopo.

## Ordem de execução global e gates de revisão

1. Obter autorização de implementação; confirmar baseline real e arquivos não rastreados. Ler o guia completo. Não trocar branch para “a mais avançada” sem autorização/revalidação.
2. Executar **somente T-001** primeiro. Entregar PDF QA completo, extração textual, imagens de todas as páginas, diff e testes. Esperar revisão do usuário antes da T-002 se essa for a autorização adotada.
3. T-002 → T-003 → T-004 → T-005 → T-006 → T-007 → T-008 → T-009 → T-010.
4. T-011 → T-012 → **T-013 (revisão de segurança jurídica obrigatória)** → T-014 → T-015 → T-016 → T-017 → T-018 → T-019.
5. T-020 → T-021 → T-022 → T-023 → T-024. Não promover o ambiente QA de dependências à instalação original automaticamente.
6. **T-025 (revisão de autorização)** → **T-026 (revisão de cancelamento/races)**.
7. T-027 dry-run e reparação somente QA → T-028 regressão integrada.
8. Entregar checklist com gates pendentes de dados reais, staging, PostgreSQL/Redis/Celery, zoom/tecnologia assistiva e testes de carga. Solicitar autorizações específicas para atividades operacionais, não executar por inércia.

## Rede de segurança e baseline esperado

Executado nesta auditoria: pytest **805 passed / 6 skipped**, cobertura71,69%; npm test exit0 (inclui30browser fixture tests); Ruff/check/doc gate verdes. Arquitetura falha por867/850linhas em rag_service.py. manage.py check --deploy reportou3erros e7warnings em desenvolvimento — não é um teste de produção.

Resultados e métodos em [verification-results.json](C:/Jurix/docs/audit/2026-10-02/verification-results.json). A implementação precisa executar novamente: “passou na auditoria” não é evidência pós-patch. Não rebaixar assertivas nem alterar threshold de cobertura para maquiar regressões.

## Critérios de saída observáveis

- PDF contém artigo inicial, intermediário e final com acentos, números, negações e condições; nenhuma página de conteúdo silenciosamente vazia.
- “Lei nº8.206/2026” funciona em /normas/ e /pesquisa/ sem depender de JS.
- Ações secundárias descobríveis por teclado em desktop/móvel; índice preserva hashes de todos os dispositivos.
- Overview usa evidências da norma correta; artigo exato e follow-up não falham por uma linha contendo só referência.
- Claims falsas/condições omitidas continuam rejeitadas. Corpus incompleto e contexto truncado não são classificados como completos.
- Fonte exata não aparece como0% relevante; contribuição mostra claim validada ou identifica somente trecho recuperado.
- Fontes/copy aparecem sem F5, após validação; fade respeita reduced-motion; Markdown copiado preserva URL oficial e referências.
- Sidebar não tem controles aninhados; composer e fontes cabem em320/360/768/1280/1920. Não esconder overflow para aparentar conformidade.
- Coleção valida comprimento/IDs/ownership no servidor.
- Cancelamento por turno passa autorização, TTL, corrida done/cancel e provedor silencioso; nenhum rascunho é salvo como completed.
- Dependências QA alinhadas e advisories resolvidos ou exceções documentadas; arquitetura passa sem aumentar limite.
- Toda tela/estado no inventário termina com evidência de teste ou “não testado em runtime” e motivo. Não converter NV em conforme.

## Fora do escopo de patches e hipóteses

Não criar tarefas para hipóteses sem reprodução: N+1 em escala, INP/LCP/CLS reais, desempenho pgvector, upstream Ollama interrompido fisicamente, toda a área administrativa/autenticada, uploads maliciosos, conjunto completo OWASP. Existem testes unitários e sinais de segurança, não certificação/pentest.

Operacional antes de release: QA PostgreSQL/Redis/Celery; fila isolada; staging settings e check --deploy; política de ingestão/atualização do corpus; reparo de sete colofões reais com manifesto/backup/aprovação; medir CWV e carga; zoom200%/320px e leitor de tela. HIG completo/M3 site são parcialmente não verificados por conteúdo JS; usar fontes primárias acessíveis registradas, sem alegar aderência universal.

## Modelo de entrega por tarefa

Registrar: tarefa/achados, estado de entrada, arquivos/hunks próprios, reproducer, diff, comandos e exit codes, screenshots QA, resultado de todos os critérios, limitações e rollback exato do próprio commit se autorizado. Nunca incluir chave/API/password ou dados privados.

Somente depois de fechar os gates de integridade e segurança fazer uma rodada estética adicional guiada pelas imagens comparativas — sem usá-la para esconder os achados não resolvidos. Este plano melhora a superfície com T-008/T-015/T-016/T-017/T-018/T-023, mas não promete uma nota futura ou production-grade antes da evidência.

