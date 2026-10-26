# Plano mestre de implementação — Jurix

Base: [auditoria de 30/09/2026](JURIX_FULL_AUDIT.md). Este documento planeja; não autoriza alteração de produto nesta etapa. Fonte única: checkout local. A numeração abaixo coincide com [o guia para o Luna](JURIX_LUNA_EXECUTION_GUIDE.md).

## Regra de entrada

Antes de T-001, registrar branch, commit, `git status --short`, diff e testes; não presumir que o estado ainda seja b2c8a2b. Cada tarefa modifica só os arquivos indicados no guia, gera um commit isolado **somente na etapa futura e se o usuário a autorizar**, e é seguida de testes. Se uma pré-condição não for verdadeira, parar. Nenhuma fase deve prometer conformidade WCAG completa sem auditoria assistiva e de zoom.

## Fase 1 — riscos de confiança e segurança (T-001 a T-004)

**Objetivo:** impedir que recuperação insuficiente pareça fundamentação validada, tornar GET seguro, restringir destino HTTP configurável em produção e aplicar filtros antes do corte de busca.

**Achados:** A-IA-001, A-COD-015, A-SEC-016, A-IA-002. **Dependências:** T-001 precede qualquer mudança cosmética de badge; T-004 prepara T-005. **Riscos:** alterar contrato SSE/API, invalidar restauração de conversa, bloquear endpoints locais legítimos em desenvolvimento, mudar ranking. Preservar compatibilidade dos eventos e distinguir `fontes recuperadas` de `fontes que sustentam`.

**Conclusão:** testes de streaming cobrem `grounded=false`, navegação GET não grava sessão, allowlist de produção nega endereço cliente arbitrário, e busca com >50 dispositivos encontra resultado filtrado. Testes Python e JS verdes. Não liberar como concluída a partir de leitura estática apenas.

## Fase 2 — quick wins de UX e acessibilidade (T-005 a T-012)

**Objetivo:** comunicar o modo de recuperação real, reduzir retrabalho na pesquisa/histórico e corrigir controles, mensagens e legibilidade mobile.

**Achados:** A-IA-003, A-UX-004, A-UX-005, A-UX-006, A-A11Y-008, A-A11Y-009, A-UX-007, A-UI-010. **Dependências:** T-005 depois de T-004; T-007 antes de T-014; demais independentes. **Riscos:** regressão de copy juridicamente sensível, âncora inválida quando dispositivo agregado, foco sem indicação em formulário, crescimento vertical do composer. Cada tela é validada em 360/768/1280/1920 px e nos dois temas onde aplicável.

**Conclusão:** rótulo de fallback correto, resultado conduz ao artigo, histórico usa pergunta, copy não promete jurisprudência/coleção de evidência, botão anexo tem papel correto, erro aponta o campo, controles legíveis em 360 px, ajuda legível e sem quebra em zoom 200%.

## Fase 3 — consistência de deploy e escala (T-013 a T-016)

**Objetivo:** preservar tipografia sob CSP estrita e evitar limites silenciosos ou trabalho de CPU não limitado nas telas de dados.

**Achados:** A-UI-011, A-PERF-012, A-PERF-013, A-COD-014. **Dependências:** T-014 após T-007; outras independentes. **Riscos:** licenças de fonte ou diferença visual em produção, mudanças de paginação, diffs grandes incompletos se o limite for escondido, ordenação de normas diferente da expectativa. Medir antes/depois em corpus sintético sem alterar dados reais.

**Conclusão:** nenhum request de fonte bloqueado por CSP no modo de deploy simulado; sessão 501 é recuperável por busca/paginação; comparação longa tem limite visível e tempo medido; leis 9 e 10 do mesmo ano ordenam conforme critério definido, idêntico em web/API.

## Fase 4 — higiene de gate (T-017)

**Objetivo:** remover a falha Ruff I001 já observada sem refatoração de comportamento. **Achado:** A-COD-017. **Risco:** mínimo, mas não usar formatador em todo o repositório. **Conclusão:** `ruff check .`, `pytest -q src/tests`, `npm test` e `manage.py check` passam no ambiente preparado.

## Ordem global e decisão de release

Executar T-001 → T-002 → T-003 → T-004 → T-005 → T-006 → T-007 → T-008 → T-009 → T-010 → T-011 → T-012 → T-013 → T-014 → T-015 → T-016 → T-017. Revalidar o inventário após T-002 e T-004, pois fluxo de sessão e busca podem mudar. Usar screenshots e manifest da auditoria como base comparativa, não como aprovação automática.

**Gate final:** repetir suite, cheque de deploy com settings de produção seguros (sem mostrar segredos), navegador nos quatro viewports, teclado/zoom/reduced-motion e um fluxo real controlado de Ollama/SSE em banco de teste isolado. Segurança SSRF e completude do corpus exigem verificação em ambiente representativo. Não iniciar ingestão SAPL ou modificar corpus de produção para satisfazer o gate.

## Trabalho de validação ainda não convertido em correção

Hipóteses da auditoria: corpus de dez normas versus meta, preview de múltiplos anexos, CWV de campo, dependências vulneráveis e WCAG assistiva. Elas **não** são fatos estabelecidos nem entram como tarefas de código sem reprodução. Criar fixture/ambiente de teste e abrir novos achados com evidência antes de propor patch.
