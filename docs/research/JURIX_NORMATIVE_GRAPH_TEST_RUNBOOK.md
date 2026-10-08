# Jurix — roteiro de testes do acervo, grafo e RAG temporal

Complemento de `JURIX_NORMATIVE_GRAPH_IMPLEMENTATION_PLAN.md`.

**Este documento descreve testes futuros. Nenhum resultado abaixo é um teste já executado.** Os scripts/comandos novos só existirão após as tarefas correspondentes. O Luna deve implementar os contratos CLI desta seção, testar `--help` e então executar os testes. Não apresentar “comando previsto” como “comando aprovado”.

## 1. Segurança e identificação do ambiente

Ambiente atual na elaboração: `C:\Jurix`, branch main, HEAD0426e53. Atualizações posteriores exigem releitura do checkout, não reset para esse commit.

Antes de qualquer mudança:

```powershell
git status --short
git branch --show-current
git log -1 --format="%h %s"
git diff --stat
git diff --cached --stat
```

Inspecionar diffs sobrepostos à tarefa sem imprimir credenciais. Preservar GOAL.md e telemetria de auditoria preexistentes. Não fazer sync remoto, commit ou troca de branch por inferência.

Criar root QA próprio, sem copiar `.env`:

```powershell
$env:JURIX_QA_ONLY = '1'
$env:JURIX_QA_ROOT = Join-Path $env:TEMP ('jurix-normative-qa-' + [guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $env:JURIX_QA_ROOT
$env:JURIX_BASE_URL = 'http://127.0.0.1:8007'
$env:DJANGO_SETTINGS_MODULE = 'config.settings_normative_qa'
```

O helper T-001 deve carregar URLs **somente de fixtures QA** para subprocessos e recusar configuração real. A autorização de criação desse diretório não autoriza apagar diretórios temporários que não foram criados nesta execução. Não reutilizar variáveis de sistema como HOME.

O settings QA deve manter o root em todas as sessões usadas pelo web/worker; abrir outra shell não pode criar automaticamente um root diferente e deixar web sem acesso aos documentos importados.

Antes de escolher 8007/8009/8010/8011/8012/8013/8014/8015/8016/8017/8018/8019/8020/8021/8022/8023/55432/16380, verificar listeners e serviços. Não matar processo existente para liberar porta. Se o compose já estiver ativo com outro projeto, parar e selecionar isolamento alternativo documentado, sem editar `.env` ou anexar worker a Redis real.

```powershell
Get-NetTCPConnection -State Listen -LocalPort 8007,8009,8010,8011,8012,8013,8014,8015,8016,8017,8018,8019,8020,8021,8022,8023,55432,16380 -ErrorAction SilentlyContinue |
  Select-Object LocalAddress,LocalPort,OwningProcess
docker compose -p jurix-normative-qa -f docker-compose.audit.yml ps
```

Se houver conflito, T-001 pode ser dividida para criar override QA de portas e atualizar guards/testes; 8012 é o fallback QA, 8013–8023 são portas de verificação de código fresco quando as anteriores já estiverem em uso. Isso é mudança de escopo explícita, não gambiarra no banco real.

## 2. Serviços e servidor web

Após T-001, preparar somente db/redis de auditoria:

```powershell
docker compose -p jurix-normative-qa -f docker-compose.audit.yml up -d db redis
.\.venv\Scripts\python.exe scripts/normative_qa.py --check-services
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py check
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py migrate --plan
```

Migrations passam pelo guard e só podem ser aplicadas em DB QA. Nunca migrar a base real para fazer o teste passar:

```powershell
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py migrate
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py makemigrations --check --dry-run
```

Identificar Ollama por leitura, sem baixar modelo ou mudar configuração global. Consultar `/api/tags` e `/api/ps` no endpoint local configurado; registrar apenas nomes/tamanhos/modo de execução úteis. Não afirmar aceleração GPU sem observar. Não fechar jogos/programas do usuário nem matar processos compartilhados para produzir benchmark favorável.

Iniciar web com `--noreload` e settings QA:

```powershell
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py runserver 127.0.0.1:8007 --noreload
```

Para execução em background no Windows, usar Start-Process com `-WindowStyle Hidden`, paths absolutos e redirects para root QA; registrar PID. Não adicionar o comando ao Startup nem iniciar servidor em janela visível sem pedido.

Worker real, depois de T-024:

```powershell
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python -m celery -A config worker --pool=solo --concurrency=1 -Q normative_qa -l warning
```

Não iniciar o worker padrão do compose audit: ele usa outro settings módulo. Não iniciar beat. Não parar Docker/Ollama compartilhados para testar indisponibilidade; usar serviço QA próprio ou mock declarado.

Provar identidade do servidor: `GET /api/v1/health/live/` deve responder; registrar HEAD e configuração QA no relatório. Health pode não conter HEAD, portanto o launcher deve registrar esse dado sem inventar campos da API. API readiness degradada por Ollama não invalida automaticamente fluxo independente de leitura/grafo; reportar dependência específica.

## 3. Baseline e gates automatizados

Rodar suites através do helper, que traduz `python` para o executável ativo e injeta apenas o ambiente QA. Scripts sem DB também devem manter logs/outputs isolados.

```powershell
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python -m pytest
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py check
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python scripts/architecture_budget_v2.py
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python scripts/validate_documentation_contract.py
npm test --prefix tests/js
```

Para lint, conferir disponibilidade instalada de Ruff antes de chamar; não instalar dependência só para gerar selo. Rodar nos paths alterados, documentando baseline:

```powershell
.\.venv\Scripts\python.exe -m ruff check <paths-exatos-da-tarefa>
```

O placeholder não é um comando pronto. Substituir pelos arquivos reais, excluir migrations conforme config e registrar comando expandido.

Gates por fase:

- A: unitários de ZIP/metadados/extração; PostgreSQL com constraints; import repetido/interrompido; nenhum candidato promovido implicitamente.
- B: revisão/CSRF/concorrência; snapshots D-1/D/D+1; sem restauração/futuro inventados.
- C: suites Python/JS completas; grafo API/lista; browser básico e citações/cópia.
- D: Celery/Redis reais QA, limites, benchmarks offline e smoke Ollama; gold humano pendente não vira passed científico.
- E: R01–R24 e suites completas novamente, com relatório final.

Testes pulados devem manter razão visível. SQLite não comprova constraints/locks/queryplan PostgreSQL. jsdom não comprova layout/acessibilidade/scroll. Mock de LLM não comprova latência/streaming do Ollama real.

## 4. Contratos CLI novos e smoke de dados

T-003 implementa:

```powershell
.\.venv\Scripts\python.exe scripts/inventory_normative_archive.py --archive 'C:\Users\Cauã V\Downloads\sistema2-20261003T011536Z-1-001.zip' --output '<QA_ROOT>\archive-manifest.jsonl'
```

Saída resumo ao lado; recusar overwrite. Substituir `<QA_ROOT>` pelo valor atual, sem editar o ZIP. Reconciliar counts com 6.663 PDFs observados, mas se hash/input mudou, registrar a diferença em vez de forçar contagem esperada.

T-008 implementa dry-run/apply, com manifesto completo e hash verificado:

```powershell
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py import_normative_archive --archive '<ZIP>' --manifest '<MANIFESTO>' --limit 40 --batch-size 10
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py import_normative_archive --archive '<ZIP>' --manifest '<MANIFESTO>' --limit 40 --batch-size 10 --apply
```

Antes de apply, resolver os placeholders; output é root QA; não usar command real sem guard. Registrar contagem antes/depois, repetir e esperar zero duplicações. Teste de interrupção usa fixture pequena com injeção de falha ou processo QA identificado, nunca interrompe importação real em andamento.

T-009 implementa seed mínimo; T-015 acrescenta a cadeia temporal, e T-025 amplia casos e estratos. Após cada uma, o mesmo comando produz mapfile atualizado:

```powershell
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py seed_normative_qa --output '<QA_ROOT>\fixture-map.json'
```

Mapfile mínimo: IDs/URLs das normas sintéticas, chaves estruturais, datas D-1/D/D+1, hashes esperados, identities para perguntas e referências externas. Credenciais fixture devem ser fornecidas por canal/env privado, não gravadas no mapfile/screenshots/reports.

Exemplo de caso sintético a implementar:

- Norma A: LO9001/2020, art.5 “O prazo é de dez dias.”, publicação/vigência confirmadas em2020-01-10.
- Norma B: LO9002/2021, altera explicitamente art.5 da A para “O prazo é de vinte dias.”; publicada2021-01-10, efeito revisado2021-03-01.
- D-1=2021-02-28; D=2021-03-01; D+1=2021-03-02.
- Norma C: LC55/2004; LC198/2021 remete aos arts21/44. Usar conteúdo **sintético** nos testes de unidade, não fingir que ele é o PDF real.
- Norma D: LO55/2004 municipal, para testar colisão de número/tipo.
- Fonte federal4320/1964 não presente; norma municipal com número4320 não pode receber o link federal.

Texto de fixture não pode conter números de série/normas com tokens inválidos para o parser. Namespace QA pode ficar em identity_json/source_ref, mantendo `numero` legalmente parseável. Nunca cadastrar fixture na base real.

## 5. Roteiro de uso comum — R01 a R24

Executar com browser real no servidor8007. Mapear nomes/IDs pelo fixture-map, sem supor PK. Para cada caso, registrar passed/failed/not_run e motivo, com evidência. Perguntas normativas reais sobre o ZIP só quando metadados/condição de uso estiverem resolvidos; testes sintéticos não confirmam juridicamente as leis reais.

### R01 — Chegada, navegação e shell

Abrir `/assistente/`, `/normas/`, `/pesquisa/`, `/historico/`, `/colecoes/`, `/configuracoes/`. Recolher/expandir sidebar, visitar item atual e trocar rota. Esperado: mesma navegação/ícones, sem scroll escondido ou flash de estado incorreto. Esses fluxos são regressões, não autorização para revamp paralelo.

### R02 — Identificação de tipo e número

Pesquisar LC55/2004 e LO55/2004 separadamente. Testar55/055 e tipo explícito. Esperado: LC e LO distintas, leading zero só normalizado para chave numérica; LP preserva série e conflito, não vira LO automaticamente.

### R03 — Abrir relações e remissão

Abrir norma LC do fixture; expandir relações e selecionar vínculo. Esperado: origem/dispositivo/alvo/evidência e ação REFERENCIA; nenhum texto “revoga” ou “altera” inventado. Confirmar que lista e SVG representam o mesmo conjunto.

### R04 — Múltiplos dispositivos sob a mesma norma

Selecionar par com várias remissões. Esperado: um agrupamento visual com contador, painel com todos os eventos e artigos; expandir/recolher sincroniza estado; sem fontes duplicadas por simples re-render.

### R05 — Teclado e painel

Usar sóTab/Shift+Tab/Enter/Escape. Abrir evidência, fechar e voltar ao botão de origem. Esperado: foco visível, ordem lógica, não obscurecido por composer/sidebar; sem trap. Lista opera sem manipular SVG.

### R06 — Limites, loading, erro e vazio

Fixture com ciclo e >40 nós. Esperado: não trava, limite/truncated/filtrar/refocar claros. Simular API lenta/500 em QA/mock declarado: skeleton/estado curto, retry preserva filtro. Norma sem relações não promete grafo inexistente.

### R07 — Redação antes/depois

Consultar Norma A em D-1 e D. Esperado: dez dias antes, vinte depois; mesmo artigo/chave, evidências/versões diferentes. Não usar embedding atual como prova da redação anterior.

### R08 — Publicação não é efeito

Ver timeline da B e redação da A em fevereiro2021. Esperado: B publicada, mas mudança ainda não aplicada. Timeline mostra publicação10/01 e efeito01/03 separadamente.

### R09 — Comparação, URL e reload

Comparar A em D-1/D; F5; back/forward. Esperado: escolhas na URL e diff restaurado; evento/trecho que justifica alteração acessível; não aparecem duas cópias de latest com datas diferentes.

### R10 — História insuficiente e conflitos

Abrir fixture sem original, com data conflitante ou evento pendente. Esperado: `not_reconstructable`, parcial ou pendente com explicação; nunca consolidação “completa” por omitir evento difícil. Consulta atual independente continua quando possível.

### R11 — Pergunta sobre norma inteira

Perguntar “O que prevê a Lei nº9001/2020?”. Esperado: conclusão direta, dispositivos relevantes e coverage proporcional; ausência de seções artificiais por artigo; não limitada sempre a cinco fontes. Norma grande declara cobertura parcial quando context budget termina.

### R12 — Artigo e follow-up

Perguntar art.5 de A; depois “E o artigo6?”. Esperado: resolve norma anterior, procura artigo6; se fixture não o tem, explicar insuficiência sem inventá-lo. Não perder contexto nem recuperar homônima de outro tipo.

### R13 — Relação explícita e efeito

Perguntar “Qual norma alterou o art.5 da Lei nº9001/2020 e quando essa mudança passou a valer?”. Esperado: B, dispositivo fonte, data confirmada e URLs estruturadas. Distinguir data de publicação e efeito.

### R14 — Histórico, referência externa e falta de base

Perguntar o prazo em D-1; depois referência federal não presente e norma inexistente. Esperado: texto histórico correto; não associar federal à municipal homônima; abstenção útil sem simular certeza. Falta de resultado não significa declarar que a norma não existe no mundo.

### R15 — Streaming e fontes disponíveis

Fazer pergunta com Ollama real. Registrar início/request, primeiro evento de status/sources, primeiro texto e done. Esperado: texto incrementa antes de finalizar quando provider efetivamente streama; fontes associadas assim que recebidas; abertura não interrompe streaming. Fade funcional curto, nenhum badge de validação que prometa certeza.

### R16 — Citações específicas versus norma

Clicar referência à norma: abrir documento base sem highlight arbitrário. Clicar art./inciso: evidência correspondente àquela versão e trecho, com fallback de documento. Não há URLs cruas nem fragmento criado de preview com “...”.

### R17 — Cópia e persistência

Copiar resposta, colar em editor de texto QA e examinar Markdown. Esperado: hyperlinks legíveis e corretos, IDs/versões correspondentes, sem HTML cru ou fonte perdida. F5 mantém resposta/fontes/URL; citações não dependem de fontes de outra resposta.

### R18 — Cancelamento e resultado insuficiente

Cancelar uma geração **durante `streaming`**; em `finalizing`, o terminal já venceu e o controle de parada deve ficar indisponível. Tentar novamente; provocar insuficiência em fixture. Esperado: sem duplicar mensagens/turnos; partial/cancelled diferenciados; fonte não utilizada não apresentada como suporte final. Não substituir honestidade por resposta plausível nem por erro genérico de rede.

### R19 — Busca temática

Filtrar ambiente/urbanismo. Esperado: normas associadas a tema; distinção entre tag automática candidata e confirmada; afinidade não afeta redação nem aparece como REVOGA/REGULAMENTA. Filtro por data preservado.

### R20 — Coleções e histórico

Com usuário QA, salvar norma em coleção e verificar acesso de outro usuário QA. Esperado: isolamento atual preservado; coleção não muda vínculo jurídico. Histórico/busca/menus recentes continuam operáveis, sem scroll cobrindo ações.

### R21 — Revisão e autorização

Admin QA: aprovar evento com motivo/fingerprint; tentar replay e aprovação de revisão antiga. Esperado: idempotência e stale rejection; visitante/outro usuário sem permissão não aprova. APIs públicas não expõem ator/email nem arquivo interno.

### R22 — Reingestão, republicação e interrupção

Importar fixture em lotes, repetir, adicionar republicação/retificação, interromper worker QA próprio e retomar. Esperado: nenhuma Norma duplicada por documento; base antiga preservada até revisão; checkpoint/lease e hashes coerentes; nenhum efeito jurídico automático por nome do arquivo.

### R23 — Sync e falhas controladas

Fixtures SAPL com update antigo, alteração apenas no PDF, página repetida e timeout. Esperado: sweep detecta mudança e cria candidato; incompletude/falha não vira freshness completa; sem excluir norma. Worker/Ollama/Redis faltantes degradam somente capacidades dependentes.

### R24 — Uso mobile, zoom e qualidade visual

Em320/360/768/1280/1920, claro/escuro e zoom200: navegar, filtrar, abrir painel, comparar e conversar. Esperado: scroll do conteúdo, leitura confortável, composer fora da sidebar, headings coerentes, alvos adequados e lista equivalente ao grafo. Avaliar qualitativamente se um usuário comum entende ação/data/limitação sem ler documentação técnica.

## 6. Browser automatizado e inspeção visual

T-029 implementa smoke com os nomes de ambiente. Gere sempre um mapfile novo
após atualizar `seed_normative_qa`: o comando recusa sobrescrever mapfiles
existentes e o smoke precisa de todos os cenários, incluindo `missing_original`.
Exemplo em PowerShell, usando o servidor QA fresco `8020` (loopback allowlisted):

```powershell
$env:JURIX_BASE_URL = 'http://127.0.0.1:8020'
$env:JURIX_FIXTURE_MAP = Join-Path $env:JURIX_QA_ROOT ('fixture-map-' + [guid]::NewGuid().ToString('N') + '.json')
$env:JURIX_QA_ONLY = '1'
.\.venv\Scripts\python.exe scripts/normative_qa.py --run python manage.py seed_normative_qa --output $env:JURIX_FIXTURE_MAP
$env:JURIX_EVIDENCE_DIR = Join-Path $env:JURIX_QA_ROOT 'browser-evidence'
.\.venv\Scripts\python.exe scripts/normative_qa.py --run node tests/js/normative-product-smoke.mjs
```

Para validar uma consulta real pelo composer com Ollama (opcional, pode carregar o modelo e levar até três minutos), use um novo diretório de evidências sob `JURIX_QA_ROOT` e o mesmo servidor QA. O script usa somente um navegador anônimo descartável, consulta a amostra histórica QA sem aprovação jurídica e grava métricas agregadas sem texto da resposta ou fontes:

```powershell
$env:JURIX_EVIDENCE_DIR = Join-Path $env:JURIX_QA_ROOT 'live-rag-browser-smoke'
.\.venv\Scripts\python.exe scripts/normative_qa.py --run node tests/js/normative-rag-live-smoke.mjs
```

O teste exige HTTP 200 no SSE, geração Ollama real, fontes antes dos chunks, citações para os dois artigos pedidos, abertura/fechamento do drawer por Escape, restauração de resposta/fontes/URL após reload e ausência de erro JavaScript. Também pergunta genericamente sobre uma norma maior: deve mostrar a cobertura parcial, explicar que não representa análise integral, avisar sobre anexos fora da amostra quando detectados e converter pelo menos três marcadores estruturados em hyperlinks no texto final. O harness espera explicitamente a remoção do estado `data-streaming` antes de avaliar o DOM final; texto provisório durante a geração não é confundido com resposta concluída. Os tempos `sourcesAvailableAfterMs` e `firstAnswerTextAfterMs` são observações locais repetidas do mesmo cenário, não uma distribuição de latência; texto extraído/resposta continuam não adjudicados.

Usar browser e Node.js já instalados; se necessário informar `PUPPETEER_EXECUTABLE_PATH` existente, sem instalar Chrome pesado implicitamente. O smoke de produto aceita `8007`, `8011`, `8013`, `8014`, `8019`, `8020`, `8021` e `8022`; o smoke RAG em tempo real tem allowlist própria: `8007`, `8009`, `8010`, `8011`, `8012`, `8013`, `8014`, `8015`, `8016`, `8017`, `8018`, `8019`, `8020`, `8021` e `8022`, sempre em loopback/QA isolado. Não usar scripts antigos com rota/PK hardcoded como evidência do novo corpus; o script novo usa mapfile.

Capturas mínimas:

- norma/grafo desktop claro e escuro;
- evidência aberta e lista mobile;
- timeline publicação/efeito;
- diff D-1/D;
- resultado histórico com fontes;
- erro/pendência/sem evidência;
- assistente, pesquisa, histórico, coleções e configurações para regressão.

Automação pode medir overflow e geometria, mas screenshots exigem inspeção visual. WCAG2.2AA exige verificar critério: contraste texto4,5:1, texto grande/UI3:1, teclado, foco, reflow, status e alvo2.5.8. O target de44px é decisão de design adotada aqui; não afirmar que WCAGAA exige44px em todos os controles.

Ativar reduced-motion no navegador e verificar ausência de simulação/animação contínua. Zoom200%: registrar o mecanismo real; ampliar somente screenshot ou reduzir viewport não demonstra zoom. Se o navegador automatizado não fornecer zoom real confiável, executar manualmente e registrar a limitação.

## 7. Performance e experimento

Não prometer ganho antes de medir. Registrar:

- versão Python/Django/Celery/PyMuPDF, HEAD, corpus digest, parser/policy, flags;
- modelo/quantização e CPU/GPU observados, não presumidos;
- queries e latência de graph/projection/retrieval;
- TTFT/final, tokens quando disponíveis, cache cold/warm;
- peak memory de import/OCR por método explicitado;
- counts criados/inalterados/pendentes/falhos por lote;
- conjunto frozen e revisão humana/adjudicação, quando existir.

Core Web Vitals: métricas locais de uma navegação são diagnóstico, não valores de campo/população. Não rotular um teste único de screenshot como LCP/INP/CLS aprovado. Se medir via PerformanceObserver/browser trace, registrar ferramenta e amostra; caso contrário “não medido”.

Qualidade científica fica `not_evaluated` se gold humano faltar. A validação matemática com fixture não deve contaminar relatório científico. Sintéticos, corpus técnico e gold real são datasets distintos.

## 8. Entrega e critérios de parada

Relatório final deve incluir:

1. Arquivos/diffs próprios e estado Git antes/depois.
2. Tarefas concluídas/bloqueadas, sem apagar falhas preexistentes.
3. Comandos efetivos, exit codes, passed/failed/skipped e tempo.
4. R01–R24 com runtime real/mock/não executado, paths de evidência.
5. Pendências humanas/legais, cobertura de versão/acervo e experimentos não avaliados.
6. URL do QA realmente ativo, HEAD e como iniciar/parar somente processos QA próprios.
7. Operação real não realizada; passos para autorização futura de migration/import/ativação.

Erro em fonte, identidade, efeito temporal, autorização, clipboard ou streaming de fluxo central bloqueia a declaração de funcionalidade completa. Correção deve receber tarefa estreita com paths/testes, não refatoração livre. Dado ambíguo exige abstenção/revisão, não patch que inventa a resposta.

Referências: [WCAG2.2](https://www.w3.org/TR/WCAG22/), [Django transações](https://docs.djangoproject.com/en/5.2/topics/db/transactions/), [Celery5.4 tasks](https://docs.celeryq.dev/en/v5.4.0/userguide/tasks.html), [PyMuPDF OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html).
