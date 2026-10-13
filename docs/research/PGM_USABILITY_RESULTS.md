# Resultados de usabilidade PGM — execução QA de 2026-10-08

## Resumo

**Resultado: smoke técnico aprovado; prontidão jurídica e estudo com usuários não avaliados.** A jornada usou a instância local QA `:8028`, o PostgreSQL/Redis QA isolados e um PDF municipal arquivado no armazenamento local. O documento e sua extração continuam pendentes de revisão humana. Esta evidência testa recuperação e interface; não confirma interpretação, identidade oficial, vigência nem cadeia de alterações.

## Cenário executado

Pergunta de consulta: “A Lei Complementar nº 198/2021 cita ou faz remissão à Lei Complementar nº 55/2004? Liste todos os artigos do PDF arquivado que mencionam a LC 55/2004 e esclareça se isso comprova alteração normativa.”

Resultado visível: quatro evidências agrupadas na LC 198/2021, associadas aos Arts. 1º, 2º, 4º e 6º. O texto limita a enumeração aos trechos legíveis recuperados e informa que remissão literal não comprova alteração/revogação. O painel apareceu sem F5, explicou a contribuição e exibiu o aviso de revisão pendente. A ação de expandir alterou o rótulo para “Recolher todas as evidências”; Escape fechou o painel.

O primeiro PDF consultado respondeu HTTP 200, `application/pdf`, 193.918 bytes, assinatura `%PDF` e `%%EOF`. Os bytes foram verificados em memória, sem baixar cópia adicional. Não foi feita adjudicação visual por especialista.

Pergunta de cadeia temporal: “A Lei Complementar nº 198/2021 alterou o art. 21 da Lei Complementar nº 55/2004? Compare a redação anterior e posterior ou informe a lacuna.” O acervo recuperou a redação de origem do Art. 21 da LC 55/2004, mas não uma cadeia de alteração/revogação vinculada e revisada. O Jurix citou somente esse texto histórico, explicitou que não confirma alteração ou revogação posterior e não conclui vigência atual. A fonte original é evidência do texto recuperado, não da relação perguntada; a ausência da cadeia no lote permanece inconclusiva. O teste anterior exigia nenhuma fonte e foi ajustado para exigir uma fonte de origem mais a lacuna temporal explícita.

O acesso anônimo a `/conferir/` terminou em `/conta/entrar/` (HTTP 200 após redirecionamento). O fluxo de revisão autenticada não foi executado por falta de uma sessão legítima de revisor; não houve tentativa de contornar login.

## Responsividade e fluxo

| Largura | Viewport/scrollWidth | Resultado |
| --- | ---: | --- |
| 320 px | 320 / 320 | passou |
| 360 px | 360 / 360 | passou |
| 768 px | 768 / 768 | passou |
| 1280 px | 1280 / 1280 | passou |
| 1920 px | 1920 / 1920 | passou |

No viewport de 1280 px, o drawer estabilizado ocupou x=800–1280 (480 px), sem sair da área visível. Zoom nativo 200%, leitor de tela e avaliação por assessores não foram executados nesta sessão.

## Problemas reproduzidos e resolução

1. O fallback inicial, para uma pergunta de sim/não e comparação, dizia “quem alterou e em que data”, embora a pergunta não pedisse autoria/data. Corrigido em `src/processing/qa_archive_rag.py`; a resposta agora acompanha a intenção sem fazer alegações de fato. Regressão em `src/tests/test_qa_archive_rag.py`.
2. O primeiro smoke recebeu 404 para o PDF porque o servidor fora reiniciado com uma nova pasta temporária vazia enquanto o banco preservava `storage_key` para arquivos no root original. Isso foi erro de configuração do teste, não defeito confirmado do produto. Restaurei `JURIX_QA_ROOT=jurix-pgm-goal-qa-20261008` e repeti; o PDF respondeu 200 e passou a validação de assinatura/EOF. Não movi, reingeri ou alterei PDFs.
3. A primeira asserção de geometria media o drawer durante sua animação de entrada; foi corrigida para esperar a posição final. A medição final permaneceu dentro do viewport.

## Automação e evidências

- Smoke novo: `tests/js/pgm-workflow-smoke.mjs`, restrito ao host/porta QA `127.0.0.1:8028`; usa somente dados públicos do acervo e verifica layout, resposta, fontes, expansão, PDF, abstenção e gate anônimo.
- Wrapper: `scripts/normative_qa.py` permite somente esse script exato; `src/tests/test_normative_qa_guard.py` verifica que argumentos extras são recusados.
- Relatório JSON gerado fora do checkout em `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-smoke\pgm-workflow-smoke.json`.
- Screenshot sanitizado: `docs/research/screenshots/pgm-workflow-20261008.png`.
- Migração QA: após autorização limitada a QA :8026, foi constatado que nenhuma migration de P-005 estava pendente; `legislation.0027_collectionevidenceversion` pertence à P-016. Ela foi aplicada por engano ao banco QA isolado, excesso de escopo registrado no diário de execução. É aditiva; não alterou PDFs, normas, extrações, decisões de revisão ou produção. Não a reverti nem fiz outra escrita.

## Verificações executadas

- Smoke Playwright/Puppeteer, com PDFs do acervo real local: **passou**; 4 evidências, 1 norma agrupada, PDF íntegro e resposta sem fonte no cenário inconclusivo.
- `test_qa_archive_rag.py` + `test_normative_query.py`: **85 passed**.
- `test_collection_evidence_versions.py` após migration no QA: **9 passed**.
- `manage.py check`: sem problemas; readiness QA `:8026` e `:8028`: HTTP 200.
- Ruff nos arquivos Python de fallback: passou; `git diff --check`: passou, mantendo o aviso de line endings preexistente em `docs/audit/2026-10-02/http-events.jsonl`.
- Usuários externos/assessores, decisão jurídica, dispositivo realmente alterado, comparação temporal revisada, gold jurídico e produção: **não testados**.

## Interpretação

O Jurix consegue descobrir remissões nos PDFs locais e apresentar as evidências agrupadas, abrir a fonte original e abster-se quando não localiza a cadeia. A experiência ainda não cumpre o uso seguro pela PGM para concluir se um dispositivo foi alterado: o PDF não foi revisado, não existe cadeia adjudicada para a pergunta, a ausência de cobertura deve continuar sendo tratada como inconclusiva e o fluxo autenticado de revisão permanece por validar. Nenhuma métrica desta execução demonstra precisão jurídica ou ganho sobre o processo de trabalho da PGM.

## Repetição da pergunta de alteração — LC 120/2010, Art. 18 — 08/10/2026

No QA `:8012`, perguntei: “Houve alteração ou revogação do Art. 18 da Lei Complementar nº 120/2010 depois de 2010? Preciso conferir a redação antes de utilizá-la em uma fundamentação.” O Jurix exibiu a redação arquivada do Art. 18 (“O Vencimento Básico percebido pelo servidor não poderá ser inferior ao Salário Mínimo Nacional vigente.”), citou uma fonte e declarou que o lote não contém uma cadeia posterior revisada; portanto, não confirmou alteração, revogação ou vigência atual. Orientou verificar a linha do tempo normativa e os atos oficiais.

O drawer mostrou o excerto e o estado pendente de revisão. Após F5, conversa, URL, resposta e fonte permaneceram disponíveis. Clicar na citação abriu uma nova aba com o PDF local da LC 120/2010 e um fragmento de texto do dispositivo. A rota e o título do PDF foram observados; a leitura visual do conteúdo no viewer não foi confirmada nesta repetição.

O PDF é um documento municipal real do acervo local, mas a extração continua pendente e sem segmentação concluída. Isso valida o comportamento de recuperação/abstenção e persistência em QA, não prova se houve alteração posterior, não confirma vigência e não é parecer. Não houve revisão, promoção ou escrita no documento; nenhum dado de processo ou pessoa foi usado. Não houve participação de procurador/assessor, então isto não substitui teste de usuário da PGM.

## Caso temporal prioritário — Código de Obras e LC 55/2004

Em 08/10/2026, confrontei fontes públicas oficiais do SAPL com o QA local:

- A [LC 198/2021 e seu PDF original](https://sapl.natal.rn.leg.br/norma/925) remetem à LC 55/2004 nos arts. 1º, 2º, 4º e 6º. No chat da instância QA, Jurix enumerou esses quatro artigos e avisou corretamente que remissão não prova alteração ou revogação; o documento local segue pendente de revisão.
- A [LC 251/2024](https://sapl.natal.rn.leg.br/norma/4030) é de regularização urbanística. O [Código de Obras é a LC 258/2024](https://sapl.natal.rn.leg.br/norma/4052), cujo [PDF oficial](https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2024/4052/lei_complementar_no_258_2024.pdf) diz, no art. 259, que se aplicam as normas vigentes na data do protocolo; o art. 260, IV, revoga a LC 55/2004; e o art. 262 trata dos processos protocolados antes da entrada em vigor e ainda sem despacho decisório.

**Retificação:** uma busca textual inicial confundiu a LC 251 com o trecho do Código de Obras. A checagem da página SAPL e do PDF normativo corrigiu a identificação para LC 258; nenhuma resposta jurídica foi baseada na busca ambígua.

Na aplicação QA `:8028`, a pesquisa local por `258/2024` encontrou **0 PDFs candidatos** e a biblioteca consolidada também não encontrou a norma. Perguntei ao assistente sobre a LC 258 e os arts. 259/260/262. A resposta foi de evidência insuficiente, sem fonte, citação ou afirmação de revogação/inexistência, e sem erro de browser. Isso é uma abstenção segura, mas não permite ao assessor resolver pelo produto esse caso de risco temporal. Um teste posterior pode incluir a LC 258 como candidato de QA não revisado, depois de autorização para importação; essa inclusão não equivale a adjudicação nem a consolidação.

Esse cenário foi executado como teste técnico com corpus municipal local incompleto, não como consulta jurídica, caso de processo da PGM ou sessão de usuário/procurador. Não houve participante humano, decisão institucional nem validação de qual norma se aplica a um processo individual.

## Saúde operacional observada no QA

Nova leitura somente-leitura em `:8028`: SAPL e DOM Natal retornaram `not_configured`, com zero checkpoints; o worker QA respondeu na fila `normative_qa`. Os endpoints de liveness e readiness responderam HTTP 200 (`ready`), mas esse estado não comprova sincronização, cobertura ou frescor jurídico. Não houve chamada de ingestão ou escrita no corpus.

Regressão focal de checkpoints, saúde da fila e agendamento SAPL: **33 passed**; Ruff passou. P-018 segue parcial até duas rodadas reais idempotentes, descoberta de publicação atrasada e teste de recuperação/outage; a fonte não configurada impede afirmar atualidade do acervo.

## Reflow e navegação fora do viewport

### Repetição em 08/10/2026 — cadeia com redação de origem disponível

Reexecutei o smoke PGM contra `:8028` com PDFs locais do acervo QA. A pesquisa por “resíduos sólidos” encontrou quatro candidatos, todos marcados “Pendente”; a tela não os confundiu com normas consolidadas. A consulta LC 198/2021 → LC 55/2004 recuperou Arts. 1º, 2º, 4º e 6º, mostrou o aviso de revisão e abriu o painel com quatro evidências agrupadas. O PDF local respondeu 200, `application/pdf`, 193.918 bytes e assinatura/EOF válidos.

Na pergunta se a LC 198/2021 alterou o Art. 21 da LC 55/2004, o acervo apresentou **uma** evidência: redação de origem do Art. 21 da LC 55/2004. A resposta não atribuiu alteração à LC 198/2021 e manteve inconclusivos a alteração/revogação posterior e a vigência. Corrigi o contrato do smoke: “não há prova da cadeia” não significa “não existe fonte do texto original”. A regressão valida exatamente essa distinção.

O smoke passou em 320, 360, 640, 768, 1280 e 1920 px para Assistente e Pesquisa; sem overflow horizontal, sem controle focável fora do viewport, landmarks principais presentes. Drawer: Escape, expansão de todas as evidências e atualização do rótulo; rota de curadoria bloqueada para anônimo. Relatório e cinco capturas ficaram somente no diretório temporário QA `pgm-smoke-continuation-20261008`.

O screenshot de 1280 px motivou ajuste de legibilidade: prévias e trechos completos foram elevados a 14 px, a contribuição a 13 px e os alvos de expansão/ações a 44 px. O smoke Chromium conferiu os estilos computados em runtime (14/14/13 px e 44/44 px) e a geometria do drawer (480 px, integralmente dentro de 1280 px). Isso corrige tamanho tipográfico/alvo, mas não substitui medição de contraste WCAG, zoom nativo 200%, baixa visão ou teste com assessores; esses itens seguem não testados.

Repeti o smoke Puppeteer em `:8028` a **320, 360, 640, 768, 1280 e 1920 CSS px**, nas telas Assistente e Pesquisa Jurídica. 640 px é apenas uma aproximação de layout para viewport 1280 px com zoom de 200%, não zoom nativo. Todos os GETs retornaram 200, `scrollWidth` igual à largura do viewport, o landmark `main` presente e zero controles focáveis fora do viewport que não estivessem inertes/ocultos. O resumo dos PDFs candidatos permaneceu visível e dentro da largura em todos os tamanhos.

Capturas verificadas visualmente: assistente e pesquisa a 320 px, em `%TEMP%\jurix-pgm-goal-qa-20261008\evidence\p021-zoom-equivalent-20261008-r2\`. A composição empilha os controles sem overflow horizontal; foco real por teclado, zoom nativo, leitores de tela e sessões de assessores não foram avaliados. Esse teste não fecha o gate WCAG nem P-021.

## Cenário de visão geral e follow-up temporal — 08/10/2026

No QA `:8028`, pesquisei `258/2024`. A interface mostrou **0 normas consolidadas** e **1 PDF candidato**, com status pendente e extração completa de 99 páginas. A pergunta ampla sobre a LC 258 recuperou 48/264 artigos e avisou que a síntese e os anexos eram parciais. A geração não nomeou os artigos no texto, embora as citações fossem clicáveis; esse defeito levou a uma validação que exige correspondência entre artigo visível e fonte citada e a um fallback que imprime `Art. N` antes de cada trecho literal. Na repetição, foram mostrados sete artigos amostrados com sete fontes; após F5, a resposta e as fontes foram restauradas e clicar `Art. 46` abriu sua evidência.

No mesmo chat, o follow-up sobre processos anteriores à vigência recuperou o Art. 262, a exceção de manifestação formal e os fatos do processo que precisam ser verificados. A cópia arquivada segue pendente de revisão; o comportamento não confirma vigência, completude do Código de Obras nem aplicação a processo concreto. A suíte QA relacionada de 118 testes passou. Nenhum revisor humano participou, portanto não é validação jurídica da PGM.

## Pesquisa visual de PDFs candidatos e grafo vazio — 08/10/2026

No Chromium em `http://127.0.0.1:8028`, abri `/explorar/` e `/normas/`. A primeira mostrou o estado vazio com a explicação de que PDFs ainda pendentes não são tratados como normas consolidadas nem geram relações públicas no grafo. Em `/normas/`, naveguei da página 1 à 2 e à última: 6.664 candidatos em 167 páginas (40 por página, 24 no final), sem overflow/repetição perceptível nos cards; o filtro local modifica a página atual e seu estado sem correspondência é explícito.

O rótulo “PDF candidato” e a retirada do índice interno da origem tornam a distinção entre acervo pendente e legislação consolidada mais legível. O contador 6.664 não é uma contagem do ZIP sozinho: são 6.663 PDFs no ZIP mais um PDF da LC 55/2019 adicionado separadamente para o ensaio QA, ainda pendente e com extração parcial. Na reexecução final, os testes de rotas passaram (**57 passed**), assim como Ruff e `manage.py check`; a readiness QA respondeu 200 com database/pgvector/Redis/migrations em `ok` (Ollama e corpus foram marcados como `skipped`).

Avaliação de uso: a lista já permite localizar/paginar candidatos, mas o grafo continua vazio e não responde à necessidade central de rastrear alterações e vigência. O próximo avanço não é desenhar relações a partir de remissões brutas: exige identificação de edição, extração confiável e revisão humana antes de publicar arestas jurídicas. Esta sessão não revisou nem consolidou nenhum dos candidatos.

Na mesma inspeção, detectei uma inconsistência de hierarquia: o H1 e o título da aba diziam “Normas consolidadas”, apesar de a página listar o acervo pendente e informar zero normas consolidadas. Troquei ambos para “Normas e acervo”, mantive as métricas separadas e verifiquei o novo título/H1 no Chromium depois de reiniciar apenas o runserver QA sem autoreload. A regressão de rotas passou (**57 passed**), com Ruff e `git diff --check` aprovados.

### Pesquisa por proximidade e correção de espaçamento — 08/10/2026

Na busca local `/pesquisa/?q=destinação+final+de+resíduos+sólidos`, todos os PDFs que continham cada termo em qualquer posição recebiam a mesma pontuação; por isso a lista dependia da ordem de entrada. Troquei o desempate para ranking textual PostgreSQL em português com normalização por tamanho, sem excluir candidatos. Uma regressão sintética verifica que a frase concentrada antecede termos espalhados; ela prova ordenação técnica, não precisão jurídica.

No acervo QA real, essa consulta listou Decreto 9365/2011, LC 55/2004 e LC 258/2024, cada qual com trecho e página; a consulta ampla `resíduos sólidos` mostrou quatro candidatos. Todos continuam pendentes de revisão, e os excertos sustentam apenas descoberta textual. Também reproduzi visualmente e corrigi a margem negativa que encostava o botão “Buscar no acervo normativo” no aviso sobre PDFs não validados. O runtime após reinício do servidor QA confirmou separação visual entre o botão e o aviso.

Verificação desta rodada: `test_document_search.py` + `test_workspace_routes.py`: **72 passed, 1 skipped**; teste JS `norma_ui_v3.test.mjs` executado pelo runner do projeto sem falhas reportadas; Ruff e `git diff --check` passaram. Ainda faltam benchmark de latência no acervo completo e validação do ranking contra gold jurídico revisado. Nenhum documento, estado de revisão ou dado do corpus foi alterado.

### Conferência temporal e cobertura desconhecida — 08/10/2026

Na inspeção estática do serviço `/conferir/`, encontrei que duas projeções completas com texto idêntico podiam produzir “Sem mudança encontrada” sem haver um escopo revisado de cobertura documental. Corrigi essa conclusão: o serviço agora só pode dizer “Sem mudança no escopo revisado” quando um escopo da mesma jurisdição/série cobre as duas datas, o corte final e não tem lacunas nem pendências. Sem esse escopo, o texto igual continua sendo evidência observada, mas o resultado é **inconclusivo** e explica a limitação. A tela distingue a cobertura do corpus das projeções da norma.

Verificação: `test_foundation_check.py`, `test_foundation_reference_parser.py`, `test_foundation_check_workspace.py` e `test_corpus_coverage.py`: **23 passed**; Ruff e `git diff --check` passaram. O comportamento foi verificado com testes QA isolados, inclusive cobertura desconhecida e um escopo revisado válido. Não houve sessão legítima de revisor para exercitar `/conferir/` autenticado no navegador; não gravei escopos de cobertura ou decisões no banco QA. Portanto a cobertura real continua desconhecida e nenhuma conclusão de ausência de mudança é sustentada para o acervo corrente.

Na revisão seguinte, corrigi o seletor CSS do estado de sucesso para corresponder a `unchanged_in_checked_scope`, atualizei a URL cache-busted e acrescentei um teste que proíbe o estado antigo genérico. A suíte Python foi repetida contra o test DB SQLite preservado por `--reuse-db`; duas inserções com a chave primária fixa `municipal` falharam por estado residual, então os testes agora atualizam essa única linha para revisões numeradas novas sem apagar o DB nem seus snapshots imutáveis. Repetição final: Python **23 passed**, JS **51 passed**, Ruff e `manage.py check` sem issues. A ferramenta autenticada segue fora do runtime browser por falta de uma sessão institucional legítima; os testes de template não substituem esse teste.

Também reabri no Chromium QA a conversa pública sobre a LC 258/2024 e ativei “Baixar evidências consultadas em JSON”. O controle mudou para “Download do pacote de evidências iniciado”, sem erro visível. Isso confirma a ação do usuário na UI, mas não inspecionei o arquivo baixado nem trato o clique como prova do conteúdo/exportabilidade jurídica; a verificação do payload permanece coberta apenas pelos testes do exporter até uma checagem direta do artefato.

Em nova navegação de usuário no QA, pesquisei `LC 55/2004`: a tela informou **0 normas consolidadas** e **1 PDF candidato**, com aviso de que a extração não é texto validado. Abri a ficha: o arquivo se identifica como cópia consolidada de julho de 2019, mas o Jurix mantém identidade e extração pendentes, condição de uso desconhecida, extração parcial (47 páginas) e ausência de índice confiável de artigos. Não tratei o nome do arquivo como prova de versão vigente. A rota local respondeu HTTP **200**, `application/pdf`, 731.250 bytes, assinatura `%PDF-` e marcador `%%EOF`. A aba PDF do navegador embutido apareceu vazia, mas um reteste posterior no Chrome headless renderizou a página 1 e miniaturas das 47 páginas; a captura está em `docs/research/screenshots/pgm-lc55-candidate-pdf-chrome-20261008.png`.

Após corrigir os testes que pressupunham um banco limpo, rodei a suíte Python integral pelo runner QA com PostgreSQL: **1.602 passed, 6 skipped, 0 failed, 8 warnings** em 214,69 s. A rodada direta sem o runner foi inválida para este repositório (selecionou `config.settings`/SQLite e deixou ausentes variáveis de isolamento necessárias), resultando em 21 falhas de ambiente; não foi usada como gate. `npm test --prefix tests/js` terminou com exit 0; o orçamento arquitetural passou sem findings. Os skips explícitos de revisor/serviço continuam pendentes, assim como inspeção direta do arquivo JSON exportado e visualização legível do PDF no browser.

Checagem operacional P-018 no QA: um worker respondeu à fila `normative_qa`, mas os checkpoints SAPL e DOM continuam não configurados (zero escopos e nenhuma sincronização bem-sucedida). O status de readiness da fonte ficou não-zero, como deveria; não iniciei sincronização. Nas referências oficiais, o DOM é descrito como meio de publicidade de atos e o portal indexa edições ordinárias/especiais, mas as páginas consultadas não concedem uma licença geral de redistribuição. O termo da Biblioteca Virtual do Natal é específico a obras submetidas individualmente com autorização do titular. Mantive, por isso, a condição de uso dos documentos como desconhecida e sem qualquer ingestão adicional; não é inferência jurídica de titularidade, apenas limite operacional de licenciamento.

### Exploração do grafo e retomada de sincronização — 08/10/2026

Reabri `/explorar/` no Chromium QA `:8028` como visitante. A tela mostra os filtros (norma/ementa, tema, espécie, ano e intervalo de publicação), informa **0 normas** e explica que PDFs pendentes não viram relações jurídicas públicas. O estado é honesto e não fabrica arestas; porém, com zero normas, os filtros ocupam espaço sem possibilidade real de explorar relações. O grafo continua sem utilidade operacional até haver uma base revisada/consolidada. Não apliquei filtros nem alterei dados nesta visita; a árvore de acessibilidade confirmou os controles e o estado vazio. Não gerei screenshot novo nesta rodada.

Em P-018, o teste novo de recuperação simulou falha de rede entre páginas e confirmou cursor/URL/token persistidos, ausência de reconciliação prematura e retomada completa no retry: **21 testes focados passaram**. Em uma consulta HTTP somente de leitura ao índice oficial do DOM (outubro/2026), o client listou seis edições (1–7/10, incluindo uma especial); não baixei PDFs nem atualizei checkpoint. Isso prova alcançabilidade e parsing do índice naquele momento, não sincronização, cobertura completa, licença ou status jurídico dos atos.

O estado vazio de `/explorar/` ainda mostrava cinco filtros sem qualquer norma consolidada. Ajustei a view/template para ocultar o formulário somente quando o conjunto-base é zero, mantendo-o disponível se filtros do usuário produzirem um resultado vazio numa base não vazia. A asserção da rota faz parte dos **77 testes aprovados e 1 skip** da rodada focada. Runtime browser após reinício do servidor `--noreload` ainda pendente nesta etapa; não reivindico validação visual até fazê-la.

### Pergunta de transição sem artigo explícito — 08/10/2026

No QA `:8029`, usei o PDF local arquivado da LC 258/2024 para perguntar como um assessor deveria analisar um licenciamento protocolado antes da lei, ainda sem despacho, e quais fatos o PDF não resolve. O primeiro runtime mostrou o Art. 262, mas apenas como citação/transcrição, sem explicar os próximos fatos a apurar. Corrigi a classificação contextual e repeti a pergunta sem mencionar o número do artigo: a resposta passou a ligar o Art. 262 ao PDF, listar data do protocolo, entrada em vigor, despacho e opção formal pela lei nova, e ressalvar que a extração não prova os fatos nem permite concluir qual regime rege um processo concreto. O streaming terminou e o painel Fontes Consultadas mostrou uma evidência.

Suíte QA do RAG arquivado: **88 passed**; Ruff, `manage.py check`, `compileall` e `git diff --check` passaram. A UI foi inspecionada em runtime, mas nenhuma screenshot foi salva. Esta é uma prova funcional sobre uma extração ainda pendente de revisão; não constitui parecer jurídico, validação da vigência da LC nem adjudicação de caso real. Nenhum documento ou estado de revisão foi alterado.

### Repetição do fluxo PGM e consulta da LC 198/2021 — 08/10/2026

O smoke de navegador em `:8028` passou em 320, 360, 640, 768, 1280 e 1920 px sem overflow horizontal; testou localização textual de PDFs, resposta a quatro remissões da LC 198/2021, fontes agrupadas, expansão, abertura/validação estrutural do PDF e uma consulta de alteração que permaneceu inconclusiva. A rota autenticada de conferência continuou exigindo login. Relatório e capturas brutas ficaram fora do repositório, no diretório QA temporário informado ao smoke.

Na inspeção manual do candidato local `LeiComplementar_20211220_198_.pdf`, a extração de duas páginas mostra remissões aos Arts. 21, 44 e 88 da LC 55/2004 e aplicação subsidiária da LC 55/2004 e LC 82/2007. Não tomei essas referências como atos de alteração. O documento continua pendente de identidade/segmentação/revisão; sua condição de uso é desconhecida.

O endpoint do PDF retornou 200, `application/pdf`, 193.918 bytes; PyMuPDF abriu duas páginas e extraiu texto. A captura da aba PDF no navegador embutido ficou escura, mas o Chrome headless local exibiu a LC 198/2021 e a LC 258/2024 pelos mesmos endpoints; também exibiu a LC 55/2004 candidata, com 47 páginas. Portanto, a hipótese mais provável é limitação da captura/navegador embutido, não falha do arquivo/endpoint. As imagens estão em `docs/research/screenshots/pgm-lc198-pdf-chrome-20261008.png`, `pgm-lc258-pdf-chrome-20261008.png` e `pgm-lc55-candidate-pdf-chrome-20261008.png`. Ainda não testei o clique do drawer em uma sessão visual normal do Chrome. Essa verificação de renderização não confirma identidade jurídica, vigência nem licença.

### Regressão técnica após os fluxos reais — 08/10/2026

A suíte Python integral QA terminou com **1.604 passed, 6 skipped, 0 failed, 8 warnings** em 208,58 s. `npm test --prefix tests/js` terminou com exit 0; testes condicionais de browser não configurados foram reportados como skips. Orçamento arquitetural passou sem findings; contrato documental, Ruff e `manage.py check` passaram.

`manage.py check --deploy` terminou com erro no perfil QA por `DEBUG=True` e chave de desenvolvimento; também apontou HSTS/redirect HTTPS e cookies seguros ainda não configurados. Não alterei valores locais nem tentei fazer QA parecer produção. O resultado é evidência contra a prontidão de deploy deste profile, não certificação de settings do ambiente produtivo.

Continuam não executados: zoom nativo 200%, avaliação consentida com assessores, workflow autenticado de conferência por revisor legítimo, restore operacional e gold adjudicado. O teste responsivo do smoke cobre larguras CSS, não substitui zoom/tecnologia assistiva. Portanto, sucesso técnico automatizado não equivale a aprovação de uso na PGM.

### Abrir o PDF pelo cartão de fonte — 08/10/2026

Repeti o fluxo completo no Chrome headless contra o QA isolado `:8028`, usando a extração local da LC 198/2021 ainda pendente de revisão. Após a resposta e abertura do drawer, cliquei em “Abrir no PDF”: abriu uma nova aba na URL local do documento e a conversa ficou aberta na original. A captura mostra o viewer do Chrome renderizando a página 1 e o trecho da remissão destacado. O mesmo href respondeu HTTP 200, `application/pdf`, assinatura PDF válida. Screenshot: `docs/research/screenshots/pgm-source-card-opened-pdf-20261008.png`; relatório JSON em `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-smoke-source-click-final-20261008\pgm-workflow-smoke.json`.

A execução completa do smoke terminou `passed` (exit 0), cobrindo também 320, 360, 640, 768, 1280 e 1920 px, sem overflow horizontal ou controles focáveis fora da viewport; o endpoint de conferência continua redirecionando visitantes para login. O teste inicialmente expirava em `networkidle0`; o visualizador PDF do Chromium não emite esse estado consistentemente. Corrigi o smoke para aguardar a URL da nova aba, mantendo checagem independente de HTTP/MIME e screenshot do viewer. A captura é evidência do fluxo de abrir/renderizar, não valida revisão/identidade/licença do PDF. Continuam pendentes zoom nativo 200%, revisor autenticado legítimo e avaliação consentida com assessores PGM.

Na repetição seguinte, cliquei também em “Baixar evidências consultadas em JSON”. O download criou `jurix-evidencias-2026-10-08.json` no diretório QA temporário; o pacote `jurix-evidence-v1` contém quatro fontes e conserva IDs de citação, norma, dispositivo e trecho. O relatório sanitizado registra apenas schema, contagem e nomes dos campos. O artefato JSON não foi copiado ao repositório, pois contém excertos legais brutos.

O smoke final acrescentou navegação do drawer por teclado: `Shift+Tab` a partir do botão de fechar permaneceu dentro do painel, e `Escape` fechou o drawer restaurando o foco no botão “Ver fontes”. Resultado final: **12 checks passed**, sem erros JavaScript não tratados; viewport responsivo, exportação, fonte PDF e gate anônimo de revisão passaram na mesma execução. IDs do corpus QA usam `qa:<hash>`; o teste aceita esse namespace de QA e o namespace `jurix:` de produto, exigindo em ambos identificador e campos jurídicos preenchidos. Isso não cobre NVDA/tecnologia assistiva nem zoom nativo de navegador a 200%.

### Checkout corrente e estado de Explorar relações — 08/10/2026

Uma primeira observação de `/explorar/` em `:8028` encontrou filtros visíveis apesar de “0 normas”. Antes de alterar código, comparei uma instância QA nova em `:8029`: ela está usando o checkout corrente e mostra estado vazio coerente, sem filtros quando não há normas-base, sem relações fabricadas e com link para a busca de PDFs. O processo `:8028` iniciou às 18:37, antes do checkout atual; deixei-o intacto e não uso seus resultados isolados como prova da versão corrente.

Reexecutei o smoke PGM inteiro em `:8029`: **13 checks passaram, 0 erros de página**, incluindo o estado vazio do grafo em 320/360/640/768/1280/1920 px; nenhuma rolagem horizontal, e o link do vazio aponta para `/pesquisa/`. Screenshot: `docs/research/screenshots/pgm-graph-honest-empty-state-20261008.png`. O teste confirma que candidatos pendentes não são apresentados como relações normativas; com zero normas revisadas, o grafo continua sem conteúdo útil. Isso não cobre zoom nativo a 200%, tecnologia assistiva nem avaliação com usuários da PGM.

O mesmo smoke em `:8029` confirmou novamente a abertura do PDF pelo card da fonte; a captura dessa execução está em `docs/research/screenshots/pgm-source-card-opened-pdf-current-20261008.png`.

### Filtro temporal e abstenção — 08/10/2026

Na UI do checkout atual, defini “Redação normativa em” para `01/01/2020` e perguntei pela redação do Art. 21 da LC 55/2004 naquela data. Capturei a requisição real: `as_of=2020-01-01` e `qa_archive_corpus=true`. O app declarou que não encontrou evidência histórica suficiente, explicitou que não apresentaria a redação atual como histórica e não mostrou novas fontes para esse turno. Resultado do smoke completo: **14 checks passed, 0 erros de página**. Captura: `docs/research/screenshots/pgm-temporal-abstention-2020-20261008.png`.

O resultado é o comportamento seguro esperado para o corpus QA sem snapshots/cadeia adjudicada; não prova que uma norma específica tinha essa redação em 2020 nem testa comparação `antes/depois` com versões históricas verificadas. A validação continua pendente de cadeia real revisada por especialista.

### Correção de placeholder em `/normas/` e reexecução no checkout atual — 08/10/2026

A screenshot anterior em 320 px mostrava o placeholder da busca cortado no meio da palavra. Reduzi o texto para “Número ou tema” e acrescentei ao smoke uma medição de largura do texto em relação à área interna do input. A asserção passou em 320, 360, 640, 768, 1280 e 1920 px; conferi a captura de 320 px e o placeholder está inteiro, sem overflow horizontal.

Para não confundir código atual com um `runserver --noreload` antigo em `:8030`, mantive os processos existentes e iniciei uma instância QA independente com o checkout corrente em `:8010`. O percurso completo passou: busca textual em PDFs reais pendentes, filtro/listagem dos 6.664 candidatos, ficha e PDF, exportação estruturada, fontes durante a conversa, pergunta sobre a cadeia LC 55/2004 ↔ LC 258/2024, abstenção para data histórica sem snapshot e gate de login para revisão. Os 40 cartões continuam sendo apenas a primeira página da interface, não cobertura integral de extração.

`src/tests/test_workspace_routes.py`: **56 passed, 1 skipped**. Smoke Chromium: status `passed`, incluindo o novo critério do placeholder e os breakpoints acima. Captura: `docs/research/screenshots/pgm-normas-320px-placeholder-fixed-20261008.png`; JSON sanitizado/estruturado do smoke fica na pasta QA temporária. Os textos usados vêm de PDFs municipais autênticos ainda pendentes de revisão. Nenhum candidato foi aceito/promovido; não considero esses resultados prova jurídica, gold, zoom nativo 200% ou avaliação com procuradores.

Na primeira regressão JavaScript integral, uma expectativa literal ainda exigia o placeholder antigo. Atualizei somente essa expectativa para o texto curto, preservando o teste. A repetição com `JURIX_QA_BASE_URL=http://127.0.0.1:8010` terminou com **exit 0** e executou também o smoke responsivo condicional; `manage.py check`, contrato documental e `git diff --check` passaram.

### Regressão da mesa de revisão — 08/10/2026

Pelo runner `scripts/normative_qa.py`, executei `src/tests/test_document_review_workspace.py`: **12 passed, 0 failed** no perfil PostgreSQL/Redis QA. Os casos cobrem acesso/permissão, CSRF, rejeição de fingerprint obsoleto e separação entre aceitar extração, promover documento e revisar segmentação. O teste usa fixtures transacionais e não alterou nenhum candidato PDF real.

Isso confirma controles de código, não a conclusão da curadoria. A revisão visual autenticada com um revisor autorizado e a decisão humana sobre identidade/uso do PDF seguem não executadas; não trato o fluxo como apto a consolidar legislação.

### Serviço e workspace de conferência de fundamentação — 08/10/2026

`src/tests/test_foundation_check.py` + `src/tests/test_foundation_check_workspace.py`: **13 passed, 0 failed** pelo runner QA. O contrato distingue referências individualmente, não mistura artigos homônimos entre normas e mantém buscas ausentes/incompletas inconclusivas; a rota de workspace exige autenticação. São testes automatizados em banco transacional, não uma sessão com procurador nem validação de conteúdo jurídico real. Não colei peça de processo ou dado sensível; o uso visual autenticado e o zoom nativo 200% seguem pendentes.

### Estado de atualização de fontes — 08/10/2026

O diagnóstico QA somente-leitura confirmou `sapl=not_configured` e `dom_natal=not_configured`, ambos com zero escopos/checkpoints; a fila `normative_qa` tinha um worker respondendo. Logo, a fila local está visível, mas não existe evidência de atualização dos repositórios oficiais nesta instalação. O health terminou não-zero deliberadamente. Não contatei as fontes externas nem iniciei sync. Para uso decisório na PGM, não se deve interpretar o acervo local como atualizado.

### Estados de cobertura na conferência — 08/10/2026

A inspeção apontou enumerações internas em inglês (`unknown`, `partial`, `reviewed`) e `completeness=partial` expostos literalmente. A interface agora apresenta “desconhecida”, “parcial” e “revisada somente nos escopos listados”; quando o processamento está completo, avisa que isso não certifica cobertura jurídica integral. Os marcadores `in_force` e `revoked` dos dispositivos também viraram descrições explícitas de projeção técnica, sem afirmar aplicabilidade aos fatos. Não alterei o serviço nem os dados.

Regressão QA de workspace, serviço e cobertura: **18 passed, 0 failed**; `manage.py check`, Ruff e `git diff --check` passaram. Isso é correção de clareza, não evidência nova de atualização. SAPL/DOM seguem sem escopos, e a cobertura real permanece desconhecida.

### Leitura real, sem gravação, do Diário Oficial — 08/10/2026

- Usei o adapter existente para consultar somente a listagem oficial do DOM de Natal em outubro/2026. Ele identificou a edição especial nº 6208 separada das ordinárias e a edição nº 6212 de 08/10. Li esse PDF somente em memória: 349.875 bytes, 23 páginas, não criptografado e 201.895 caracteres extraíveis; SHA-256 `edc0996c1b8581be15a02f4b7061e757259d238f470d42f65eec8182120ae8b`. A listagem pública também pode ser conferida no [portal oficial do DOM](https://www2.natal.rn.gov.br/dom/index.php?p=d).
- Não salvei o PDF, não escrevi no banco QA, não criei checkpoint/candidato e não rodei schedule. As regressões offline do adapter, staging e health passaram (**32/32**). Isso comprova que o client atual consegue ler uma edição real, mas ainda não configura atualização diária nem faz análise dos atos contidos na edição; P-017/P-018 continuam parciais.

### `/normas/` — navegação de PDFs candidatos — 08/10/2026

Usei o runtime QA corrente `:8029` como visitante. A tela informa 0 normas consolidadas e 6.664 PDFs em revisão; os 40 cartões visíveis estão marcados como PDF candidato. Busquei `Lei Complementar nº 120/2010`, abri sua ficha documental e confirmei status pendente, aviso explícito de que a extração não foi revisada, ação para abrir o PDF arquivado e ausência do formulário de revisão sem login.

O smoke Chromium passou em 320, 360, 640, 768, 1280 e 1920 px, sem overflow horizontal nem controles focáveis deslocados para fora da viewport. Revisei visualmente os screenshots em 320 e 1280 px. Em 320 px, o placeholder do campo (“Número, tipo ou em...”) é cortado pela largura do controle; apesar de não impedir digitação/filtro, é um refinamento visual/usabilidade pendente. Screenshots: `docs/research/screenshots/pgm-normas-320px-20261008.png` e `docs/research/screenshots/pgm-normas-candidate-detail-1280px-20261008.png`.

Resultado total do smoke: **16 verificações passaram, 0 erros de página**. A primeira rodada detectou que o HTTP 200 do gate anônimo estava sobrescrevendo o campo textual `passed` no JSON; corrigi a ordem do registro do teste e repeti o smoke completo, agora com 16/16 status textuais `passed`. O teste demonstra descoberta e abertura de um candidato no acervo real de QA, não que ele seja norma consolidada, esteja vigente, possa ser redistribuído, ou tenha texto/identidade adjudicados. Nenhuma escrita de conteúdo jurídico, revisão ou promoção ocorreu.

### Consulta composta em linguagem natural — cadeia LC 258/2024 — 08/10/2026

Repeti no checkout corrente a pergunta sobre uma fundamentação antiga que usa o Art. 21 da LC 55/2004 e acrescenta “Considere também o Art. 260, inciso IV, e o Art. 262”. A primeira execução mostrou que a busca achava os trechos, mas o resolvedor conservador não associava os artigos sem repetição da norma e respondia para consultar cada referência separadamente.

A regra foi ajustada para aceitar a continuação explícita “Considere também/ainda” e “Inclua também/ainda”, vinculando apenas os artigos da frase seguinte à última norma nomeada. Sem esses marcadores, a regra de ambiguidade segue bloqueando a associação. Após reiniciar não o processo antigo, mas uma instância isolada atualizada em `:8030`, o browser mostrou três fontes corretas: LC 258/2024, Arts. 260 e 262, e LC 55/2004, Art. 21. A resposta descreveu a lista de revogações, a transição condicionada à data do protocolo e ausência de despacho, e o teor de origem do Art. 21; também indicou dados e fontes oficiais que ainda precisam ser conferidos, sem concluir que o dispositivo rege o caso.

Smoke completo: **17/17 checks**, zero erros JS; `test_qa_archive_rag.py`: **89 passed**. Screenshot: `docs/research/screenshots/pgm-lc258-transition-chain-20261008.png`. A consulta usou candidato PDF/extrator não revisado no QA: prova funcional de recuperação e rastreabilidade, não uma validação jurídica independente nem decisão para processo real.

Regressão final do checkout: pytest completo (**1.605 passed, 6 skipped, 0 failed, 8 warnings**), suíte JavaScript `npm test --prefix tests/js` exit 0 (repetida com `JURIX_QA_BASE_URL=http://127.0.0.1:8030` para retirar o skip do smoke responsivo), Ruff, contrato documental, orçamento arquitetural (`passed: true`) e `git diff --check` passaram. Esses gates de software não substituem a sessão de zoom nativo, tecnologia assistiva ou teste consentido com assessores.

### Geração local com Ollama e overview parcial — 08/10/2026

Na QA corrente `:8030`, o health verificou banco, pgvector, Redis e migrations, mas deixou Ollama/corpus como `skipped`; consultei Ollama local separadamente e após o fluxo confirmei `llama3:latest` e `nomic-embed-text:latest` carregados. O smoke de RAG em Chromium exigiu tentativa de geração no backend, e não aceitou fallback sem geração.

A comparação de Arts. 17/18 da LC 120/2010 retornou `sources → chunk → done`; geração medida em 3,884 s, fontes visíveis em 106 ms, primeiro texto em 4,007 s e conclusão da UI em 4,135 s. A resposta trouxe os dois artigos e citações clicáveis, preservadas na cópia Markdown. Testei também follow-up Art. 19, F5, abertura do PDF e cancelamento/retry. Um overview da norma de 39 artigos examinou 30 e mostrou amostra de seis, indicando que a cobertura não era integral. Isso é o comportamento honesto esperado, não uma visão completa da lei.

Auditoria estrutural do lote QA visível: 40/40 fichas e PDFs responderam/validaram, 2,158,094 bytes; os arquivos são autênticos do acervo recebido, mas extrações pendentes de revisão. A sessão, incluindo overview e cancelamento, terminou com exit 0 e zero erros de browser. O relatório sanitizado (`%TEMP%\jurix-pgm-goal-qa-20261008\pgm-live-ollama-final-20261008\live-rag-browser-smoke.json`) não registra os textos integrais. Screenshot: `docs/research/screenshots/pgm-ollama-overview-partial-20261008.png`. Métrica n=1 não é SLA nem estudo de qualidade, e os cenários sintéticos do smoke permanecem separados dos PDFs reais.

Persistem como não testados: participantes da PGM, zoom nativo 200%, tecnologia assistiva, adjudicação/gold jurídico e restore operacional. A geração observada não torna a LC 120/2010 revisada ou adequada para citação processual.

### Propostas de atos em uma edição oficial — revisão ainda necessária — 08/10/2026

O PDF público do DOM nº 6212/08-10/2026 foi novamente consultado pelo adapter e analisado apenas em memória. O parser gerou 78 sugestões de cabeçalho com página/offset: 66 portarias, 3 editais, 3 extratos, 2 avisos, 3 resoluções e 1 lei. A mesa de revisão agora pode apresentar sugestões não verificadas e abrir a página do PDF local, sem promover o documento nem certificar que o limite sugerido é um ato jurídico.

O detector ainda não identifica todas as variações vistas no diário; a contagem de linhas prefixadas por tipos (89) é um diagnóstico lexical, não um inventário de atos. A edição não foi persistida nem revisada por procurador. Portanto, esse avanço reduz trabalho de navegação, mas ainda não habilita o DOM como corpus operacional ou como prova de vigência.

Após integrar as sugestões à extração e à mesa de revisão, a suíte Python completa passou (**1.614 passed, 6 skipped, 0 failed, 8 warnings**) e `npm test --prefix tests/js` encerrou com **exit 0**. O smoke de browser que requer `JURIX_QA_BASE_URL` foi ignorado por não haver servidor explicitamente selecionado nesta rodada; os testes visuais/browser independentes do servidor passaram. Esta verificação cobre regressões do software, não revisão de ato por procurador.

Uma segunda edição real (especial nº 6208/03-10/2026, 136 páginas com texto extraível) revelou um caso sem número: foram sugeridos 8 cabeçalhos “Edital” com identidade nula. O parser deixou sem classificação 8 linhas iniciadas por “Resolução” cuja sequência textual não correspondia a epígrafe isolada. A edição regular nº 6212 segue com 78 candidatos. Esta revisão adiciona aviso de número ausente na tela e passou 89 testes direcionados; a suíte Python completa está pendente de repetição após o último ajuste. Nenhum PDF/candidato foi persistido ou promovido.

Atualização após a repetição da suíte completa: `python scripts/normative_qa.py --run python -m pytest src/tests -q --reuse-db --tb=short` terminou com exit 0: **1.616 passed, 6 skipped, 0 failed, 8 warnings (219,84 s)**. A execução não fez teste visual manual da nova lista de candidatos, não alterou o status jurídico dos PDFs e não cobre validação por procurador. P-017 permanece parcial.

A suíte JavaScript integral `npm test --prefix tests/js` também terminou com exit 0; os testes browser locais passaram. O smoke de reflow que necessita `JURIX_QA_BASE_URL` foi skip por não haver uma instância QA explicitamente selecionada nessa execução.

Checagem read-only ampliada do detector em quatro PDFs oficiais adicionais do DOM (edições 6206, 6207, 6209 e 6210 de outubro/2026), baixados e analisados em memória: foram sugeridos respectivamente **25, 30, 44 e 52** cabeçalhos em PDFs de 15, 9, 8 e 16 páginas. A composição por tipo foi registrada no diário de progresso; nenhum PDF foi salvo, candidato persistido ou ato aprovado. Essa amostra demonstra execução em mais layouts/edições, mas sem revisão visual/legal não mede precisão, cobertura ou aptidão para uso como corpus.

Em seis edições (6206, 6207, 6208, 6209, 6210 e 6212), uma checagem adicional confirmou em memória que cada cabeçalho coincide com o trecho extraído no offset registrado, cada span cabe nos limites textuais da página e nenhuma leitura atingiu o limite de páginas. Isso comprova integridade dos ponteiros produzidos; não comprova que o span termina no limite jurídico correto.

A seção de candidatos da mesa de revisão continua sem verificação visual autenticada: a rota exige conta de revisor e a sessão disponível estava na tela de entrada. Não inseri credenciais nem assumi um papel autorizado; o teste de template/rota cobre somente o contrato de renderização.

### Atualização operacional P-018 — 08/10/2026

Foi acrescentado um task de sincronização de edições do DOM com checkpoint por mês, overlap padrão de três meses, limite global retomável de cinco PDFs por execução (configurável até dez) e schedule QA separado, desligado por padrão. O schedule só é montado em settings QA após `JURIX_QA_DOM_NATAL_SYNC_SCHEDULE_ENABLED=1`; nenhum job real foi disparado e nenhuma edição foi gravada. Os testes de saúde/retomada e o contrato de schedule passaram; a suíte Python integral terminou com **1.622 passed, 6 skipped, 0 failed**. O teste de duas rodadas com o portal oficial e a descoberta real de uma edição atrasada permanece pendente.

O novo `manage.py inspect_dom_natal_editions` foi executado em QA como diagnóstico read-only: o catálogo consultado retornou 7 edições em outubro/2026, 0 itens para agosto/setembro, e 0 URLs correspondentes no acervo QA. O comando não baixou PDFs nem criou checkpoints/linhas. Health separado confirmou `dom_natal=not_configured` e worker `normative_qa=current` (1 worker); exit não-zero foi esperado por fonte ainda sem sync. Lista vazia não é prova de ausência histórica. Assim, há evidência de conectividade/catálogo, mas a fonte ainda não está sincronizada.

Revalidação da rodada em 09/10/2026: a suíte Python completa terminou com exit 0 (**1.623 passed, 6 skipped, 0 failed, 8 warnings em 215,25 s**), incluindo o limite global do lote DOM entre meses; `manage.py check`, orçamento de arquitetura e `git diff --check` passaram. A edição real continua não sincronizada: não houve download, persistência, checkpoint nem teste de duas execuções. P-018 segue parcial; os testes não são evidência de revisão jurídica ou de cobertura completa do DOM.

### Teste de fluxo PGM: regra de transição da LC 258/2024 — 09/10/2026

Na interface QA `:8029`, a pergunta ampla sobre processo de licenciamento protocolado antes da vigência selecionou os Arts. 75, 242 e 54 da LC 258/2024, embora não fossem a regra transitória perguntada. As três evidências estavam agrupadas corretamente sob a mesma norma, mas a correspondência temática era inadequada. Ao perguntar especificamente pelo Art. 262, a resposta recuperou o dispositivo correto, apresentou o texto, pediu conferência de protocolo/entrada em vigor/despacho/manifestação formal e disse que o PDF local não prova os fatos do processo.

Implementei filtro de retrieval para perguntas identificadas como escopo de transição e acrescentei testes de seleção e abstenção. O alvo `src/tests/test_qa_archive_rag.py` passou **91/91** e Ruff passou. No replay pela mesma `:8029`, a saída antiga continuou igual; a própria UI reporta “build local não identificado”, então não atribuo o resultado à versão alterada nem considero o runtime validado. A rota PDF devolveu HTTP 200 e `application/pdf`, mas a nova aba embutida permaneceu visualmente branca; abertura visual bem-sucedida não verificada. A regra foi lida de PDF local pendente de revisão, não de fonte oficial consolidada, e nenhum juízo foi feito sobre processo concreto.

No fluxo de descoberta separado em `:8028`, `/normas/` apresentou 0 normas consolidadas e 6.664 PDFs em revisão. A pesquisa pela regra pré-vigência localizou um candidato LC 258/2024 e mostrou trecho do Art. 262 na página 61, além dos avisos de que não é resultado consolidado. A ficha abriu e informou condição de uso desconhecida, extração automática pendente e falta de índice confiável de artigos. Isto é uma boa fronteira de transparência para um MVP de arquivo, mas a base consolidada vazia e o estado de revisão impedem prontidão jurídica de produto para uso decisório.

O link do artigo preserva `#:~:text=` no endereço, mas o teste visual do PDF não comprovou salto ao trecho: o viewer da aba existente `:8028` permaneceu na página 1 de 99 com um fragmento de Art. 260, e a nova aba `:8029` ficou visualmente branca mesmo com HTTP 200 `application/pdf`. A navegação para a citação, portanto, ainda precisa de fallback por página e verificação num navegador que renderize o PDF.

Revalidação pós-correção da recuperação de transição: suíte Python completa **1.625 passed, 6 skipped, 0 failed, 8 warnings em 220,39 s**; teste RAG focado **91/91**; Ruff, `manage.py check` QA, arquitetura e `git diff --check` passaram. O replay no `:8029` ainda não é conclusivo: build não identificada e resposta anterior persistente, então o runtime não demonstrou se a instância carregou o patch. O fix está coberto por testes, mas P-019 segue parcial até replay numa instância rastreável ao checkout. O documento local LC 258/2024 continua pendente de revisão; nenhum resultado deve ser usado como parecer ou fundamento consolidado.

Complemento runtime: uma instância do checkout foi iniciada pelo runner QA isolado em `127.0.0.1:8011` com versão explícita `qa-rag-2c2f8aa464a2` (fingerprint do módulo RAG) e revisão-base `0d9157aefeb1`. Na consulta ampla, a UI devolveu somente o Art. 262 da LC 258/2024, citou o trecho e separou as quatro verificações que dependem dos autos/publicação oficial; o drawer mostrou 1 evidência com ressalva de extração pendente. O link PDF deu 404 enquanto o servidor estava configurado com raiz temporária nova. O SHA do PDF correspondente já estava armazenado na raiz QA anterior; reusá-la sem copiar dados fez a rota responder HTTP 200 (`application/pdf`, 3.838.098 bytes). O viewer in-app continuou visualmente em branco, então somente o endpoint está aprovado, não a renderização nem o salto ao trecho. A instância QA foi iniciada com corpus local não consolidado; a resposta não é parecer e não conclui caso individual.

Teste de cadeia temporal em runtime: numa pergunta pública sobre obra protocolada antes da LC 258/2024, ausência de despacho e possível aplicação do Art. 21 da LC 55/2004, o assistente citou LC 258, Arts. 260, IV, e 262, além de LC 55, Art. 21. Explicou a revogação expressa e a regra de transição sem decidir a incidência no processo; listou protocolo, vigência oficial, despacho e opção formal como fatos a conferir. O drawer exibiu três fontes agrupadas em duas normas, todas marcadas como extração pendente. As rotas dos dois PDFs responderam 200 (`application/pdf`; 3.838.098 e 731.250 bytes). A visualização embutida dos PDFs continuou em branco; o salto ao texto não foi aprovado. É um cenário de teste construído com PDFs locais, não autos reais, parecer ou validação humana.

Conferência mecânica read-only dos bytes PDF usados: a LC 258/2024 tem 99 páginas; o texto pesquisável do Art. 260 está na p. 60 e o do Art. 262 na p. 61. A LC 55/2004 tem 47 páginas; o Art. 21 está na p. 8. O texto extraído das páginas confirma que os três trechos citados correspondem a esses dispositivos, inclusive a revogação expressa da LC 55 no Art. 260, IV, e as condições do Art. 262. Isto não certifica autenticidade, vigência ou correção jurídica e não altera o status pendente dos documentos.

### Pesquisa, relações e controle de acesso no QA rastreável — 08/10/2026

No checkout atual em `:8011`, pesquisei pela interface `licenciamento de obras`. A página retornou **0 normas consolidadas** e **5 PDFs candidatos**, explicitamente separados e rotulados como pendentes de revisão; os resultados incluíram LC 198/2021, LC 55/2004, LC 258/2024, Decreto 11.294/2017 e LC 136/2014. O texto da página alerta que extração automática não valida texto jurídico nem prova vigência. Abri a ficha da LC 258/2024: condição de uso “Desconhecida”, revisão “Pendente”, extração técnica de 99 páginas e ausência de índice confiável de artigos. O PDF abriu visualmente no navegador com 99 páginas, confirmando navegação/renderização neste fluxo específico; não validei salto automático para artigo nem o conteúdo contra fonte oficial.

Na rota `/explorar/`, a instância mostrou **0 normas**, declarou que PDFs pendentes não geram relações jurídicas públicas e ofereceu link para a busca do acervo. O empty state é honesto, mas o produto ainda não entrega grafo útil enquanto não houver normas consolidadas/revisadas. A rota `/conferir/` redirecionou para login com `next=/conferir/`; não usei credenciais nem contornei esse controle. Portanto, conferência autenticada não foi testada em runtime.

Estes testes foram feitos como navegação de usuário na QA local, com PDFs autênticos do acervo arquivado, mas não são autos reais nem validação jurídica. Nenhum dado documental foi gravado. P-011 tem busca de candidatos visivelmente exercitada; P-012 permanece funcional apenas no estado vazio, sem prova de exploração de relações reais; P-014 segue sem runtime autenticado. A aprovação de identidade/extração, análise jurídica da cadeia, condições de uso e estudo com procuradores continuam pendentes.

### Smoke ponta a ponta após corrigir identidade de build — 08/10/2026

O smoke `tests/js/pgm-workflow-smoke.mjs` foi executado pelo runner QA contra o checkout identificável em `http://127.0.0.1:8011`, com `JURIX_QA_ROOT=%TEMP%\jurix-pgm-goal-qa-20261008` e saída em `pgm-smoke-8011-current`. A primeira execução parou antes dos fluxos por expectativa obsoleta de build desconhecida; corrigi o teste para exigir versão/revisão explicitamente válidas sem fixar um hash. Guard focal: **25 passed**; `node --check`: passou. Reexecução completa: **17 checks passaram, 0 falharam**, com relatório e 11 screenshots em `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-smoke-8011-current\`.

O smoke cobriu assistente, pesquisa e normas a 320/360/640/768/1280/1920 px sem overflow ou controles focáveis fora da viewport; busca nos PDFs reais; lista de 6.664 candidatos (40 exibidos, filtragem de um resultado) versus zero consolidados; grafo vazio seguro; metadados da instância; exportação JSON `jurix-evidence-v1` com quatro fontes estruturadas; drawer/modal, Escape, expansão e restauração de foco; PDF citado com HTTP 200 e renderização; consulta real ao PDF LC 198/2021 com Arts. 1º, 2º, 4º e 6º; abstenção temporal em 2020; cadeia LC 258/2024 ↔ LC 55/2004; e gate anônimo da mesa de revisão. O relatório completo preserva respostas/excertos locais e permanece só no diretório QA, não versionado.

Esse resultado melhora a confiança nos contratos técnicos e na jornada guest, mas **não** comprova conformidade WCAG completa, zoom nativo 200%, acessibilidade assistiva, legitimidade/atualidade do corpus, correção jurídica, conteúdo/licença dos PDFs, grafo com relações reais, fluxo autenticado de revisor, autos concretos, gold independente ou estudo com assessores. O grafo sem normas consolidadas passa apenas o critério de não inventar relações. P-011/P-015/P-019/P-021 continuam parciais frente aos gates integrais do plano.

No gate de deployment, `python manage.py check --deploy` executado sob `config.settings_normative_qa` encerrou com **2 erros e 7 avisos**: o profile QA tem `DEBUG=True` e segredo inadequado para produção; também não ativa HSTS/redirect HTTPS/cookies `Secure`. Isso reprova uso do profile QA como deployment, como esperado; não é medição de um ambiente de produção separado. Nenhum valor de segredo foi exibido e nenhuma configuração foi alterada.

A suíte JavaScript completa (`scripts/normative_qa.py --run npm test --prefix tests/js`) foi repetida após a correção do smoke e terminou com **exit 0**, sem subtests falhando. Os smokes que exigem participante/credencial de revisor ou outra URL QA explícita permaneceram skipped conforme os pré-requisitos; isso não conta como validação autenticada ou humana.

### Reflow e alvo de ações da sidebar no checkout atual — 08/10/2026

O runtime manual em `:8011`, `:8028` e `:8030` ainda entregava o cache/template antigo `jurix-sidebar.css?v=20261002-session-actions1`; não usei essas instâncias para validar as alterações novas nem as encerrei. Iniciei uma instância QA separada em `127.0.0.1:8012` pelo runner `scripts/normative_qa.py`, com o profile e banco QA isolados já dedicados. A página `/normas/` identificou 0 normas consolidadas e 6.664 PDFs candidatos; nenhuma escrita documental ocorreu.

Na UI do checkout, os botões “Opções da conversa” mediam **34×34 px**. Corrigi o alvo para **44×44 px**, atualizei o cache-buster compartilhado da sidebar nas duas shells e acrescentei um teste de regressão. Em `:8012`, confirmei o stylesheet `v=20261008-session-actions44` e a geometria computada de 44×44 px. Com viewport CSS de 640×720, o documento mediu 625 px de largura, sem overflow horizontal; o botão de navegação mediu 44×44 px. A navegação por Tab mostrou foco visível com outline de 2 px. Esse viewport estreito é reflow responsivo, **não** zoom nativo a 200%; o atalho de zoom da automação não alterou a escala, portanto o zoom nativo continua não testado. P-021 permanece parcial.

Verificação após a mudança: `node --test tests/js/sidebar.unification.test.mjs` (**7/7 passed**), suíte JavaScript pelo runner QA (**exit 0; nenhum subteste falhou**) e `git diff --check` nos quatro arquivos alterados (**passou**). O `check --deploy` e as lacunas de revisão, autenticação, corpus consolidado, gold e sessões de procuradores descritos acima não mudam.

#### Consulta de usuário final — regra transitória de licenciamento — 08/10/2026

- No Chromium, usei o checkout atual em `http://127.0.0.1:8012/assistente/?new=1&corpus=archive-qa`, preenchi o campo inicial e enviei uma situação **explicitamente hipotética**, sem dados de processo ou de pessoas. A sessão foi criada e a UI mostrou a resposta concluída sem F5.
- O assistente recuperou o Art. 262 da LC 258/2024 de uma extração local e resumiu as condições do trecho: protocolo até a vigência, ausência de despacho decisório e ressalva de manifestação formal pela análise integral segundo a lei nova. Pediu que se confirmassem quatro fatos do processo e não concluiu qual regime rege um caso concreto. A interface avisa que a extração e os metadados do acervo estão em revisão.
- A citação foi associada à norma/dispositivo e a um hyperlink para o PDF local. Abri “Fontes consultadas”: o drawer mostrou uma evidência em uma norma; o link apontou à rota local do PDF com fragmento de texto. A rota foi verificada por GET: **HTTP 200, `application/pdf`, 3.838.098 bytes**. `HEAD` retorna 405; como GET funciona, isso não foi tratado como falha do arquivo.
- Limites: confirma recuperação/renderização e disponibilidade do PDF no runtime QA, mas não revisão independente da extração, autenticidade da publicação, reconstrução histórica, nem teste de um processo real da PGM. Não houve escrita, revisão ou promoção documental. P-019/P-021 continuam parciais e `:8012` é QA, não produção.

#### Regressão de follow-up com dois dispositivos — LC 258/2024 — 08/10/2026

- Fiz uma continuação natural pedindo a relação entre o Art. 262 (transição) e o Art. 266 (vigência). O runtime anterior respondia apenas com o Art. 266 ou se abstinha sem fontes. O diagnóstico somente-leitura, porém, localizou os dois artigos na extração completa (264 artigos), provando que a perda ocorria no caminho de síntese/fallback, e não na recuperação. O registro de cobertura não é prova de que todos os dispositivos estejam juridicamente corretos.
- Reproduzi com um teste de regressão que falhou antes do patch. Causa: a referência única da LC era marcada `ambiguous` pelo parser porque a pergunta continha dois artigos; o fallback multiartigo exigia uma referência não ambígua e passava a tratar a consulta com norma explicitamente nomeada como tema livre. Ajustei a condição para aceitar a identidade da norma quando há exatamente uma referência tipada/ano qualificada e o classificador reteve os artigos no plano de consulta; referências a normas múltiplas continuam sem associação presumida.
- Após reiniciar somente o servidor QA `:8012` que iniciamos, repeti pelo browser: o assistente apresentou transcrições separadas de Arts. 262 e 266 com marcadores `[1]`/`[2]`; cada artigo abre o fragmento correspondente do mesmo PDF. O drawer agrupou 2 evidências sob 1 lei. Após reload, resposta e botão de 2 fontes persistiram.
- Conferência oficial somente-leitura: o PDF de LC 258/2024 disponibilizado pelo SAPL contém o texto do Art. 262 e do Art. 266 e informa publicação em 27/12/2024. A URL oficial é `https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2024/4052/lei_complementar_no_258_2024.pdf`. Não calculei data de vigência nem validei interpretação/aplicação; o PDF QA continua pendente de revisão.
- Verificações: teste focal inicialmente **1 falha** (reprodução); suíte RAG após fix **92 passed**; suíte Python integral **1.626 passed, 6 skipped, 0 failed, 8 warnings**; Ruff, `manage.py check`, orçamento arquitetural, contrato documental e `git diff --check` passaram. Sem promoção/revisão ou alteração do conteúdo jurídico.

#### Follow-up implícito sobre vigência — regressão corrigida — 08/10/2026

- Em uma conversa QA, perguntei primeiro sobre o Art. 262 da LC 258/2024 e depois, sem repetir a lei: “E qual artigo define a data de entrada em vigor?”. Antes da correção, a resposta listava Arts. 262, 50 e 28; o Art. 262 apenas menciona a data como condição transitória, e os outros resultados eram alheios ao que se pediu.
- A causa foi a falta de uma intenção específica para localizar o dispositivo operativo de início da vigência. A consulta herdava a norma, mas era ranqueada por termos genéricos. Acrescentei um filtro fail-closed no RAG: em perguntas que pedem qual artigo define/estabelece/fixa/determina a vigência, só retorna dispositivo que efetivamente contenha cláusula de entrada em vigor; se nenhum for encontrado, não apresenta artigos apenas semelhantes.
- No runtime QA `:8012`, reiniciado a partir do checkout após a mudança, repeti a conversa. A resposta agora diz que a LC 258/2024 entra em vigor 90 dias após a publicação e vincula o Art. 266. O botão indicou 1 fonte; o drawer agrupou 1 evidência sob a LC 258/2024 e mostrou o trecho do Art. 266 e o link ao PDF local. Após F5, conversa, resposta e fonte continuaram visíveis.
- O diagnóstico de recuperação somente-leitura retornou inicialmente Arts. 262/266/98/66/5/51/50/48 e, após a correção, somente `Art. 266`. A regressão `test_contextual_followup_for_effective_date_returns_only_operative_clause` falhou antes do patch e passou depois. O PDF e a extração local continuam pendentes de revisão; isto não é confirmação jurídica nem recomendação para caso real.
- Verificação final deste bloco: suíte Python pelo runner QA PostgreSQL isolado **1.627 passed, 6 skipped, 0 failed, 8 warnings em 261,30 s**; suíte JavaScript via runner QA **exit 0, sem testes falhos**; Ruff, `manage.py check`, orçamento arquitetural (`passed=true`, `findings=[]`), contrato documental e `git diff --check` passaram. O `pytest` direto em SQLite falhou por backend incompatível; não é o comando de validação deste projeto e não foi usado como resultado final.

#### Follow-up “quando passou a vigorar?” — segunda regressão de temporalidade — 08/10/2026

- No mesmo chat QA, perguntei “E quando a lei passou a vigorar?”. Antes deste patch, o sistema chegou a mostrar 12 fontes pendentes durante a geração e finalizou com “não especifica a data de vigência”, atribuindo a resposta ao Art. 75; isso não respondia à pergunta. O teste foi feito com a extração local LC 258/2024, ainda marcada `pending`.
- Ampliei a resolução contextual para reconhecer “quando” e “em que data”, preservando a identidade normativa do turno anterior. A recuperação passa a classificar perguntas por data de vigência separadamente do ranking lexical genérico, exigir uma norma exata e selecionar somente uma cláusula operativa de início da vigência. Pergunta ambígua ou sem cláusula reconhecível não deve receber artigos parecidos; não há cálculo de data no calendário.
- A regressão sintética prova exclusão de Art. 262 (menção incidental) e Art. 50 (licenciamento), retornando apenas Art. 266. O diagnóstico somente-leitura com a extração real retornou `Art. 266`. Após reiniciar o servidor QA `:8012`, o browser repetiu a pergunta e exibiu uma fonte; o drawer identificou Art. 266, mostrou a transcrição e link ao PDF local. Nenhuma promoção/revisão do documento ocorreu.
- Verificação deste incremento: teste de recuperação/continuação em foco passou; suíte Python no PostgreSQL QA isolado **1.628 passed, 6 skipped, 0 failed, 8 warnings em 234,57 s**; Ruff, `manage.py check`, arquitetura, contrato documental e `git diff --check` passaram. A suíte JS anterior segue exit 0; não houve alterações frontend. O texto segue em revisão e não deve ser tratado como data oficial nem fundamento de caso real.

#### Rótulo correto para fontes provisórias durante streaming — 08/10/2026

- O SSE `sources` fornece candidatos recuperados antes de `done`; o evento final substitui a lista pelas fontes selecionadas para a resposta. Embora o badge dissesse “Verificação em andamento”, o botão chamava os candidatos de “fontes consultadas”, o que podia sugerir citação já confirmada.
- Ajustei o estado provisório para “fonte(s) em análise”, inclusive no nome acessível do botão, no título do drawer e no subtítulo, que explica que os candidatos aguardam validação e associação à resposta. Depois de `done`, o mesmo controle/drawer volta a “Fontes consultadas” com a seleção final. As fontes continuam acessíveis durante o streaming.
- A suíte de comportamento do streaming passou **52/52**; o teste real de Chromium para o estado provisório também passou. Ambos verificaram antes/depois de `done`, inclusive com drawer já aberto. Atualizei o cache-buster dos dois scripts; não fiz uma nova pergunta ao modelo neste subitem. Isso melhora a comunicação do estado, mas não substitui revisão jurídica humana nem resolve a incompletude do corpus.

#### P-001/P-019 — paráfrase explícita do pedido de vigência — 08/10/2026

- Pergunta real no browser QA (`:8012`, primeiro turno): “Qual dispositivo da Lei Complementar nº 258/2024 estabelece sua entrada em vigor, e o que diz o trecho do PDF local?”. Antes do patch, a resposta genérica exibiu Arts. 191, 172 e 89, sem relação com a vigência; o drawer terminou em 3 fontes incorretas. Durante o streaming o botão já dizia “12 fontes em análise”, provando também a utilidade da distinção provisório/final.
- Causa: a intenção específica cobria “qual artigo define a data...” e perguntas “quando...”, mas não “qual dispositivo ... estabelece sua entrada em vigor”. A identidade repetida pelo contexto do mesmo normativo também era considerada ambígua pelo parser. Ampliei a frase reconhecida para artigo/dispositivo e tratei menções repetidas como uma identidade única **somente** se todas as referências tipadas e anuais tiverem o mesmo `identity`; múltiplas normas ou referências sem ano não ganham essa exceção.
- Antes da repetição real, o teste de regressão falhou (incluiu Art. 262 além de 266 quando o contexto repetia a LC). Após a correção, `src/tests/test_qa_archive_rag.py` + `src/tests/test_followup_context.py`: **113 passed**; Ruff passou. No browser QA reiniciado, a mesma pergunta retornou apenas **Art. 266**, com a cláusula “entra em vigor 90 dias após a data de sua publicação”, um link ao PDF e uma fonte final. Não calculei a data civil nem afirmei vigência oficial.
- A fonte é extração local real, mas segue `pending`/não revisada; a UI identifica isso e manda conferir o PDF. Não é parecer nem confirmação da situação oficial. As duas conversas de QA foram feitas em sessões públicas temporárias; nenhuma fonte foi promovida ou alterada.
- Gates finais depois da correção: suíte Python integral via PostgreSQL QA isolado **1.628 passed, 6 skipped, 0 failed, 8 warnings em 228,59 s**; `manage.py check` sem issues; `architecture_budget_v2.py` `passed=true`, `findings=[]`; contrato documental passou; `git diff --check` passou, com aviso preexistente de normalização CRLF em `docs/audit/2026-10-02/http-events.jsonl`.
#### Consulta de alteração legislativa — PLC 9/2026 e LC 120/2010 — 08/10/2026

- No app local QA `http://127.0.0.1:8012`, em sessão pública com documentos do acervo real ainda pendentes de revisão, perguntei se o PLC 9/2026 e a Emenda Supressiva 1/2026 alteraram ou revogaram o Art. 18 da LC 120/2010 e pedi separar proposta de lei publicada.
- A resposta citou a redação de origem do Art. 18, advertiu que o lote local não tem cadeia revisada de alterações/revogações e não concluiu que o artigo continua vigente. Acrescentou que a busca não trouxe documentos oficiais de tramitação/resultado da proposta, portanto não permite concluir aprovação, sanção e publicação. Isso descreve o escopo da busca desta consulta; não prova inexistência de atos no SAPL.
- Sem recarregar a página, abri e expandi o drawer. Ele mostrou uma fonte sob “Lei Complementar nº 120/2010”, dispositivo Art. 18, com status explícito de extração/metadados pendentes, excerto e link para PDF local com fragmento de texto. O painel foi utilizável sem F5.
- Cenário público e hipotético, sem dados de processo/pessoa; não houve decisão jurídica nem escrita/promoção no acervo. Os registros SAPL consultados como contexto oficial são [PLC 9/2026](https://sapl.natal.rn.leg.br/materia/54742) e [Emenda Supressiva 1/2026](https://sapl.natal.rn.leg.br/materia/54885). O app ainda não recupera nem associa automaticamente esses registros legislativos: não validado se a emenda foi aprovada ou qual foi o desfecho final do projeto.
- Testes após o ajuste: 131 testes Python focados passaram; Ruff e `git diff --check` passaram. Não é validação com procuradores, revisão jurídica independente nem prova de vigência.
- Complemento por API oficial SAPL (GET, sem persistência): busca exata por espécie/número/ano localizou PLC 9/2026 (ID 54742) e Emenda Supressiva 1/2026 (ID 54885), relacionados como matéria principal/anexada. Os payloads mostram `em_tramitacao=false`; `resultado` e `data_publicacao` vieram vazios/nulos. A ementa da emenda declara que suprime o Art. 3º do PLC para preservar, entre outros, o Art. 18 da LC 120/2010. Isso é metadado de tramitação da Câmara e não basta para afirmar resultado final ou vigência. O app QA não consultou essa API durante a resposta; este dado foi observado separadamente pelo agente. Integração e fonte oficial legível na resposta continuam pendentes.

#### Adapter exato read-only para matérias SAPL — 08/10/2026

- Acrescentei ao cliente SAPL um método que busca matéria por descrição exata do tipo, número e ano, resolvendo o ID no catálogo da própria instalação; segue paginação validada e preserva os campos oficiais de situação/resultado/publicação/relacionamentos sem inferir desfecho. Os testes de todos os módulos SAPL: **96 passed, 4 skipped**; Ruff passou.
- Consulta live do novo cliente, GET somente e sem conectar a banco, localizou os dois IDs (54742 e 54885) do caso público. Isso valida apenas o transporte e os filtros do API. O assistente ainda não chama o adapter e não mostra matérias SAPL como evidências; o comportamento no produto não mudou e permanece por validar.

#### Resposta com matéria oficial SAPL associada — 08/10/2026

- A pergunta pública “PLC 9/2026 e Emenda Supressiva 1/2026” no endpoint SSE de QA `:8013` retornou os dois registros, seus links SAPL e ementas; o `sources` chegou antes dos chunks. A UI de cartões foi coberta por teste JS, mas não inspecionada visualmente: a ferramenta de automação encerrou a sessão sem conseguir identificar a URL da janela.
- O registro informa que ambos estão fora de tramitação, mas não fornece resultado nem data de publicação. O app apresenta esses campos como não informados e avisa que o registro não demonstra aprovação, promulgação, vigência ou validade. A emenda cita a preservação do Art. 18 da LC 120/2010; isso não substitui a linha do tempo oficial nem prova que a redação continua vigente.
- Testes: 125 Python, 53 JavaScript, Ruff e `git diff --check` passaram. A chamada HTTP de runtime foi não autenticada, QA-only, sem gravar sessão/matéria. Nenhuma peça reservada foi usada.

### Navegação por teclado e limite da conferência autenticada — QA `:8281` — 09/10/2026

- Em `/pesquisa/?q=Lei+Complementar+258%2F2024+Art.%2059&corpus=archive-qa`, confirmei como visitante **0 resultados consolidados e 1 PDF candidato**, com status pendente, trecho do Art. 59 e acesso à ficha/PDF. A interface não apresentou esse candidato como texto vigente.
- Com Tab, o primeiro foco foi o link “Pular para o conteúdo principal”; o foco do botão de pesquisa na sidebar teve outline visível. Acionei o link e confirmei a URL com `#main-content` e foco transferido à área principal. Isso verifica o caminho de salto nessa rota, não uma auditoria completa de ordem de foco/leitor de tela.
- Acessar `/conferir/` redirecionou para `/conta/entrar/?next=/conferir/`. Não usei credenciais nem tentei contornar o gate; formulário, submissão, resultados, autorização por objeto e experiência autenticada permanecem **não testados em runtime**.
- Tentei usar atalhos de teclado do navegador embutido para 200% (`Ctrl+0`, `Ctrl++`/numpad e `Ctrl+Shift+=`), mas a escala visual não mudou. Portanto, zoom nativo 200% permanece **não verificado**; os testes de 320–1920 px são apenas responsividade/reflow e não substituem zoom. Não registrei screenshot versionado dessa inspeção.
- Evidência visual: captura observada na sessão browser do Codex; inventário AX mostrou os focos e conteúdo acima. Nenhum dado ou documento foi alterado; consulta somente de navegação no QA.

### Regressão integrada de navegador — QA — 09/10/2026

- A suíte de navegador `real.browser.test.mjs` passou **41/41** após alinhar o teste de teclado do drawer ao contrato real: desktop (`>=1200px`) é painel não modal; a verificação de wrap de Tab/Shift+Tab deve ocorrer em largura modal (`1024px`). A paginação do histórico passou isoladamente e no arquivo completo; não houve alteração do comportamento do histórico.
- O teste de assets também foi sincronizado com a versão efetivamente servida `jurix-rag.js?v=20261009-sapl-matter-source-label2`; a asserção continua exigindo correspondência exata e não foi enfraquecida.
- Suítes integradas: Python **1.706 passed, 6 skipped, 0 failed**; JS **248 passed, 5 skipped, 0 failed**; `manage.py check` sem issues; orçamento arquitetural `passed=true` sem findings; contrato documental aprovado. O smoke QA do fluxo PGM permaneceu em 17/17 checks.
- Limites não mudam: zoom nativo 200% não medido pelo browser embutido, `/conferir/` sem conta QA autenticada, nenhum participante PGM, nenhum gold jurídico independente e nenhum PDF pendente foi promovido ou tratado como vigente.

### Uso como procurador — conferir proposta de alteração do Art. 59 — QA `:8281` — 09/10/2026

- Usei o assistente em consulta pública de triagem sobre a redação do Art. 59 da LC 258/2024 e a situação da PLC 12/2025. A resposta distinguiu o PDF local pendente de revisão do registro oficial de matéria no SAPL, mostrou “Em tramitação” e avisou que os metadados não demonstram aprovação, promulgação ou vigência.
- Sem F5, abri “Fontes Consultadas” e expandi as evidências. O cartão da LC 258/2024 identificou Art. 59 e abriu o PDF do acervo no trecho; o cartão da PLC abriu a ficha SAPL `/materia/48759`. A proveniência e a ressalva de revisão estavam visíveis nos próprios cartões.
- Avaliação de uso: bom fluxo de conferência inicial para detectar uma proposição que pode afetar o dispositivo e evitar tratar uma proposta como lei promulgada. Ainda não serve para concluir a redação vigente: o PDF do acervo não foi revisado e o aplicativo não mostrou ato final de aprovação/publicação. O teste foi baseado em legislação pública, não em autos nem em validação por procurador; a resposta veio pelo caminho determinístico e não foi um teste de qualidade/latência do Ollama.
- Falha na pergunta de seguimento: logo depois perguntei “Qual é a redação nova proposta para o art. 59?”. O assistente não herdou a PLC 12/2025 identificada no turno anterior e respondeu que os trechos recuperados não sustentavam o tema. A resposta não inventou conteúdo, mas obriga o usuário a repetir o número da matéria e não explica a lacuna específica (a evidência disponível traz a ementa, não necessariamente o texto proposto). Continuidade de contexto e recuperação do texto integral da proposição precisam ser corrigidas/testadas antes de piloto de uso real.

#### Reteste após correção contextual — 09/10/2026

- A primeira repetição ainda usou o processo antigo `runserver --noreload` e reproduziu uma resposta inválida que confundia o PDF da LC com o texto da proposta. Descartei esse resultado como não representativo da working tree; reiniciei o servidor QA sob meu controle.
- Em conversa nova no servidor atualizado, a pergunta completa trouxe o PDF local e a ficha SAPL da PLC, sem atribuir o trecho do PDF à proposição. A resposta explicou que a consulta SAPL disponível tinha ementa e metadados, não a íntegra do projeto.
- Em seguida, perguntei “E qual é a redação nova proposta?”. O sistema herdou a PLC 12/2025, citou apenas sua ficha SAPL e absteve-se corretamente de afirmar a redação do dispositivo. O drawer distinguiu uma matéria legislativa oficial e não apresentou fontes do acervo local como texto do projeto.
- O seguimento agora preserva o contexto e evita a confusão observada; continua faltando recuperar/exibir eventuais anexos integrais da proposição. Não é aprovação para uso em autos: PDF local segue pendente de revisão, sem validação por procurador e sem avaliação de resposta jurídica independente.

#### Reteste com anexo “Texto Original” SAPL — 09/10/2026

- Perguntei pelo chat “Qual é a redação proposta para o art. 59 no PLC 12/2025? Traga somente o texto do dispositivo alterado, sem assinaturas ou rodapé.” A aplicação consultou cadastro e anexo oficial no SAPL, extraiu o Art. 59 proposto e respondeu sem incluir o Art. 2º, assinatura ou rodapé.
- A resposta exibiu status “Em tramitação no SAPL” e aviso explícito de que a redação é proposta, não norma promulgada nem prova de vigência. Drawer mostrou dois cartões sob a mesma PLC: cadastro da matéria e PDF oficial do texto original. O href do cartão aponta para o anexo SAPL com fragmento de texto do Art. 59 e não exibe mais “Baixa correspondência 0%”; não confirmei a nova aba após clicar no link.
- Em seguida perguntei “E qual é a redação proposta?” sem repetir o número: o contexto recuperou a PLC 12/2025, apresentou novamente o Art. 59 do anexo e atualizou o estado final de fontes sem F5.
- Problema encontrado/corrigido durante o teste: a primeira extração levava junto artigos posteriores e boilerplate do PDF. O parser agora encerra no próximo artigo em caixa alta, mantendo referências internas como “art. 51”; um teste unitário reproduz a estrutura observada no documento. Também foi acrescentado rótulo semântico para a fonte oficial de proposta, que não tem escore de similaridade.
- Testei a ação “Copiar resposta”; a UI confirmou sucesso, mas não li a área de transferência, portanto a equivalência Markdown/citação/URL continua não verificada.
- A tela foi usada em `http://127.0.0.1:8281`, sem F5 durante envio ou abertura das fontes. Após recarga deliberada para atualizar recurso estático, a conversa e os cartões foram restaurados. Nenhum dado de processo real foi inserido.
- Testes: Python focado 42/42; JavaScript focado 109/109; suíte JS do projeto 248 pass, 5 skip, 0 fail; Ruff, `manage.py check` QA, orçamento arquitetural e `git diff --check` passaram. Ainda sem revisão por procurador, confirmação independente do status legislativo ou autorização para tratar o texto como vigente.

#### Revalidação do anexo oficial e de seu ponto de abertura — 09/10/2026

- Evidência positiva isolada: o serviço de domínio e o endpoint SSE Django em QA recuperam a ficha SAPL e o PDF original da PLC 12/2025, extraem somente a redação proposta do Art. 59 e identificam a página 3. O PDF contém 3 páginas; o visualizador Chromium mostrou a página 3/3 com o texto alvo após navegação por página.
- Regressão de produto observada: o navegador `:8280` continuou mostrando uma fonte (cadastro SAPL) e omitindo o anexo/texto proposto em duas sessões limpas; o resultado persistiu após reload. Logo, não confundir os testes de função/API com aceite ponta a ponta. Fontes e texto precisam ser reconciliados no fluxo real da UI.
- Não usar a falha de UI como prova de que o anexo não existe: o GET público do registro SAPL 48759 e do PDF respondeu, e a chamada SSE direta carregou a evidência. Próximo passo de depuração: comparar o evento SSE real visto pelo navegador com o endpoint direto, validando `sources` inicial, chunks, `done.sources`, os marcadores `[[1]]/[[2]]` e a persistência local anônima.
- Testes desta rodada: 151 Python focados e 58 JavaScript passaram; `manage.py check` QA sem issues. Navegador sem erros console. `#page=3` foi verificado no visualizador previamente aberto; a ligação da URL gerada pelo app ao cartão ainda aguarda a fonte aparecer na UI.

#### Reteste ponta a ponta com build atual — QA `:8040` — 09/10/2026

- A observação de falha em `:8280` acima foi supersedida: aquela porta estava servindo uma instância antiga, com assets e template anteriores ao checkout atual. Não é correto atribuir a discrepância ao cliente SSE atual.
- Em `:8040`, confirmei os identificadores atuais dos arquivos JS no HTML servido, usei uma conversa limpa e perguntei “Qual é a redação proposta no art. 59 do PLC 12/2025?”. A resposta exibiu a redação do anexo, marcou a matéria como “Em tramitação” e esclareceu que proposta não é norma promulgada.
- O painel “Fontes Consultadas” abriu sem F5 e exibiu dois cartões agrupados sob a PLC 12/2025: registro da matéria e PDF oficial original. O PDF foi rotulado como proposta, sem escore semântico enganoso. O link abriu a URL do anexo com `#page=3`; a inspeção visual confirmou página **3/3** e o Art. 59 na página aberta.
- Isso aprova apenas este fluxo de triagem pública e a navegação até a página do anexo. Não prova situação legislativa final, validade/vigência, completude do acervo nem adequação para concluir parecer; não foram usados autos ou dados confidenciais, nem houve revisão por procurador.

#### Consulta de artigo do PDF local e divergência entre documentos — QA `:8040` — 09/10/2026

- Em conversa separada, consultei o Art. 59 da LC 258/2024 pelo assistente. A resposta ligou a afirmação ao PDF local, abriu “Fontes Consultadas” sem recarregar a página e apresentou o cartão com o excerto, o rótulo de transcrição pendente e o botão “Abrir PDF do acervo”.
- Comparei apenas os dois documentos públicos já abertos: o PDF local arquivado contém referência ao art. 54; o texto do anexo oficial da PLC 12/2025 contém a redação proposta do Art. 59 com referência ao art. 51. Isso pode refletir alteração entre versões, mas o teste não localizou nem adjudicou o ato final/publicação. A resposta é útil para localizar a divergência, não para declarar qual texto rege um caso.
- Verifiquei `/api/tags` e uma geração curta direta no Ollama local (`llama3:latest`): concluída em 2,42 s. A interface não expõe evidência de qual provider serviu a consulta do app; o código usa Ollama como padrão, mas não contei a chamada direta como prova de uso do modelo na resposta E2E.
- Sem análise de autos, sem promoção/consolidação de documentos e sem alteração de dados reais. Próximo passo para o fluxo PGM: identificar por fonte oficial o eventual ato promulgado que resultou da PLC, comparar datas e redações antes de qualquer conclusão temporal.
- Na página oficial de tramitação da PLC 12/2025, verifiquei 16 eventos; o mais recente exibido é de **08/10/2026**, com destino à Comissão de Finanças e status “Aguardando análise do parecer”. A página básica marca “Em Tramitação? Sim” e não informa data de publicação. Isso dá ao assessor uma pista operacional concreta de que o texto recuperado é proposta pendente, embora a atualização futura do status exija nova consulta ao SAPL: [registro oficial de tramitação](https://sapl.natal.rn.leg.br/materia/48759/tramitacao).
- **Problema de produto de alto impacto:** ao perguntar diretamente sobre LC 258/2024, o painel devolveu só o candidato local e não mostrou a PLC pendente que declara alterar o mesmo artigo. Como usuário, eu teria que conhecer a matéria e procurá-la à parte; isso não atende ao uso pretendido de evitar fundamentação baseada em dispositivo possivelmente alterado. A evidência é a diferença entre a resposta/painel da conversa QA e o registro oficial da PLC 12/2025; não implica que a proposta já tenha força normativa.

#### Correção do seguimento contextual e novo teste de uso — QA `:8040` — 09/10/2026

- Reproduzi a pergunta natural “E existe alguma proposta posterior para alterar esse dispositivo?” após consultar o Art. 59. Antes da correção, o produto não herdava a referência e respondia insuficiência de evidência. Atualizei o resolvedor para acrescentar LC 258/2024 e Art. 59 somente quando o contexto anterior é inequívoco.
- No reteste do app, sem abrir nova conversa, o assistente consultou o SAPL e mostrou a PLC 12/2025 como matéria em tramitação, com a última atualização do cadastro em 08/10/2026 às 13:08. O drawer agrupou a matéria, distinguiu “Registro de matéria legislativa” de norma vigente e abriu a ficha oficial. A resposta não inferiu aprovação/promulgação; resultado e data de publicação ficaram como não informados.
- Testes: 51 focados antes, 54 depois; `manage.py check` QA e Ruff passaram. O servidor reiniciado foi apenas o QA `:8040`; a interface permaneceu aberta para revisão.
- Avaliação do fluxo: o seguimento agora serve à triagem de alteração pendente. Continua existindo fricção importante: a consulta inicial do texto do artigo não oferece a PLC relacionada automaticamente; o procurador precisa fazer uma segunda pergunta. Também faltam o ato final/publicação e adjudicação humana para fechar a redação aplicável. Não tratei esse fluxo como apto a decidir caso concreto.

#### Consulta simples agora alerta para proposta relacionada — QA `:8040` — 09/10/2026

- Como usuário, abri conversa nova e perguntei apenas “O que prevê o Art. 59 da Lei Complementar nº 258/2024?”. Sem solicitar pesquisa de alterações, recebi o excerto local e a PLC 12/2025, cuja ementa associa a proposta ao Art. 59. A fonte local continua marcada pendente de revisão e a PLC como matéria em tramitação; a resposta avisa que cadastro/ementa não prova aprovação, promulgação ou vigência.
- Abri “Fontes Consultadas” durante a conversa, expandi todas as evidências e confirmei dois grupos: LC 258/2024 com link para o PDF local no trecho, e PLC 12/2025 com link para o registro oficial SAPL. Não precisei dar F5. Isso melhora a descoberta de possível alteração, mas não determina a redação aplicável nem substitui a inspeção da tramitação e do ato publicado.
- Fricção visível: a resposta mostra mais de um link para a mesma fonte local (referência textual ao artigo e marcador de citação), deixando a leitura poluída. O drawer oferece a fonte correta, mas a resposta deve futuramente evitar essa duplicação sem perder a citação estruturada ou o link copiável.
- Verificação associada: 186 testes Python passaram (6 subtestes), `manage.py check` QA e Ruff passaram. Pergunta roteada pelo caminho determinístico; não conta como teste de qualidade ou streaming do Ollama. Sem autos, dados confidenciais, promoção documental ou alteração de corpus.

#### Revalidação manual de acessibilidade e fluxo de fontes — QA `:8283` — 10/10/2026

- No navegador embutido, em viewport de 1285 × 884 CSS px, Tab alcançou o link de pular para o conteúdo com outline visível de 2 px (`rgb(147, 197, 253)`, caixa 146 × 38 px). Enter moveu o foco para `#messages-container` e atualizou o fragmento da URL.
- Ctrl+K abriu a paleta com controles e rótulos acessíveis; não observei SVG bruto como texto. Escape fechou a paleta. Na conversa, Escape também fechou Fontes Consultadas e devolveu o foco ao botão que abriu o painel.
- Enviei uma pergunta pública sobre proposta no SAPL que afetaria o Art. 59 da LC 258/2024. A resposta exibiu a redação do PDF local e a PLC 12/2025 como matéria em tramitação, sem afirmar aprovação, promulgação ou vigência. As fontes apareceram sem F5; o drawer agrupou LC e PLC, e “Expandir todas as evidências” mudou para “Recolher todas as evidências”. O cartão local indicou extração pendente; o SAPL abriu a ficha da matéria 48759.
- Zoom nativo de 200% **não testado**: os atalhos Ctrl++/Ctrl+= do navegador embutido não alteraram `devicePixelRatio`, `visualViewport.scale` nem a largura CSS. Isso não é evidência de que o layout passe ou falhe em zoom de 200%; requer navegador que permita controlar zoom real.
- Não usei autos ou dados confidenciais. A consulta foi executada em QA isolado e não adjudica o status jurídico final da proposta nem a redação vigente da LC.

#### Jornada ampla do assessor após estabilização do smoke — QA `:8283` — 10/10/2026

- `tests/js/pgm-workflow-smoke.mjs`: **20/20 verificações passaram**. Cobriu assistente e pesquisa em 320/360/640/768/1280/1920 px; busca sem acento no acervo; `/normas/` (6.664 PDFs candidatos, até 40 exibidos, todos identificados como pendentes; 0 consolidados); abertura do PDF citado; exportação estruturada; drawer modal, foco/Shift+Tab, Escape e expansão de grupos; remissões LC 198/2021 → LC 55/2004; lacuna temporal de 2020; regra transitória/revogação da LC 258/2024; proposta SAPL 12/2025 e acesso anônimo à conferência.
- A primeira repetição falhou no clique imediatamente após o reflow; estabilizei a geometria do botão no teste. A segunda chegou à expansão durante a transição de 300 ms do drawer; o teste agora aguarda o painel alcançar a posição final. Na terceira repetição, as 20 verificações passaram. Nenhuma alteração de produto foi necessária para esses dois problemas de sincronização do teste.
- Evidências e relatório JSON estão apenas no QA temporário: `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-workflow-smoke-20261010-transition-stable\`. Smoke focado SAPL também passou novamente com 2 fontes, ressalva jurídica e 0 erros de página.
- O smoke verifica comportamento técnico e dados públicos/arquivo pendente, não validade jurídica, completude do acervo, vigência atual, desempenho do Ollama em carga, uso autenticado institucional nem adequação para decidir processo. Nenhum autos ou dado confidencial foi usado.

#### Smoke de geração Ollama e overview de norma inteira — QA `:8283` — 10/10/2026

- `normative-rag-live-smoke.mjs` passou no build QA atual usando Ollama local real e acervo PDF com revisão humana pendente. O teste mediu uma pergunta sobre Arts. 17/18 da LC 120/2010: 2 tentativas de geração, 1.625 ms no backend, 7 eventos `chunk`, citações Markdown válidas, links dos artigos apontando para páginas dos PDFs, fontes antes de F5, follow-up para Art. 19 e restauração da conversa/fontes após reload; 0 erros de browser. A lista de documentos e rotas PDF passou 40/40 (2.158.094 bytes verificados no total; sem armazenar o texto da resposta no relatório).
- O controle de streaming mostra fontes por volta de 154 ms; primeiro texto visível em 1.837 ms e UI concluída em 1.971 ms (antecedência visível de apenas 134 ms). Há múltiplos chunks SSE, mas esta medição sugere que a resposta pode parecer quase colada de uma vez; precisa de avaliação perceptiva e instrumentação por intervalo de chunks, sem relaxar grounding.
- Pergunta geral sobre uma norma: recuperação de 30/39 artigos extraídos, 6 excertos usados, cobertura explicitamente parcial, anexos omitidos informados, 6 citações resolvidas; sem heading artificial. O smoke também exercitou cancelamento/retry e relações/temporalidade sintéticas, que não contam como evidência jurídica real.
- A primeira execução após tornar a omissão de anexos uma asserção falhou porque o teste não reconhecia a forma linguística “nessa seleção”; o screenshot da execução anterior já mostrava a divulgação. Atualizei apenas o reconhecimento de variantes “nesta/nessa” e a repetição passou com `statesAnnexOmission=true`. A correção foi do teste, sem mudança do texto do app.
- Relatório sanitizado: `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-live-rag-smoke-20261010-final\live-rag-browser-smoke.json`. Isso não equivale a benchmark em carga, gold jurídico, autenticação PGM ou adjudicação dos PDFs.

#### Reteste de ponta a ponta e drawer na transição para modal — QA `:8040` — 09/10/2026

- Depois de permitir explicitamente `:8040` no runner/smoke restrito a QA e declarar a revisão-base `0d9157aefeb1` junto ao rótulo de checkout dirty, executei o smoke de navegador completo. Resultado: **17/17 checks**, sem erros de página; inclui o drawer a 1024px, Tab reverso preso ao modal, cartões de evidência, ações de 44px e PDF local.
- Duas execuções iniciais falharam enquanto a animação de entrada ainda deslocava o painel. O diagnóstico final mostrou que, depois da transição, a geometria atendia ao viewport; atualizei o teste para aguardar a posição final antes de medir e mantive a exigência de que o painel esteja integralmente visível. Não foi necessária alteração no CSS do produto.
- Evidências reprodutíveis (somente QA): relatório JSON e capturas em `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-smoke-current-20261009\`. O smoke não usa autos, não promove documentos e não testa um usuário institucional autenticado. A fonte LC 258/2024 continua pendente de revisão; a proposta SAPL não foi tratada como direito vigente.

#### P-001/P-019 — streaming incremental de comparação de artigos — QA `:8284` — 10/10/2026

- Em `src/processing/qa_archive_rag.py`, a inspeção encontrou um buffer que esperava todos os artigos pedidos antes de liberar texto. Agora a primeira afirmação validada e citada de um artigo solicitado pode aparecer durante a geração; as demais continuam sujeitas à validação normal. Se faltar cobertura ao fim, o prefixo já visível é preservado e a resposta final explica os artigos recuperados mas não sintetizados, com citação, ou os sem evidência suficiente. Consultas por facetas continuam integralmente bufferizadas.
- Regressão: `src/tests/test_qa_archive_rag.py` (**143 passed**) e `src/tests/test_rag_answer_pipeline_streaming.py` + `src/tests/test_normative_qa_guard.py` (**37 passed**); Ruff passou nos quatro arquivos Python verificados e `git diff --check` passou.
- O primeiro live smoke parou por `ReferenceError` porque `hasTextFragment` não existia no contexto do browser. Corrigi somente a asserção para ler `URL.hash`, sem retirar o critério. Reteste `:8284` com Ollama/Puppeteer: eventos `sources → chunk → done`; 4 chunks; fontes 176 ms; texto 1.456 ms; UI concluída 2.524 ms (**1.068 ms de streaming visível**); geração backend 2.281 ms; Arts. 17/18 citados e links nos PDFs; 0 erros de browser. Reload, follow-up Art. 19, cópia Markdown, cancelar/retry, drawer e PDFs 40/40 passaram.
- Overview geral permaneceu explicitamente parcial: 30/39 artigos detectados, amostra de 6 e anexos fora da seleção informados. Relatório sanitizado: `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-live-rag-stream-gate-20261010-r3\live-rag-browser-smoke.json` (não guarda o texto da resposta).
- Uma execução não é benchmark sob carga nem SLO. Sem revisão jurídica independente ou promoção de PDF; leitor de tela, zoom real 200% e autenticação institucional não testados nesta rodada.
- Verificação final do checkout pelo runner QA: suíte Python completa **1.745 passed, 6 skipped, 0 failed** em 285,08 s; `manage.py check` sem issues; suíte `npm test --prefix tests/js` exit 0, incluindo browser real **41/41**. O primeiro pytest integral com settings padrão teve 14 falhas de guard/configuração QA; os módulos afetados passaram 55/55 no runner isolado, e a suíte integral correta passou.

#### P-003/P-007/P-011/P-019/P-021 — revalidação PGM com extração completa e build identificada — QA `:8284` — 10/10/2026

- Auditoria somente-leitura do PostgreSQL QA: **6.664 documentos candidatos únicos**, todos com extração técnica; status da versão mais recente: **6.566 completas, 97 parciais, 1 ilegível**. Quarenta documentos têm duas versões imutáveis, explicando 6.704 registros; **zero extrações aceitas/revisadas**. Estado “completa” não certifica o conteúdo.
- Diagnóstico da pergunta de triagem sobre LC 258/2024: documento `pending`, sem aceite; extração de 184.127 caracteres, 264 artigos, 857 elementos legais e 99 entradas de mapa de página. Recuperação para os tópicos identificou Art. 2º (objeto/princípios), Arts. 22–25 (protocolo/notificação/complementações) e Art. 262 (processos antigos sem despacho); seis trechos ranqueados foram 22, 24, 262, 23, 2º e 25. É evidência do parser/RAG, não cotejo do texto com o original.
- Reiniciei apenas o servidor QA iniciado nesta rodada com `JURIX_BUILD_VERSION=qa-dirty-20261010`, hash-base do HEAD e profile QA; o nome deixa claro que o checkout tem alterações locais. O smoke completo em Chromium passou **20/20**, 0 erros: Assistente/Pesquisa/Normas/grafo, ficha e PDF, exportação, drawer/foco, remissões, temporalidade, cadeia LC 258/2024 + LC 55/2004, proposta SAPL e gate anônimo. Breakpoints 320/360/640/768/1280/1920 sem overflow; `/normas/` mostrou 6.664 candidatos, 40 por página e zero consolidadas.
- Na consulta de transição, a resposta separou Art. 260 (texto extraído sobre revogação), Art. 262 (regra de transição) e Art. 21 da LC 55/2004, pedindo conferir protocolo, despacho, opção formal, vigência e histórico antes de aplicar ao caso. A PLC 12/2025 e seu “Texto Original” foram tratados como proposição, não lei vigente. O PDF abriu renderizado no Chrome.
- Relatório: `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-workflow-smoke-20261010-current-identified\pgm-workflow-smoke.json`. A primeira execução foi corretamente recusada pelo gate de build sem identidade; a repetição identificada passou. Nenhum documento, extração, revisão, vínculo, checkpoint ou migration foi gravado.
- Avaliação: produto atual serve para triagem rastreável de candidatos, não para certificar direito aplicável. Sem revisão humana, atualização SAPL/DOM e cadeia publicada adjudicada, o procurador precisa conferir os PDFs/fontes. P-006/P-010/P-017/P-018/P-020/P-021 seguem parciais por revisão, operação de fontes ou participação humana.

#### P-007/P-011/P-019 — teste de artigo em PDF do acervo e fecho editorial — QA `:8284` — 10/10/2026

- Perguntei, como usuário, “O que dispõe o Art. 2º da Lei nº 6.859/2018?” no modo do acervo histórico. O assistente citou o texto do PDF, vinculou a afirmação ao Art. 2º e avisou que a transcrição/metadados seguem pendentes; não afirmou vigência atual. O drawer mostrou a evidência agrupada sob a lei e o link abriu o PDF local em nova aba, página 1. Não foi necessário F5.
- O cotejo técnico do PDF real da Lei 6.859/2018 (1 página, extração nativa) confirmou que a redação do Art. 2º termina antes do fecho “Palácio Felipe Camarão, em Natal/RN, 18 de Outubro de 2018”; a data de assinatura não foi convertida em data de publicação. O parser não reconhecia essa variante `/RN` antes da alteração desta rodada.
- Corrigi a expressão do colofão para admitir `Natal/RN` e acrescentei regressão que verifica a fronteira do último artigo e impede inventar data de publicação. Testes QA relacionados: **94 passed** (`test_legal_parser`, `test_document_metadata`, `test_document_extraction`, `test_document_editions`, `test_segmentation_revision`); `manage.py check` sem issues; parser verificado novamente contra o PDF real.
- Limites: este teste não revisa nem promove o PDF e não comprova publicação, vigência atual ou aplicabilidade a processo. O teste E2E observou a resposta final, não mediu a latência do primeiro token nesta pergunta. Não usei dados de autos nem alterei revisão/consolidação.
- Repeti `tests/js/pgm-workflow-smoke.mjs` após reiniciar o QA com a correção: **20/20 checks**, zero overflow nos breakpoints de 320–1920 px, busca do acervo, PDF/ficha, exportação, drawer, relações normativas e gate anônimo aprovados. Relatório e screenshots sanitizados: `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-workflow-smoke-20261010-post-colophon\pgm-workflow-smoke.json`.

#### Seguimento “essa lei” após consulta real do PDF — QA `:8284` — 10/10/2026

- Reproduzi em conversa nova, pela interface, o fluxo “O que dispõe o Art. 2º da Lei nº 6.859/2018?” seguido de “E essa lei teve alterações posteriores?”. Na reprodução inicial, o seguimento perdeu a referência e começou a responder sobre a Lei nº 7.121/2021, despejando conteúdo do PPA sem relação com a pergunta. Interrompi a geração; a interface marcou a tentativa como cancelada/não validada, sem apresentá-la como resposta concluída.
- Corrigi o resolvedor de seguimentos em `src/apps/legislation/api_search.py` para reconhecer “essa/esta/a mesma lei ou norma” e herdar apenas a identidade normativa inequívoca da conversa. Ampliei `src/processing/sapl_matter_lookup.py` para buscar, em consultas sobre norma inteira, ementas que mencionem exatamente tipo, número e ano (sem inventar artigo); a resposta deixa explícito que ementa não é inventário exaustivo nem prova de efeito modificador. A ressalva de resultado vazio agora distingue consulta por identidade da norma de consulta por artigo em `src/processing/qa_archive_rag.py`. Regressões adicionadas em `src/tests/test_followup_context.py`, `src/tests/test_sapl_matter_lookup.py` e `src/tests/test_qa_archive_rag.py`.
- Testes após a ampliação: `test_sapl_matter_lookup.py`, `test_qa_archive_rag.py`, `test_followup_context.py` e `test_api_security.py`: **214 passed**; Ruff nos seis arquivos alterados: passou; `manage.py check` em QA: sem issues. Uma primeira execução encontrou e corrigiu a pontuação de milhar em ementa (`6.859` versus identidade `6859`), sem afrouxar o match de ano/tipo.
- Gate amplo posterior: suíte Python em `config.settings_normative_qa`: **1.749 passed, 6 skipped, 0 failed**; `npm test --prefix tests/js` pelo runner QA: **254 passed, 5 skipped, 0 failed**, exit 0; Ruff e `manage.py check` passaram. O teste de navegador que exige `JURIX_QA_BASE_URL` ficou entre os skips do pacote genérico; a jornada equivalente foi exercitada separadamente no navegador/smoke QA 20/20.
- Repeti o fluxo com Ollama e o PDF real no QA isolado. A consulta inicial respondeu sobre o Art. 2º da Lei 6.859/2018 e abriu a fonte PDF local. No seguimento, não apareceu mais a Lei 7.121/2021 nem texto estranho; a pesquisa SAPL por ementa e identidade da norma terminou sem matéria com menção explícita. A interface informou que o histórico oficial/cadeia permanece inconclusivo e que a busca não prova inexistência de alteração.
- O smoke PGM completo no build identificado `qa-dirty-20261010-law-sapl` passou **20/20**, incluindo breakpoints 320–1920 px, candidatos do arquivo real, abertura do PDF, temporalidade, cadeia LC 258/2024, pesquisa de proposta SAPL e gate anônimo. Evidência sanitizada: `%TEMP%\jurix-pgm-goal-qa-20261008\pgm-workflow-smoke-20261010-law-sapl-final\pgm-workflow-smoke.json`.
- Limite restante: a busca SAPL por ementa é deliberadamente limitada e pode não achar ato que não cite expressamente a lei; resultado vazio não confirma ausência de alteração. A interface agora relata esse escopo corretamente, mas a cadeia normativa precisa de fontes oficiais adjudicadas e cobertura do Diário Oficial para ser conclusiva.
- Ambiente: servidor reiniciado apenas no `:8284`, com banco/Redis do runner QA; conversas de teste ficaram somente nesse banco isolado. Nenhum PDF foi aceito, promovido ou consolidado; nenhuma migration, dado real de produção, autos ou informação confidencial foi alterado/usado.

#### Revisão visual do fluxo de atualidade e proveniência — QA `:8030` — 11/10/2026

- Inspecionei manualmente a captura Chromium produzida pelo smoke via runner, além das métricas DOM. Neste estado, o aviso de extração pendente e o alerta de sincronização de fontes continuam visíveis; as referências legais aparecem sublinhadas, o controle “2 fontes consultadas” e as ações de copiar/exportar estão junto à resposta. Na posição de rolagem final, o início da resposta fica acima da viewport, mas o final, as fontes e o composer permanecem separados; a verificação geométrica não detectou sobreposição nas cinco larguras testadas.
- A captura mostra também o campo temporal “Redação normativa em” vazio e a explicação de que, sem data, a busca usa a redação atual. Mantive-o exposto: é contexto material para triagem temporal da PGM, e escondê-lo reduziria a descoberta do recurso. Esta decisão foi observada apenas em desktop; não é teste de preferência de usuários.
- Evidência temporária: `%TEMP%\\jurix-pgm-goal-qa-20261008\\currentness-f5-runner-20261011\\pgm-article-currentness.png`. É uma revisão visual de uma tela/resposta QA, não auditoria WCAG, leitor de tela, zoom nativo 200% nem validação jurídica.

### Pesquisa do PDF real e limite da conferência autenticada — QA `:8286` — 12/10/2026

- Pela UI, pesquisei `258/2024` com documentos pendentes incluídos. O resultado distingue zero normas consolidadas de um PDF candidato, deixa explícito “sem trecho textual coincidente” e mantém a indicação de revisão pendente. A ficha aberta pelo card mostra identidade candidata, hash, 99 páginas e contagens técnicas de extração (81 texto nativo, 18 OCR, nenhuma página sem texto), mas avisa que não há índice jurídico confiável de artigos e que OCR não é transcrição certificada. O acesso ao PDF foi testado antes nesta sessão no endpoint, mas a renderização visual do PDF no browser in-app continua sem confirmação.
- A rota `/conferir/` redireciona visitantes sem sessão para `/conta/entrar/`. Não usei credenciais nem tentei contornar o gate; o workflow autenticado segue fora do runtime validado. Essa proteção é esperada, mas sem usuário revisor autorizado não consigo completar a tarefa de conferência de fundamentação como procurador.
- O QA SAPL recusou replay do cursor autorizado antes de qualquer escrita porque não havia âncora local correspondente aos registros atualmente retornados pela página oficial. A pesquisa read-only de health reportou estado `degraded`, `last_success_at=null`, um escopo parcial e worker da fila responsivo. Não interpretei isso como atualização concluída.

### Diagnóstico de spans repetidos no Diário Oficial — QA read-only — 12/10/2026

- Reexecutei a inspeção da edição especial nº 6208/2026 sem persistência. O detector encontrou oito cabeçalhos de edital com a mesma assinatura textual, cada um repetido oito vezes nas páginas de origem; os spans propostos variam de 2 a 22 páginas. Isso é um alerta técnico de segmentação, não identificação de oito atos. A mudança preserva todas as ocorrências e apenas acrescenta o contador de repetição para revisão; nenhum PDF foi salvo nem candidato foi cadastrado.
- Regressão dos parsers/cliente/sync: **43 passed**; Ruff passou. A análise não autoriza consolidar esta edição; o passo de revisão de atos reais continua pendente.

### Repetição de consulta sobre atualidade do Art. 18 da LC 120/2010 — QA :8286 — 12/10/2026

- Na primeira tentativa real, a resposta encontrava uma Emenda Supressiva no SAPL, mas o drawer não mostrava o PDF da LC 120/2010 apesar de o diagnóstico direto encontrar o Art. 18. Repeti em conversa limpa e reproduzi o defeito; causa localizada: associação sintática reconhecia `Art. 18 da Lei X`, mas não `Lei X, Art. 18`.
- Após a correção e reinício isolado do container QA para carregar o módulo atualizado, repeti exatamente a pergunta. A interface mostrou o trecho do Art. 18 e abriu duas fontes no painel: PDF local (página 5) e emenda SAPL relacionada. A resposta não alegou que o artigo estava vigente nem que foi alterado/revogado.
- Julgamento como usuário da PGM: a cobertura de fontes agora é melhor, mas a tarefa substantiva “comparar redação original e atual” continua sem solução neste acervo porque há apenas um PDF pendente e nenhuma versão consolidada/histórico verificado. A UI deveria deixar essa limitação mais diretamente ligada ao pedido de comparação; não use esta resposta como confirmação jurídica de atualidade.
- Sessões e mensagens dessa repetição foram criadas somente no banco QA isolado; sem dados de processo, autenticação, promoção ou escrita no banco de produto.
