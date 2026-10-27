# Índice de Documentação Ativa (`docs/`)

Este diretório contém apenas os contratos operacionais ativos, especificações de produto e relatórios de governança exigidos pelos gates do repositório.

> **Aviso importante para agentes e desenvolvedores**: O subdiretório `docs/archive/` contém histórico congelado (diários de progresso, relatórios antigos e versões `v2` a `v6` substituídas). **Nunca leia nem edite `docs/archive/` por padrão.** Da mesma forma, não leia `docs/ui-audit/` (capturas de tela e artefatos de inspeção visual).

## 1. Pontos de Entrada para Agentes

- [`../AGENTS.md`](../AGENTS.md) — Regras operacionais, comandos rápidos e limites invioláveis.
- [`../STATE.md`](../STATE.md) — Estado real dos subsistemas, métricas do baseline e bloqueadores.
- [`mvp.md`](mvp.md) — Escopo fechado do MVP de consolidação normativa (*fail-closed*).
- [`backlog.md`](backlog.md) — Fila priorizada de tarefas atômicas e verificáveis (`T-009` em diante).

## 2. Contratos Exigidos por Scripts e CI (Não Mover)

Estes arquivos são validados por `scripts/validate_documentation_contract.py`, `scripts/validate_release_contract.py`, `scripts/validate_staging_contract.py` e `scripts/production_gate.py`:

- [`current-status.md`](current-status.md) — Estado factual de prontidão operacional e limitações abertas.
- [`production-readiness.md`](production-readiness.md) — Checklist e critérios de prontidão de produção.
- [`rag-quality-contract-v2.md`](rag-quality-contract-v2.md) — Contrato técnico de qualidade e gates do pipeline RAG.
- [`security-production-matrix.md`](security-production-matrix.md) — Matriz de controles de segurança de produção.
- [`production-validation.md`](production-validation.md) — Evidências e procedimentos de validação de ambiente.

## 3. Guias Operacionais e Arquitetura Ativa

- [`architecture.md`](architecture.md) — Visão arquitetural dos módulos Django, Celery, pgvector e consolidação.
- [`api-reference.md`](api-reference.md) — Referência de endpoints internos e contratos HTTP.
- [`deployment-guide.md`](deployment-guide.md) — Guia de deploy com Docker Compose e variáveis de ambiente.
- [`operations-runbook.md`](operations-runbook.md) — Runbook operacional de manutenção, filas e banco.
- [`security-guide.md`](security-guide.md) — Práticas de segurança, CSP, autenticação e proteção de dados.
- [`testing-guide.md`](testing-guide.md) — Como executar testes Python (`pytest`) e JavaScript (`node --test`).
- [`rag-pipeline.md`](rag-pipeline.md) e [`rag-evaluation.md`](rag-evaluation.md) — Documentação técnica do subsistema RAG.
- [`research/PGM_GOLD_ADJUDICATION.md`](research/PGM_GOLD_ADJUDICATION.md) — Protocolo para adjudicação humana do Corpus Ouro da PGM (referência da tarefa `T-003`).

## 4. Governança de Reorganização (`docs/agents/`)

- [`agents/reorg-manifest.csv`](agents/reorg-manifest.csv) — Manifesto completo dos 1.678 arquivos rastreados com decisão e evidência.
- [`agents/reorg-report.md`](agents/reorg-report.md) — Relatório executivo da reorganização para desenvolvimento autônomo.
