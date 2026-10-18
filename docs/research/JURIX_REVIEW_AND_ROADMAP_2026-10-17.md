# Jurix — avaliação do estado atual e próximas entregas

Data: 17/10/2026. Fonte: checkout local `C:\Jurix`, branch `main`, HEAD `d3592597`, incluindo alterações preexistentes não commitadas. Esta é uma avaliação qualitativa apoiada em inspeção e testes; as notas não são métricas científicas nem porcentagens do plano concluído.

## Julgamento

**Nota geral: 6,5/10.** Há uma base de pesquisa e engenharia considerável, com fontes reais, comparação textual e citações úteis. O produto ainda exige que o usuário conheça modos de corpus e formule referências de maneira específica. O fluxo central da PGM não chega a uma cadeia real revisada pela navegação normal.

- **Protótipo de pesquisa: 7,5/10.** Problema relevante, dados autênticos, mecanismos de proveniência e infraestrutura de experimento. Falta demonstrar o ganho por avaliação independente.
- **Engenharia/backend/banco: 7,5/10.** Stack adequada, extrações versionadas, hashes, contratos e testes. Concentração de lógica e distância entre ambientes/caminhos de consulta aumentam o custo de manutenção.
- **Apresentação visual: 7,0/10.** Shell, tokens e agrupamentos dão consistência. A densidade da demo e das fontes compromete a leitura.
- **Usabilidade: 6,0/10.** Busca dividida, modo especial do acervo, recusa de referências agrupadas e excesso de informação foram reproduzidos.
- **Produto open source utilizável: 6,0/10.** Há código, licença e CI localmente inspecionados; documentação de estado e jornada inicial precisam acompanhar o corpus e a execução reais.
- **Prontidão para trabalho da PGM: 5,0/10.** Leitura assistida e triagem documental são demonstráveis. Ainda falta a cadeia revisada que sustenta comparação histórica e conferência de fundamentação.
- **Validade científica: não estabelecida.** Não encontrei no repositório um gold PGM humano adjudicado que cumpra os mínimos de 20 normas e três cadeias. Não deduzir acurácia jurídica da quantidade de testes.

A nota geral é um julgamento do conjunto, não uma média calculada dessas réguas diferentes. Não atribuo 9–10 enquanto a jornada principal falhar para uma formulação natural e a demonstração não estiver ligada a um corpus jurídico revisado.

## Método e ambiente efetivamente usados

A porta `8293` indicada na aba estava fechada. Reativei os containers já existentes de PostgreSQL/Redis do projeto Compose `jurix-normative-qa` e reconstruí somente o web com o checkout atual. A avaliação ocorreu em **http://127.0.0.1:8287**. Não executei migrations nem aceite/promoção de documentos. O worker QA não foi iniciado para esta avaliação; o aviso de fila indisponível não foi tratado como prova de defeito do código.

O endpoint `/api/v1/health/ready/` retornou `ready` com banco, pgvector, Redis e migrations OK. Ele informou checks de Ollama/corpus como `skipped`; essa resposta não certifica geração local nem qualidade/completude do acervo. O Ollama tinha listener local, mas esta avaliação não mede seu desempenho.

As contagens abaixo foram obtidas por agregações Django em transação `SET TRANSACTION READ ONLY`, sem ler peças processuais ou divulgar credenciais. Fonte persistida: [observations.json](evidence/review-20261017/observations.json).

- 6.671 documentos de origem `archive`, 31 de Diário Oficial, oito SAPL e 22 legados. São registros documentais, não 6.671 normas únicas ou vigentes.
- 1.761 eventos candidatos e um escopo de cobertura registrado como `partial`.
- 195 registros de norma visíveis pelo filtro de produto e **zero normas consolidadas** por `consolidated_normas_for_product()`.
- Os 17 documentos aprovados encontrados são legados explicitamente sintéticos. Os 20 documentos com extração aceita são de origem legada; não os contabilizei como revisão do acervo real. Nenhum documento `archive`, SAPL ou DOM possui extração aceita no QA consultado.

Isso explica a aparente contradição entre ter muitos PDFs e ver o grafo normal vazio. Não é correto resolver a contradição marcando documentos como aprovados por contagem ou ocultando o estado pendente.

## O que já é um investimento válido

Manter Django/templates/JavaScript, PostgreSQL/pgvector, Celery/Redis e provedores locais configuráveis. Não há evidência nesta avaliação que justifique trocar o frontend inteiro, adotar outro banco de grafo ou aumentar o modelo para corrigir problemas de escopo e navegação.

O modelo de documentos/extrações imutáveis, hashes, snapshots e eventos sustenta a rastreabilidade necessária. A consulta com referências completas apresentou cinco fontes; o painel agrupou-as por norma. A cópia por teclado preservou 2.361 caracteres em Markdown com destinos oficiais e do PDF local. O PDF local citado respondeu GET 200, `application/pdf`, com cabeçalho `%PDF-`.

Evidências: `src/apps/legislation/document_models.py:39`, `:152`, `src/processing/normative_projection.py:180`, `src/processing/evidence_export.py:424`; [resposta](evidence/review-20261017/archive-explicit-answer.png), [fontes](evidence/review-20261017/sources-desktop.png).

## Problemas reproduzidos que limitam a nota

### REV-01 — o acervo disponível não acompanha a entrada normal do assistente — alto

Em `/normas/`, a busca por `258/2024` informou zero resultados consolidados e ofereceu outro link. Na pesquisa do acervo, esse link encontrou um PDF da LC 258/2024. Em seguida, “Nova pesquisa” abriu `/assistente/?new=1`, sem corpus histórico; uma pergunta sobre LC 55/2004 e LC 258/2024 terminou sem informação suficiente. A rota com `corpus=archive-qa` alcança outro caminho.

Consequência: o usuário pode interpretar um problema de seleção de corpus como ausência da lei. A separação entre fonte pendente e consolidada deve continuar explícita, mas não exigir que ele conheça um parâmetro técnico para descobrir o documento.

Evidências: `src/apps/legislation/api_search.py:559`, `:801`, `src/apps/legislation/norma_queries.py:16`; [busca normal](evidence/review-20261017/normas-search.png), [resultado documental](evidence/review-20261017/archive-search.png), [consulta normal](evidence/review-20261017/default-chat-no-sources.png).

### REV-02 — referências agrupadas naturais são recusadas — alto

Perguntei, no modo de acervo, sobre licenciamento anterior ao novo Código e escrevi: “Confronte o Art. 260, inciso IV, o Art. 262 e o Art. 266 da LC nº 258/2024”, junto do Art. 21 da LC 55. O sistema recusou a associação dos artigos. Repetindo tipo/número/ano após cada artigo, respondeu com cinco fontes.

Esse par de consultas prova sensibilidade à formulação, não recall geral. A correção deve interpretar enumerações com escopo textual inequívoco e apresentar referências reconhecidas para confirmação nos casos realmente ambíguos. Não deve associar automaticamente artigos a qualquer lei próxima.

Evidências: `src/processing/qa_archive_rag.py:2020`, `:2041`; [recusa](evidence/review-20261017/archive-ambiguous-query.png), [resposta após explicitação](evidence/review-20261017/archive-explicit-answer.png).

### REV-03 — interação com o compositor: observação limitada, sem defeito geral comprovado

Após reposicionamento automático por locator, o centro do botão de fontes estava em um retângulo `x=346, y=426, w=446,7, h=33,2`. `elementFromPoint` nesse ponto retornou o `TEXTAREA` com o nome “Digite sua pergunta sobre legislação”. O clique automatizado não abriu o painel; Enter sobre o botão abriu. A cópia funcionou depois por teclado, preservando links.

Na rechecagem, recarreguei a conversa e medi o botão em `y=315`, com hit test correto; um clique direto na posição visível abriu o painel. A screenshot anterior à tentativa automatizada também mostrava o botão acima do compositor. Portanto, retirei esse caso dos defeitos gerais confirmados: o reposicionamento da automação pode ter contribuído. Manter o cenário como regressão a investigar antes de propor alteração de produto.

Evidência: `src/apps/core/static/js/chat.js:254`; [estado anterior ao reposicionamento](evidence/review-20261017/archive-explicit-answer.png), [clique direto após reload](evidence/review-20261017/sources-after-reload-direct-click.png); valores em `observations.json`. Não classificar a primeira leitura vazia de clipboard como bug de Markdown: o clique havia atingido outro elemento.

### REV-04 — a demo concentra casos e explicações demais numa página — médio

A página intitulada LC 258/2024 inclui o cotejo do CTM, minutas, inclusões, múltiplas cadeias e o grafo. No carregamento em 360 × 800, medi 76 headings e 60.739 px de altura de documento. A largura do documento foi 345 px; não houve overflow horizontal global nessa observação após reload. O problema dominante é densidade e hierarquia.

Evidências: `src/apps/legislation/templates/legislation/workspace/pgm_consolidation_demo.html`, `src/apps/legislation/workspace_views.py:3031`; [desktop](evidence/review-20261017/demo-desktop.png), [mobile](evidence/review-20261017/demo-mobile-after-reload-360.png), [grafo após a rolagem](evidence/review-20261017/graph-desktop.png). O grafo distingue cláusulas e alvos em cartões conectados, mas sua posição e altura exigem várias telas para leitura.

### REV-05 — grafo demonstrativo e grafo de produto têm capacidades distintas — alto para o objetivo PGM

`/explorar/` mostrou zero normas disponíveis; a demonstração exibe relações candidatas específicas. Isso é transparente, mas ainda não é o fluxo genérico “encontrar qualquer norma do corpus revisado → ver mudanças → comparar redação”. A demo deve tornar-se uma seleção de casos que usam o mesmo serviço do produto.

Evidências: `src/apps/legislation/templates/legislation/workspace/explore.html:12`, `:99`, `src/apps/legislation/workspace_views.py:2317`, `:2482`, `:3031`; [grafo normal](evidence/review-20261017/explore-product.png).

### REV-06 — detalhes técnicos e ressalvas repetidas disputam espaço com a tarefa — médio

A busca exibe simultaneamente avisos de recuperação, heurística, revisão, ausência de consolidação e metadados como `complete` e hashes. No drawer, a fonte federal de contagem foi rotulada com “Baixa correspondência” e pontuação técnica 0%. Uma fonte normativa adicionada por regra não deveria receber uma indicação de similaridade ausente como se fosse estimativa de sua qualidade jurídica.

Manter um resumo do alcance da resposta e oferecer detalhes de processamento sob disclosure. O texto principal deve explicar a conclusão documental e o que falta para resolvê-la.

Evidências: `src/apps/legislation/templates/legislation/workspace/search.html`; snapshots de `Pesquisa jurídica` e do drawer nesta sessão; [fontes em celular](evidence/review-20261017/sources-mobile-360.png).

### REV-07 — semântica de página e manutenção precisam de uma rodada dirigida — médio

A ficha documental contém um `<main>` dentro do `<main>` do shell. A automação encontrou dois landmarks principais na mesma página. O módulo `qa_archive_rag.py` tem 8.892 linhas e `workspace_views.py` 3.872 no checkout observado, concentrando vários caminhos especiais. O verificador arquitetural passou, porém esses dois arquivos não estão em `DEFAULT_BUDGETS`; esse resultado não atesta que seus tamanhos/limites sejam adequados.

Evidências: `src/apps/legislation/templates/legislation/document_evidence.html:8`, `src/apps/legislation/templates/legislation/workspace/base.html:30`, `scripts/architecture_budget_v2.py:11`. A duplicação de landmark é uma deficiência semântica; esta inspeção não estabelece, sozinha, conformidade ou reprovação WCAG integral.

### REV-08 — a documentação pública tem números e estado antigos — médio

O README ainda afirma que os 40 PDFs arquivados continuam pendentes no QA e apresenta resultados de 06/10, enquanto o QA atual contém 6.671 registros do acervo local. Há um histórico amplo em documentos de pesquisa, mas o leitor precisa distinguir a visão atual desses relatos históricos.

Evidência: `README.md:977`. A atualização futura deve usar data, escopo e comando de reprodução; não publicar um total de documentos como total de normas consolidadas.

## Próximas entregas propostas

Esta sequência prioriza o plano existente P-001–P-023; não o substitui nem altera suas exigências de revisão humana. Implementação futura deve ocorrer em mudanças pequenas, cada uma com seu aceite. Não fiz essas alterações nesta avaliação.

1. **R-01 — oferecer uma entrada clara para todo o acervo.** P-011/P-019. Nos fluxos de `norma_list.html`, `workspace/search.html`, sidebar e `api_search.py`, tornar o escopo “acervo documental” uma escolha visível e persistente por conversa. Antes de dar ausência de resultado, indicar qual corpus foi consultado e oferecer a busca documental. Aceite: partir de “Nova pesquisa”, encontrar LC 258 e abrir sua fonte sem conhecer `corpus=archive-qa`; documentos continuam rotulados como não revisados. É a primeira correção recomendada.
2. **R-02 — reconhecer enumerações e pedir confirmação apenas da referência incerta.** P-013/P-019. Isolar o parser de referências agrupadas do caminho de geração. Cobrir a frase reproduzida em REV-02 e negativos com duas leis disputando o mesmo artigo. Aceite: a formulação natural e a versão explícita resolvem o mesmo conjunto de referências; ambiguidades reais oferecem candidatos sem atribuição inventada.
3. **R-03 — reduzir a carga visual e esclarecer a evidência.** P-015/P-019/P-021. Organizar a demo por caso/tarefa, recolher metadados técnicos, traduzir estados e evitar pontuação de similaridade fictícia para fontes adicionadas por regra. Remover o landmark principal aninhado. Aceite: uma pessoa encontra o grafo e o antes/depois sem percorrer outros casos; manter fontes, cópia e limites acessíveis por mouse/teclado em desktop/mobile. Reproduzir o estado de REV-03 com interação direta antes de alterar a geometria do compositor.
4. **R-04 — concluir três cadeias reais revisadas.** P-004/P-006/P-007/P-009/P-010. Começar por uma alteração textual integral pequena, uma revogação parcial e uma cadeia com vacância/transição. A LC 258 e o CTM são candidatos à seleção do orientador; a divergência da LC 55 não precisa bloquear outra cadeia mais simples. Conferir identidade, edição, cláusula, alvo e datas no PDF/DOM; registrar a revisão no fluxo existente. Aceite: perguntar/abrir o artigo mostra antes/depois, ato modificador e data comprovados; conflito fica explícito. Aprovação jurídica cabe ao revisor legítimo.
5. **R-05 — colocar a demo no mesmo caminho do produto.** P-010/P-012/P-014/P-015/P-016. Extrair os serviços reutilizáveis hoje concentrados em `workspace_views.py`; renderizar os casos por parâmetros e eventos versionados. Criar uma ficha com resumo e abas “Texto na data”, “Alterações”, “Grafo” e “Fontes”. Aceite: a mesma cadeia alimenta chat, comparação, grafo e exportação, sem regras específicas de uma lei no controlador; um segundo caso usa o mesmo percurso.
6. **R-06 — crescer por lotes, começando pelos atos recentes e dispositivos operativos.** P-003/P-008/P-009/P-017/P-018. Usar o inventário existente e ordenar trabalho por publicação comprovada. Resolver identidades-alvo e pendências de modo retomável. Priorizar texto de artigos e referências a anexos; preservar PDF integral. Aceite: cada lote informa universo, processados, falhas, cobertura e revisão, e a chegada de um alvo retoma as relações pendentes. Comparar extração estruturada Markdown/HTML com o pipeline atual em amostra real antes de trocar o extrator.
7. **R-07 — produzir evidência científica e observar procuradores.** P-020/P-021. Executar `PGM_GOLD_ADJUDICATION.md`: mínimo de 20 normas distintas e três cadeias, revisão independente e adjudicação; congelar teste por cadeia. Comparar baseline, grafo e grafo temporal nas mesmas condições, medindo erros de ação/alvo/data, citações, abstenção e latência. Depois observar 3–5 assessores no fluxo de conferência, medindo tarefa concluída e tempo. Aceite: resultados reproduzíveis, inclusive negativos; casos não solucionáveis permanecem no denominador.
8. **R-08 — transformar o checkout em piloto reproduzível e projeto open source legível.** P-022/P-023. Um comando/porta estável por perfil, identificação de build, worker/atualização monitorados, restore ensaiado e checks na configuração de deployment. Atualizar o README sem confundir histórico com estado atual; adicionar roteiro curto de instalação, contribuição e demonstração com amostra redistribuível. Aceite: outra pessoa instala, percorre os casos e reproduz os resultados sem apoio desta conversa. Tratar a divisão dos módulos grandes em etapas separadas e orientar os limites por responsabilidades e contratos, não só linhas.

Para chegar à faixa 8, a prioridade é R-01–R-05. Para sustentar 9–10 como pesquisa/produto, R-07 e R-08 precisam de prova prática, além do crescimento controlado de R-06. Não atribuo prazo em horas sem estimar o backlog de revisão com o orientador.

## Verificações e limites

Comando novo desta avaliação:

```powershell
$env:JURIX_QA_ONLY='1'
$env:JURIX_QA_ROOT=Join-Path $env:TEMP 'jurix-pgm-goal-qa-20261008'
uv run python scripts/normative_qa.py --run python -m pytest -q --reuse-db --tb=short src/tests/test_foundation_reference_parser.py src/tests/test_normative_query.py src/tests/test_evidence_export.py src/tests/test_corpus_coverage.py
```

Resultado: **76 passed em 1,30 s**, incluindo os testes de banco de cobertura em banco descartável de pytest. `manage.py check` passou. O verificador arquitetural passou com a limitação de escopo descrita em REV-07. Não repeti a suíte integral Python/JS nem atribuo os resultados históricos a esta execução.

Na UI, testei busca normal/documental, ficha, exploração, três variações de consulta pública, acesso às fontes por mouse/teclado, cópia Markdown e vista de 360 px. `/conferir/` redirecionou corretamente o anônimo ao login com contexto; o fluxo autenticado e dossiês não foram testados nesta rodada. O PDF foi verificado por GET, não por adjudicação de seu conteúdo. A primeira tentativa HEAD retornou 405; não foi classificada como PDF ausente após o GET bem-sucedido.

Não houve estudo com participantes, medição de precisão jurídica, rechecagem integral de segurança, leitor de tela, zoom nativo 200%, Core Web Vitals ou benchmark do Ollama. A resposta com cinco fontes não é prova de inferência local/streaming do LLM. A inspeção responsive não cobre todos os estados nem certifica WCAG.

Referências consultadas: [WCAG 2.2](https://www.w3.org/TR/WCAG22/) para estrutura, foco, reflow e alvos; [NN/g — heurísticas de usabilidade](https://www.nngroup.com/articles/ten-usability-heuristics/) para consistência, visibilidade e linguagem do usuário; [Django — deployment checklist](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/) para avaliação operacional por configuração. A página de [feedback da Apple HIG](https://developer.apple.com/design/human-interface-guidelines/feedback) foi acessada, mas seu corpo não foi plenamente extraível; não declaro aderência formal à HIG. O polimento proposto usa hierarquia, feedback discreto e divulgação progressiva como critérios de design.

Estado preservado: os diffs de código/testes/progresso e o log local existentes antes desta avaliação não foram editados. Foram adicionados apenas este documento e evidências, além de um Canvas de avaliação fora do repositório. Sem commit/push/merge, troca de branch, migration, promoção de norma ou escrita de conteúdo jurídico no banco. As conversas públicas de teste ficaram no histórico local do navegador QA.
