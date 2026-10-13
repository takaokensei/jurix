# Estado atual do projeto

Esta página é a fonte de status de engenharia. Roadmaps históricos no README não
devem contradizer esta página.

## Infraestrutura

- Django: implementado.
- PostgreSQL/pgvector: implementado.
- Redis/Celery: implementado.
- Ollama: implementado.
- Storage local/S3: implementado.
- Gates de produção: implementados.

## Qualidade RAG

- Retrieval híbrido: implementado.
- Grounding determinístico original: implementado.
- Grounding estrito v2: implementado neste hardening.
- Benchmark jurídico revisado: **pendente de dados e aprovação humana**.

## Performance

- Cache de embeddings/respostas: implementado.
- Índice vetorial: deve ser verificado/criado com `ensure_vector_index`.
- Benchmark operacional de pgvector: disponível.

## Operação

- Auditoria de storage: read-only.
- Limpeza de anexos expirados: comando separado, dry-run por padrão.
- Configuração de produção: validada por checks Django.

## UX

A interface existente deve ser validada manualmente em teclado, leitor de tela,
mobile, erro de dependência e streaming interrompido. Este repositório não deve
atribuir conformidade WCAG sem evidência de auditoria.

### Auditoria parcial de contraste — tema escuro

Em 2026-09-27 foram calculados os pares dos tokens principais do workspace
contra suas superfícies: `#F8FAFC`/`#081220` = 17,96:1,
`#94A3B8`/`#081220` = 7,33:1, `#60A5FA`/`#081220` = 7,39:1 e
`#3B82F6`/`#081220` = 5,11:1. O uso de `#64748B` como texto pequeno tinha
3,95:1 e foi substituído pelo token de texto muted no workspace.

Essa medição cobre tokens e componentes auditados nesta etapa; não constitui
uma declaração de conformidade WCAG da aplicação inteira. Permanecem pendentes
os componentes legados, estados claros/escuros alternativos e uma auditoria
automatizada de todas as combinações efetivamente renderizadas.

## Piloto PGM — QA local (2026-10-10)

- O smoke `tests/js/pgm-workflow-smoke.mjs` passou na instância QA `:8282` com **21/21 verificações**, incluindo busca em PDFs candidatos reais, PDF, fontes, teclado, temporalidade, exportação e proposta SAPL. Um smoke focado perguntou sobre atualidade do Art. 18 da LC 120/2010: a resposta ficou inconclusiva, apresentou PDF local + registro SAPL e não confundiu proposição com norma promulgada. A build respondeu sem erros de página.
- O snapshot QA count-only registra **6.664 PDFs candidatos**: 6.566 extrações mais recentes completas, 97 parciais e 1 ilegível; 40 documentos têm uma extração anterior adicional. Não há extrações aceitas nem normas consolidadas. Esses contadores não validam identidade, vigência ou cobertura jurídica.
- O teste de rolagem da resposta real confirmou o fim do texto e as fontes acima do composer; captura sanitizada e relatório estão no diretório temporário `jurix-pgm-goal-qa-20261008\read-only-dom-inspection-20261010\pgm-article-currentness-scroll-20261010`. A porta `:8282` é apenas a instância QA observada, não endereço estável de release.
- A build disclosure do workspace mostra versão/revisão explicitamente fornecidas ou “build local não identificado”; perfil e escopo de corpus aparecem sem inferir um commit a partir do Git.
- Nesta continuação: a suíte Python integral no runner QA isolado concluiu **1.750 passed, 6 skipped, 0 falhas, 8 warnings em 296,90 s**. `tests/js/run-tests.mjs` terminou com exit 0; os 41 testes de browser real passaram, enquanto três cenários de revisão/coleções autenticadas ficaram skipped por exigirem credencial temporária autorizada. Também passaram `test_qa_archive_rag.py` (**144**), testes do cliente DOM/sync/recovery/schedule (**28**), arquitetura (`passed=true`), contrato documental, Ruff e `manage.py check`.
- A consulta somente leitura do catálogo DOM retornou 8 edições em outubro/2026; o health do sync permanece `not_configured`, apesar de um worker QA respondendo. Não iniciei beat/sync nem baixei ou gravei edição.
- A nota de segurança do piloto está em `docs/research/PGM_PILOT_SECURITY.md`; controles técnicos não equivalem a autorização institucional.
- O banco de produto, worker Celery de produto e cobertura integral do acervo não foram certificados. Sem gold humano, cadeia normativa adjudicada e usuários PGM consentidos, ganho científico, prontidão para processo e nota 9/10 permanecem não demonstrados.
- `legislation.0027_collectionevidenceversion` foi aplicada somente ao PostgreSQL QA isolado após interpretação excessiva de autorização que era específica à P-005, embora a migration pertença à P-016. A ocorrência está documentada no diário e na entrega PGM; sem dados jurídicos alterados ou migration de produção.
- Continuação de 10/10: a build do checkout com aviso de sincronização QA está aberta em `http://127.0.0.1:8030/assistente/?corpus=archive-qa`; regressão focal **62 passed, 1 skipped** e workflow PGM no browser **21/21 checks passed**. O container web `:8000` ainda responde 500 por hostname de banco `db` não resolvido; não foi reiniciado. Relato/evidências em `docs/research/NORMATIVE_IMPLEMENTATION_PROGRESS.md` e `%TEMP%\jurix-pgm-goal-qa-20261008\post-source-health-smoke-20261010\`.
- O aviso de atualização foi estendido também ao assistente padrão; Chromium confirmou ambos os escopos em seis larguras (**12/12**, sem overflow/erros) e o smoke PGM repetido ficou **21/21**. Testes focais agora **63 passed, 1 skipped**. Para conferir esta build, use `http://127.0.0.1:8030/assistente/`; o aviso desaparece somente quando SAPL e DOM tiverem sincronização recente registrada.
- Reteste com Docker/Ollama ativos na QA `:8030`: fluxo live SSE concluiu em 6,1 s após 7 chunks; fontes chegaram antes do texto, citações dos arts. 17/18 abriram o PDF local, F5 restaurou conversa/fontes e follow-up recuperou Art. 19. Smoke também cobriu overview parcial de 30/39 artigos, cancelamento/retry e abstenção. Relatório sanitizado em `%TEMP%\jurix-pgm-goal-qa-20261008\live-rag-after-docker-20261010\live-rag-browser-smoke.json`; extrações permanecem pendentes de revisão. Health de SAPL/DOM segue `not_configured`, worker QA responde; container `:8000` segue 500/timeout, então a instância atual para teste continua sendo `:8030`.
- Também executei o smoke PGM de atualidade no `:8030` (allowlist do script atualizada): pergunta sobre LC 120/2010, Art. 18, respondeu com incerteza explícita, distinguiu PDF pendente e matéria SAPL de lei promulgada, exibiu 2 fontes e não teve erro JS. Screenshot/relatório sem transcrição em `%TEMP%\jurix-pgm-goal-qa-20261008\currentness-after-docker-20261010\`; isso não comprova a situação jurídica do artigo.
- Gate P-022 no QA: 24 testes de autorização, segurança de settings e acesso a documentos passaram. `manage.py check --deploy` não passou no perfil `settings_normative_qa` (DEBUG/chave de desenvolvimento; HSTS/HTTPS/cookies seguros ausentes), como esperado para QA. Nenhuma credencial foi exibida; ainda não há perfil operacional de piloto validado.
- Diagnóstico somente leitura dos containers: `jurix_web` está ativo, mas `jurix_db`/`jurix_redis` estão parados e `jurix-worker-1` unhealthy; por isso `:8000` não funciona. Compose de produção não valida sem `POSTGRES_USER` obrigatório; não subi serviços nem acessei/alterei volumes. QA isolada em `:8030` permanece disponível.
- Com variáveis fictícias isoladas no processo, `check --deploy --tag security` passou e o Compose de produção validou; isso confirma o contrato configurável, não a configuração real do deploy. Os valores reais continuam ausentes e nenhum container foi iniciado.
- O smoke focado de atualidade (LC 120/2010, Art. 18) agora também verifica 320/360/768/1280/1920 px: 5/5 passaram, sem overflow e com resposta/fontes acima do composer. Zoom nativo 200% e leitor de tela não foram executados.
- Corrigi a proveniência estruturada do PDF arquivado: SSE/serializer agora classificam a fonte como archive; a matéria SAPL continua sapl_legislative_matter. Regressão QA: 177 testes; smoke de atualidade em cinco larguras e workflow PGM 21/21 passaram na build dirty identificada em :8030. Extrações locais seguem pendentes de revisão; nenhum status jurídico foi promovido.
- Suíte Python integral depois do ajuste: 1.753 passed, 6 skipped, 0 failed, 8 warnings em 253,05 s no banco de teste QA.
- Com Docker aberto, a prontidão QA em `:8030` confirmou database/pgvector/Redis/migrations; Ollama ficou `skipped`. O smoke focado executou consulta, F5 e restauração das fontes `archive` e `sapl_legislative_matter`: passou sem erros JS e sem overflow em 320/360/768/1280/1920 px. O runner QA não inclui esse script na allowlist; foi executado diretamente, com host loopback e saída isolada no diretório temporário QA. Evidências: `%TEMP%\\jurix-pgm-goal-qa-20261008\\currentness-f5-docker-20261010\\`. A conclusão jurídica continua inconclusiva e o PDF segue pendente de revisão.
- Smoke live Ollama pós-Docker em QA `:8030`: passou com SSE 200, 7 chunks, fontes antes do texto, 2 tentativas de geração, cópia Markdown/follow-up/F5 corretos e 40/40 rotas PDF HTTP 200. A resposta começou a aparecer em 6,063 s e concluiu em 6,212 s (149 ms de streaming visível). Overview foi explicitamente parcial: 30/39 artigos recuperados, 6 excertos usados e `corpusCoverageStatus=unknown`. Sem inferência de validade jurídica; PDF não revisado. Relatório sanitizado em `%TEMP%\\jurix-pgm-goal-qa-20261008\\pgm-live-rag-post-docker-20261010\\live-rag-browser-smoke.json`.
- Diagnóstico Docker read-only: o readiness/web `/assistente/` em `:8000` falha (500/timeout), pois o app não resolve os hosts `db`/`redis`; o worker também está unhealthy por DNS de `redis`. O container reporta healthy apenas no liveness. Postgres/Redis QA pertencem a outro projeto Compose e não foram conectados ao web/worker. Nenhum container foi reiniciado ou rede/config/volume alterado; QA `:8030` segue sendo a instância funcional.
- Os arquivos Compose agora verificam readiness de dependências no healthcheck web, com timeout de 3 s, em desenvolvimento e produção. Contrato focal: 13 passed; ambos os Compose parseados; `manage.py check` sem issues. Nenhum container foi recriado, então a instância atual `:8000` ainda usa o healthcheck antigo até uma recriação explicitamente autorizada.
- Rechecagem QA em 11/10: a fila `normative_qa` responde com 1 worker; identidade não exposta. O sync DOM continua `not_configured`, sem escopos/checkpoints/sucesso. Nenhuma coleta ou escrita foi iniciada; o worker unhealthy do Compose `:8000` não foi confundido com o worker QA.
- Integrei o smoke de atualidade (`pgm-article-currentness-smoke.mjs`) à allowlist estrita do runner QA; guard **28/28** e reteste pelo wrapper passaram. Fontes estruturadas persistiram após F5 e layout passou em cinco larguras. Evidência sanitizada em `%TEMP%\\jurix-pgm-goal-qa-20261008\\currentness-f5-runner-20261011\\`; extração não adjudicada.

## Revalidação PGM — QA local (2026-10-12)

- Checkout atual na branch `main`; working tree preservado, sem commit/push/merge. A QA corrente `:8040` responde em `/assistente/` e `/normas/`; não confundir com os containers de produto `:8000` nem com instâncias QA antigas.
- Smoke PGM no Chromium em `:8040`: 20 verificações funcionais passaram, 0 erros de página, 13 capturas, seis larguras (320, 360, 640, 768, 1280 e 1920 px). Uma verificação separada marcou `unversioned-local-checkout` porque este build local não declara release/revisão. Relatório: `%TEMP%\\jurix-pgm-goal-qa-20261008\\evidence\\pgm-workflow-current-8040-20261012\\pgm-workflow-smoke.json`.
- `/normas/` mostrou 6.664 PDFs candidatos, 40 na página e **0 normas consolidadas**. PDFs e extrações continuam pendentes de revisão; a consulta temporal sem versão reconstruível se absteve. A cadeia pública LC 258/2024–LC 55/2004 foi apresentada como triagem, com pedido para conferir protocolo, despacho, manifestação e vigência, sem decisão sobre processo concreto.
- `npm test --prefix tests/js`, com base QA `:8040`: **262 passed, 3 skipped, 0 failed** (exit 0); 41 testes de browser real passaram. Os três skips precisam de credencial temporária de revisor. Regressão Python de autorização/CSRF/sessões/documentos/anexos/revisão/conferência: **94 passed**. Regressão cruzada P-012–P-016: **120 passed, 1 skipped**; P-017 offline: **84 passed**. `manage.py check`, Ruff e `git diff --check` passaram.
- O cliente e o detector DOM passaram offline, mas a leitura pública do catálogo de outubro/2026 retornou `DomNatalError`; uma abertura externa somente leitura do portal também expirou. Health `dom_natal=not_configured`, fila QA `current` com 1 worker. SAPL continua limitado à página autorizada no cursor 30, dez registros `pending`, sem PDFs. Nenhum novo sync, download ou promoção ocorreu.
- P-015 recebeu alinhamento do DTO de exportação Python/JS; P-016 preserva data/dispositivo no formulário após erro de validação. Ambos seguem parciais até uso autenticado por revisor e referências reais revisadas. P-022 continua parcial: 94 regressões passaram, mas deploy real, TLS, retenção, cleanup periódico, restore, pentest e política institucional não foram verificados.
- Regressão integral Python do checkout em profile `config.settings_normative_qa`: **1.794 passed, 6 skipped, 0 failed, 8 warnings** (1.800 coletados; 314,31 s). A suíte JS integral terminou com exit 0 (**262 passed, 3 skipped, 0 failed**); 41 testes de browser real passaram. Arquitetura (`passed=true`), contrato documental, `manage.py check` e Ruff passaram.
- Pontuação científica permanece **não avaliada**; prontidão PGM não demonstrada. O QA permite pesquisar/abrir PDFs candidatos como material de conferência, não afirmar vigência ou substituir validação oficial. Evidências detalhadas em `docs/research/PGM_PILOT_DELIVERY.md`.
- Rechecagem do DOM em 12/10: catálogo de outubro disponível (8 edições); uma edição PDF oficial foi lida e validada somente em memória (23 páginas, 421.706 bytes). O protótipo detectou 69 linhas com prefixos reconhecidos na edição, mas pode incluir referências, não infere spans completos dos atos e não está integrado à ingestão. Nenhum PDF foi salvo ou promovido. Para SAPL, cursor 30 permanece parcial e a repetição autorizada da página anterior já havia sido concluída; nenhum avanço para a página 4 foi feito.
