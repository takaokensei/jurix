# Jurix — checklist de QA e liberação

Atualizado em 2026-10-02. Registro da T-028, executado no workspace local `C:\Jurix`, branch `main`. Este checklist não declara conformidade ou prontidão de produção; registra somente verificações feitas e gates pendentes.

## Resultado executivo

- **Suíte QA alinhada:** Python completo passou (**873 passed, 6 skipped, 7 warnings**); `npm test` terminou com **exit 0**, incluindo 35 testes de navegador reais. A execução padrão no `.venv` falha somente no gate de dependências porque PyMuPDF 1.24.10 difere do pin 1.28.2; o ambiente original não foi alterado.
- **Fluxos Django de integração:** 2 testes de jornada passaram com banco de teste isolado; nenhum dado de `db.sqlite3` foi usado ou alterado.
- **Smoke de navegador/responsividade com fixture descartável:** passou nas rotas principais, detalhe da norma, árvore e comparação em 320/360/768/1280/1920 px. Sem overflow horizontal global, erros JavaScript ou requests para Google Fonts. Busca rápida abriu por teclado, Escape fechou e devolveu foco; temas claro/escuro foram alternados.
- **Assistente em runtime com snapshot SQLite temporário:** pergunta sobre o Art. 1º da Lei nº 8.206/2026 completou o pipeline local e SSE. Foram observados estados de recuperação/reranking, evento `sources` antes da geração, cinco chunks de texto, finalização e `done` fundamentado. O evento agora mostra imediatamente a fonte com o rótulo “Verificação em andamento”; o drawer pode abrir durante a geração, atualiza o status no mesmo painel após `done`, e fecha com Escape devolvendo o foco ao acionador. Nenhum erro JavaScript foi observado.
- **Ollama:** stream direto do provedor real também concluiu com primeiro token em 460 ms (1 chunk, 2 caracteres). O pipeline RAG acima foi exercitado usando o backend configurado pelo snapshot SQLite local, mas não PostgreSQL/Celery. Zoom de navegador a 200% e leitor de tela seguem pendentes.
- **T-027 — colofões:** numa cópia SQLite isolada, as sete propostas foram aplicadas com manifesto aprovado e backup verificado; artigos ficaram limpos. Nas três divergências SAPL/OCR, todas as datas foram preservadas e as normas mantidas para revisão. O hash da base real permaneceu inalterado. Veja `QA_COLOPHON_REPAIR.md`.
- **Dependências Python em QA isolado:** 24 requisitos conferidos sem pacote ausente ou fora do pin; `pip check` não apontou dependências quebradas. O `.venv` original permanece intocado.

## Matriz dos achados da auditoria

Os IDs e evidências de referência abaixo estão registrados em `JURIX_FULL_AUDIT.proposed.md`. T-028 não reabriu cada achado visual individualmente; a coluna “situação nesta rodada” delimita o que foi e o que não foi revalidado.

| Achados | Evidência/resultados nesta rodada |
| --- | --- |
| UX-A-001–UX-A-008 | Auditoria original preservada; rotas principais revalidadas em navegador QA nos cinco breakpoints. Testes de interação existentes em `npm test` também passaram. |
| UI-A-001–UI-A-005 | Auditoria original preservada; smoke em navegador não encontrou erro de script nem overflow nas rotas exercitadas. Isso não substitui revisão visual humana. |
| A11Y-A-001 | Smoke cobriu foco da busca rápida, Escape, devolução de foco e reduced-motion emulado; zoom a 200% e tecnologias assistivas não verificados. |
| IA-A-001–IA-A-005 | Jornada HTTP cobre catálogo, pesquisa, detalhe, árvore, comparação, API e PDF em corpus de teste; o runtime do assistente exercitou recuperação, SSE, geração fundamentada e abertura/fechamento do drawer sobre SQLite snapshot. PostgreSQL/Celery não foram exercitados. |
| PERF-A-001–PERF-A-003 | Primeira resposta direta Ollama: 460 ms até o primeiro token; não é medida de Core Web Vitals nem de carga. Não foram coletados LCP/INP/CLS nesta rodada. |
| SEC-A-001–SEC-A-002 | Sem novo teste de penetração ou auditoria de segurança nesta rodada; consultar evidências originais da auditoria. |
| COD-A-001 | `scripts/architecture_budget_v2.py`: **passed: true** após extrair a função pura de divisão de chunks para `rag_answer_pipeline.py`; testes direcionados de RAG passaram. |
| COD-A-002 | Coberto pelos 2 testes de jornada Django e smoke de navegador real em 5 larguras, incluindo detalhe, árvore e comparação. |
| COD-A-003 | `ruff check src config`, `manage.py check` e `validate_documentation_contract.py` passaram; ver também achados e evidências originais da auditoria. |

## Verificações executadas

| Comando/verificação | Resultado |
| --- | --- |
| `.venv\Scripts\python.exe -m pytest -q src/tests/test_legal_user_journeys.py --tb=short` | **2 passed** em 1,99 s. Exercita busca exata e pesquisa, detalhe, árvore, comparação, API, exportação PDF e restauração autenticada de conversa/histórico. |
| `.venv\Scripts\python.exe -m pytest -q --tb=short` | **Falhou apenas** `test_security_sensitive_document_dependencies_match_declared_pins`: `.venv` tem PyMuPDF 1.24.10; `requirements.txt` declara 1.28.2. Não foi instalado nem substituído pacote no ambiente original. |
| Ambiente QA temporário `jurix-implementation-qa-20261002\venv`: `python -m pytest -q --tb=short` | **873 passed, 6 skipped, 7 warnings** em 65,44 s; PyMuPDF e demais pins conferidos nesse ambiente separado. |
| Testes direcionados de colofão (ambiente QA) | **5 passed**: manifesto obrigatório/stale, preservação de referências, limpeza em conflito com datas preservadas e parser do artigo final. |
| `npm test` em `tests/js`, com `JURIX_QA_BASE_URL=http://127.0.0.1:8016` e fixture descartável | **Exit 0**; testes de navegador reais passaram (35 no grupo `real.browser`), e o smoke próprio cobriu as rotas/5 larguras e teclado. |
| `npm test` em `tests/js` (reexecução final, sem servidor externo) | **Exit 0**; 35 testes `real.browser` passaram. O smoke que exige `JURIX_QA_BASE_URL` foi executado separadamente com fixture descartável. |
| `tests/js`: fluxo SSE de fontes, após ajuste para visibilidade durante geração | **Passou:** 35 testes reais de navegador, incluindo drawer aberto antes de `done`, estado pendente removido no mesmo drawer após grounding e rascunho provisório não exposto. Os demais testes do pacote também foram reexecutados após a alteração. |
| Navegador Edge headless em `http://127.0.0.1:8017`, snapshot SQLite isolado | Pergunta sobre Art. 1º completou SSE (HTTP 200; `sources` recebido antes dos chunks; 5 chunks; `done` fundamentado). Fontes apareceram sem reload; drawer mostrou 1 evidência da Lei nº 8.206/2026; Escape fechou e devolveu foco; zero erros JavaScript. |
| Smoke adicional de rotas contra o snapshot SQLite local | **Parcial:** `/assistente/` respondeu 200, mas `/normas/3/` respondeu 500 porque a cópia não tinha a tabela `operations_corpusrevision` (migration pendente). Nenhuma migration foi aplicada. A cobertura dessas rotas continuou pelo smoke independente com fixture descartável acima. |
| `ruff check src config`; `manage.py check`; `validate_documentation_contract.py` | Todos passaram. |
| `scripts/architecture_budget_v2.py` | **passed: true**; `rag_service.py` agora fica dentro do orçamento de 850 linhas. |
| `npm audit --omit=dev` em `tests/js` | **0 vulnerabilidades** reportadas nas dependências de produção. |
| `npm audit` em `tests/js` | **0 vulnerabilidades** reportadas, incluindo dependências de teste. |
| `pip-audit -r requirements.txt` no Python QA | **No known vulnerabilities found**; execução consultou advisories e terminou com exit 0. |
| `git diff --check` | **Passou**; Git emitiu apenas aviso de normalização CRLF→LF para `src/llm_engine/ollama_service.py`. |
| Stream Ollama real direto | **Concluído**; primeiro token em 460 ms, 1 chunk / 2 caracteres; não representa um teste RAG ponta a ponta. |

## Próximos passos de liberação

1. Validar o pipeline RAG end-to-end com PostgreSQL/Celery e corpus QA isolado; o runtime desta rodada exercitou o fluxo com SQLite, não substituindo a verificação com PostgreSQL/Celery.
2. Completar zoom de navegador a 200%, inspeção de leitores de tela e revisão visual humana das capturas das telas principais.
3. Manter registrada a evidência de que o servidor QA usou somente SQLite temporário e foi encerrado; não redirecionar smoke para dados pessoais.
4. Liberar somente após revisar os achados abertos da auditoria e evidências atuais. Este checklist sozinho não constitui aprovação de produção.
5. Manter revisão documental/jurídica das datas divergentes das normas 9, 10 e 11 como gate operacional antes de qualquer decisão temporal; a limpeza textual foi testada na cópia QA sem alterar datas.

## Limites de segurança e dados

- Nenhuma migration foi executada por esta rodada.
- Nenhuma escrita foi feita na base real `db.sqlite3`.
- O teste de navegador não foi direcionado a uma instância que pudesse conter conversas ou outros dados pessoais.
- Nenhuma credencial ou valor de configuração secreto é registrado aqui.
