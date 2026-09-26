# Production readiness — fonte canônica

Esta é a página canônica para o estado de produção do Jurix. Documentos de versões
anteriores são históricos e não devem ser usados como instruções operacionais sem
serem confrontados com este documento e com `docs/current-status.md`.

## Estado

- **Engineering gates:** executados pelo CI de produção.
- **RAG benchmark:** o gate aceita a ausência de corpus revisado; um benchmark jurídico
  humano-revisado continua sendo requisito antes de declarar qualidade jurídica de release.
- **Vector production gate:** verifica configuração/indexação de pgvector quando executado
  contra um ambiente com PostgreSQL disponível.
- **Acessibilidade:** não declarar conformidade WCAG sem auditoria formal.
- **Ingestão:** implementações são separadas por domínio; `tasks.py` é a superfície pública.

## Gates canônicos

| Área | Fonte | Quando usar |
|---|---|---|
| Status de engenharia | `docs/current-status.md` | referência rápida |
| Segurança | `scripts/security_audit_v2.py` | CI/release |
| Arquitetura | `scripts/architecture_budget_v2.py` | CI/release |
| Contratos | `scripts/check_service_contracts_v2.py` | CI/release |
| RAG jurídico | `scripts/run_legal_benchmark_v1.py` | quando houver corpus revisado |
| Vetores | `scripts/vector_production_gate_v5.py` | staging/produção |
| Preflight | `scripts/production_preflight_v2.py` | staging/produção |

## Regra de documentação

Não criar novos `production-readiness-vN.md`, `production-final-vN.md` ou gates paralelos
para a mesma responsabilidade. Se um gate mudar, atualize esta página e a fonte executável
correspondente.

## Release checklist

1. CI de produção verde.
2. Preflight executado contra o ambiente-alvo.
3. Benchmark jurídico revisado por humano disponível, quando a release fizer alegações de
   qualidade jurídica.
4. Vector gate validado contra o PostgreSQL/pgvector do ambiente-alvo.
5. Auditoria manual de UX/acessibilidade concluída quando houver alegação de conformidade.
