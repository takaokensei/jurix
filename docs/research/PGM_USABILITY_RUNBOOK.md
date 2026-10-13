# Roteiro de usabilidade PGM — Jurix QA

## Objetivo e limites

Verificar, como assessor jurídico em triagem de norma municipal, se o Jurix permite localizar um ato no acervo, inspecionar a evidência original, distinguir remissão de alteração normativa e perceber quando a cadeia temporal não foi comprovada. O roteiro usa PDFs locais reais em banco QA isolado; documentos e extrações ainda pendentes de revisão **não são gold jurídico**.

Não inserir número de processo, nomes de partes, peças, pareceres internos ou qualquer conteúdo reservado. Não promover documentos, aprovar relações, editar redações/datas, criar usuário privilegiado ou acessar dados de produção. Login e operações de revisão só podem ser testados por revisor autorizado, em sessão legítima.

## Pré-condições verificáveis

1. Confirmar a branch e `git status`; preservar integralmente mudanças preexistentes.
2. Confirmar que o servidor é QA local e que `JURIX_QA_ROOT` aponta ao armazenamento de PDFs correspondente ao banco QA `127.0.0.1:55432`. Não trocar por uma pasta vazia: o banco pode reter `storage_key` para blobs existentes.
3. Verificar `/api/v1/health/ready/` e usar a porta QA atual documentada para a sessão. Não presumir que `:8000` ou qualquer porta histórica seja a versão atual.
4. Verificar modelo/provedor antes de iniciar consultas lentas. Todas as perguntas devem usar normas públicas e não devem solicitar opinião jurídica final.

## Jornada automatizada com PDF do acervo

O smoke amplo permite somente servidores QA locais explicitamente allowlisted (`:8010`, `:8011`, `:8016`, `:8017`, `:8028`, `:8029`, `:8030`, `:8040`, `:8280`, `:8281`, `:8282` e `:8283`). O smoke focado de matéria SAPL permite apenas `:8280–:8283`. Na revalidação de 10/10/2026, `:8283` respondeu no profile `config.settings_normative_qa`, com PostgreSQL/Redis isolados e metadata de checkout dirty; os processos antigos foram mantidos. O commit-base não contém os diffs locais. Neste host, as portas `7937–8036` estão reservadas pelo Windows. Antes de executar, confirme health, profile, raiz com os blobs do banco QA e identidade explícita do build atual.

1. Layout e landmark `main` em 320, 360, 640, 768, 1280 e 1920 CSS px, sem overflow horizontal. 640 CSS px é uma aproximação de reflow para desktop a 200%; não equivale a uma validação de zoom nativo de navegador.
2. Consulta: “A Lei Complementar nº 198/2021 cita ou faz remissão à Lei Complementar nº 55/2004? Liste todos os artigos do PDF arquivado que mencionam a LC 55/2004 e esclareça se isso comprova alteração normativa.”
3. Resposta concluída e Fontes Consultadas disponíveis sem F5; recuperação de artigos 1, 2, 4 e 6; agrupamento sob uma norma; contribuição e aviso de revisão pendente.
4. Expansão do grupo e atualização do rótulo do botão; fechamento do drawer por Escape.
5. GET da rota do PDF citado, validando HTTP, `Content-Type`, cabeçalho `%PDF` e marcador `%%EOF` sem salvar os bytes em arquivo.
6. Pergunta sobre cadeia temporal: “A Lei Complementar nº 198/2021 alterou o art. 21 da Lei Complementar nº 55/2004? Compare a redação anterior e posterior ou informe a lacuna.” Se houver texto de origem recuperado, a resposta pode citá-lo como tal, mas deve distingui-lo da alteração perguntada e manter inconclusivos o ato modificador, a redação posterior e a vigência. Não inventar ato, autoria, data, redação ou fonte de alteração.
7. A mesa `/conferir/` redireciona usuário anônimo para login. Não contornar o gate.

Execute no PowerShell, usando a raiz QA já identificada para o banco e os PDFs:

```powershell
$env:JURIX_QA_ONLY = '1'
$env:JURIX_QA_ROOT = Join-Path $env:TEMP 'jurix-pgm-goal-qa-20261008'
$env:JURIX_BASE_URL = 'http://127.0.0.1:8283'
$env:JURIX_EVIDENCE_DIR = Join-Path $env:JURIX_QA_ROOT 'pgm-smoke'
.\.venv\Scripts\python.exe scripts/normative_qa.py --run node tests/js/pgm-workflow-smoke.mjs
```

O teste cria uma conversa temporária no QA e grava relatório/screenshot somente sob `JURIX_QA_ROOT`. Não copiar o relatório bruto para um repositório compartilhado sem revisar o conteúdo. O screenshot sanitizado versionado fica em `docs/research/screenshots/pgm-workflow-20261008.png`.

### Consulta de atualidade e proposta relacionada no SAPL

O smoke focado exercita uma pergunta de atualidade para o Art. 59 da LC 258/2024. O endpoint público de pesquisa textual por ementa pode retornar tipos diferentes de matéria; o teste exige o registro exato da PLC 12/2025, confirma que a ementa cita o dispositivo e abre a fonte no drawer. A resposta deve manter a extração local como pendente e não converter tramitação/proposta em alteração promulgada ou vigente. O teste cria uma conversa temporária no banco QA e salva captura e relatório JSON sanitizado apenas no root QA.

```powershell
$env:JURIX_QA_ONLY = '1'
$env:JURIX_QA_ROOT = Join-Path $env:TEMP 'jurix-pgm-goal-qa-20261008'
$env:JURIX_BASE_URL = 'http://127.0.0.1:8283'
$env:JURIX_EVIDENCE_DIR = Join-Path $env:JURIX_QA_ROOT 'pgm-sapl-related-matter-smoke'
.\.venv\Scripts\python.exe scripts/normative_qa.py --run node tests/js/pgm-sapl-related-matter-smoke.mjs
```

## Smoke de geração real com Ollama local

O profile `config.settings_normative_qa` mantém `READINESS_REQUIRE_OLLAMA=False`, portanto `health/ready` pode reportar Ollama como `skipped`. Para verificar geração real, confirme separadamente o serviço local em `127.0.0.1:11434`, o Ollama no `/api/ps` após a execução e execute o smoke de navegador abaixo. Não use uma porta antiga sem validar sua cadeia de processos/build. Nesta sessão, a instância QA corrente é `:8282` com build `qa-dirty-20261010`; a revisão exibida é o commit-base e não contém os diffs locais. O teste cria conversas temporárias apenas no banco QA e requer Chrome/Edge local.

```powershell
$env:JURIX_QA_ONLY = '1'
$env:JURIX_QA_ROOT = Join-Path $env:TEMP 'jurix-pgm-goal-qa-20261008'
$env:JURIX_BASE_URL = 'http://127.0.0.1:8282'
$env:JURIX_EVIDENCE_DIR = Join-Path $env:JURIX_QA_ROOT 'pgm-live-rag-smoke'
./.venv/Scripts/python.exe scripts/normative_qa.py --run node tests/js/normative-rag-live-smoke.mjs
```

Esse smoke exige geração medida, resposta com dois artigos, citations, copy Markdown, F5, follow-up, PDF, cancelamento/retry, overview parcial, recuperação insuficiente e cenários temporais/relacionais explicitamente sintéticos. Relatório/capturas ficam sob o diretório QA temporário; não copiar respostas/excertos sem sanitização. Uma execução não é benchmark ou avaliação jurídica.

## Sessão manual complementar

- **Localizar**: buscar tipo, número e ano; verificar se o rótulo identifica explicitamente “PDF candidato/pendente”, sem chamar candidato de norma consolidada.
- **Conferir fonte**: abrir o painel, expandir evidências, localizar dispositivo e contribuição; abrir o PDF em nova aba e comparar visualmente epígrafe e trecho. Erro, ausência ou divergência deve ser registrado como inconclusivo.
- **Verificar cadeia**: procurar ato alterador, artigo alterador, data de publicação e redação anterior/posterior. Uma remissão não é prova de alteração; ausência de resultado não prova que não houve alteração.
- **Testar histórico**: copiar uma citação e reabri-la; trocar data `as_of`; registrar se corpus/corte/versão e limitações continuam visíveis.
- **Testar responsividade/acessibilidade**: 320/360/768/1280/1920 px, zoom nativo a 200%, Tab/Shift+Tab, Enter, Escape, foco visível, texto não cortado, scroll horizontal, contraste e reduced motion.
- **Registrar**: tarefa, pergunta sanitizada, rota/porta/build quando identificados, corpus e status de revisão, resultado observado, latência, falhas, screenshot sem informação reservada e severidade. Separar comportamento técnico de validação jurídica.

## Estudo com assessores

Somente depois de autorização institucional, aprovação de privacidade e recrutamento consentido, conduzir 3–5 sessões independentes. Usar casos públicos adjudicados, não processos reais. Registrar tempo, sucesso, erros de interpretação e se a pessoa percebeu corretamente candidato/revisado/inconclusivo. O protótipo não pode influenciar uma decisão jurídica real. Publicar tamanho de amostra e limitações; metas exploratórias não equivalem a estimativa populacional.
