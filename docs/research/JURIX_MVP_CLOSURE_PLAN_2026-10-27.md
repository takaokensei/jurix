# Jurix — plano de fechamento do MVP

Data: 27/10/2026. Destino: execução por GPT 6 Luna em esforço **alto**.
Checkout inspecionado: `L:\Jurix`, `main`, HEAD `1ac3ab75`, incluindo trabalho não commitado.
Status deste documento: **plano proposto; implementação ainda não executada**.

## 1. Decisão de produto e ponto de chegada

Entregar o **Jurix MVP de pesquisa documental e consolidação experimental**:
uma pessoa encontra uma norma, lê o PDF, consulta artigos, confronta redações,
vê relações e exporta as evidências pelo mesmo percurso da aplicação.
A análise/adjudicação por IA é suficiente para desenvolver e entregar esse MVP.
Nenhuma tarefa de software abaixo depende de promotor, procurador ou jurista.

A entrega será considerada concluída quando os aceites da seção 7 passarem e
um pacote de instalação, dados do piloto e evidências puder ser reproduzido.
O aceite não depende de uma nota subjetiva 9/10 nem de continuar refinando a UI.

O produto apresentará o que conseguiu reconstruir **dentro do acervo e do escopo
processados**, com vínculos ao documento original. Conflito ou data sem prova
continua sendo um resultado utilizável: a pessoa vê o problema e suas fontes.
A interface não deve transformar essa limitação em uma recusa genérica de toda
a consulta quando já existe conteúdo documental útil.

Este plano é um recorte de entrega de R-01–R-08, preservando os planos e
protocolos anteriores. O estudo com procuradores e a validação jurídica
independente permanecem marcos posteriores; não serão declarados realizados.
O MVP pode ser encerrado sem esses marcos. O conjunto Gold v1 continua com sua
autoria por IA e seus hashes originais.

## 2. Escopo fechado

### Incluído na entrega

1. **Acervo geral:** busca e abertura dos documentos efetivamente disponíveis,
   com contadores de cobertura derivados do banco em uso.
2. **Coleção operacional de 20 normas:** todas descobríveis por tipo/número/ano,
   título quando comprovado e links dos dispositivos selecionados. O corpus
   operacional usa as extrações dos PDFs; o gabarito permanece na avaliação.
3. **Três percursos reais:** CTM/LC 271, LC 258/revogação parcial/transição,
   LC 208/LC 261. Cada um tem comparação, grafo, fontes e perguntas no chat.
4. **Consolidação experimental por dispositivo:** substituição textual integral,
   acréscimo e revogação expressa de alvo identificado. Aplicação por data apenas
   quando o intervalo e sua evidência estiverem resolvidos.
5. **Caso de conflito:** LC 55, Art. 34, exibindo a divergência de numeração.
6. **Assistente:** pergunta direta, pergunta sobre uma lei, seguimento contextual,
   citações, fontes durante a geração, cópia Markdown e restauração após F5.
7. **Operação local:** comando único, porta estável, build identificável,
   armazenamento comum ao web/worker, exportação e restauração do piloto.
8. **Relatório técnico:** execução das 28 perguntas congeladas, comparação dos
   braços sobre a mesma população e roteiro final de usabilidade.

### Fora desta versão

- Consolidar integralmente milhares de leis ou todos os anexos/tabelas.
- Declarar vigência universal, resolver revogação tácita por similaridade ou
  fornecer uma decisão automática para um processo real.
- Acrescentar projetos de lei ao RAG, ampliar provedores/modelos ou trocar stack.
- Novo frontend, novo banco de grafos, implantação pública multiusuário,
  Graphify como dependência do produto ou benchmark científico independente.
- Refatoração completa dos módulos grandes, OCR de todo o backlog e cosmética
  sem efeito sobre um aceite desta versão.

As demais normas do acervo continuam pesquisáveis segundo sua disponibilidade;
a coleção de 20 é o mínimo de entrega verificável, não um limite artificial da busca.

## 3. Estado observado e causa do problema

O levantamento desta rodada está em
[`evidence/mvp-closure-20261027.json`](evidence/mvp-closure-20261027.json).
Os números históricos do banco não foram revalidados porque PostgreSQL QA
`:55432`, Redis `:16380` e os webs `:8293/:8294` estavam sem listener no último
probe. Ollama tinha listener em `:11434`; inferência não foi medida nesta rodada.
A aba aberta não comprova que seu servidor continue ativo.

- O pacote Gold passa na validação atual: **20 normas, 41 recortes, 13 eventos,
  28 perguntas, 37 arquivos**. PDFs originais não foram rechecados nesta execução.
  Evidência: `scripts/pgm_project_gold.py`; registro
  `benchmarks/corpus/municipal_natal/project-gold.v1.json`.
- `src/apps/legislation/norma_queries.py:16` lista como consolidadas apenas
  `Norma.status=consolidated`. O Gold é um pacote de avaliação, não executa
  essa promoção.
- `src/apps/legislation/workspace_views.py:2139` implementa o catálogo Gold
  separado. Ele dá acesso aos casos, mas não produz versões consolidadas.
- `src/processing/normative_projection.py:104` exige base/extração/segmentação
  revisadas para a projeção já existente. `AIPilotAdoption`, em
  `src/apps/legislation/document_models.py:607`, registra adoções IA separadas.
  Falta integrar o percurso experimental com a projeção e o dossiê.
- `src/processing/normative_casefile.py:120` já agrega projeção, grafo e
  exportação, mas seu ponto de entrada é uma `Norma` do percurso revisado.
- `src/apps/legislation/api_search.py:827` encaminha o acervo a outro gerador.
  `src/processing/qa_archive_rag.py:5848` responde com abstenção imediata quando
  recebe solicitação temporal. Portanto, hoje a rota documental não reconstrói
  uma versão na data apenas porque há um grafo demonstrativo em outra tela.
- `scripts/collect_normative_rag_experiment.py:365` chama
  `AdaptiveRAGService`; o último experimento registrado comparou a população
  legada em vez dos PDFs Gold. Os zeros dessa execução não são uma medida
  válida de ganho/perda do grafo sobre o acervo documental.
- `src/processing/qa_archive_rag.py:1196` reconhece ano de consolidação com
  vocabulário restrito; `:1699` reconhece somente o título Código de Obras.
  Compilação/ano da edição e ano do ato precisam ser resolvidos separadamente.
- Existem alterações em 85 entradas de `git status`. A comparação com o
  upstream já conhecido informa 0 commits à frente/12 atrás; não houve fetch.
  Isso não autoriza sincronização nem descarte do estado local.

O gargalo é a integração entre corpus, evidência e projeção. Mudar a aparência
do estado vazio ou marcar todos os documentos como aprovados não entrega essa integração.

## 4. Graphify e Context7: uso efetivamente realizado

**Graphify 0.9.96:** executado via ambiente temporário `uvx`, com análise AST
local de 16 arquivos centrais: **556 nós, 1.417 arestas, zero fontes com falha**.
Não houve análise semântica dos PDFs nem instalação de hooks/configuração no
agente. O extrator criou cache local em `graphify-out/`. A análise delimita as
dependências a preservar ao introduzir os adaptadores do piloto. As funções
indicadas acima também foram lidas diretamente.
Referência: [Graphify oficial](https://github.com/Graphify-Labs/graphify/tree/v8).

Comando de reprodução do mapa de código, a partir da raiz:

```powershell
uvx --from graphifyy==0.9.96 --python 3.12 python -m graphify.extract src/apps/legislation/api_search.py src/apps/legislation/workspace_views.py src/apps/legislation/norma_queries.py src/apps/legislation/document_models.py src/apps/legislation/serializers.py src/apps/ingestion/management/commands/adopt_ai_pilot_review_qa.py src/processing/qa_archive_rag.py src/processing/adaptive_rag_service.py src/processing/normative_casefile.py src/processing/normative_projection.py src/processing/normative_graph.py src/processing/evidence_export.py src/processing/coordinated_article_references.py scripts/collect_normative_rag_experiment.py scripts/evaluate_pgm_project_gold.py scripts/evaluate_pgm_project_gold_archive.py
```

**Context7:** o servidor oficial respondeu à inicialização, listagem, resolução
de Django e consulta de documentação de Django 5.2, sem envio de código local.
A consulta confirmou o uso de transações e de `transaction.on_commit()` para
invalidar caches/enfileirar trabalho após a gravação. Aplicar isso ao builder
do corpus. Não depender da disponibilidade de Context7 para executar o MVP.
Referências: [Context7](https://context7.com/docs/overview) e
[transações do Django 5.2](https://docs.djangoproject.com/en/5.2/topics/db/transactions/).

Os dois recursos auxiliam o desenvolvimento. A identidade e os efeitos das
relações jurídicas continuam ligados aos PDFs e aos registros do Jurix.

## 5. Contratos mínimos da implementação

### 5.1 Corpus operacional e gabarito

Criar uma **revisão imutável do corpus piloto**, em armazenamento QA, derivada
de `DocumentoNormativo`/`ExtracaoDocumento` e das adoções IA autorizadas.
Pode ser um manifesto JSON versionado e seus sidecars: não é necessário criar
outro conjunto de tabelas para entregar a primeira versão.

O manifesto mínimo terá `schema_version`, `corpus_revision`, data de captura,
inventário dos hashes, identidade tipada, edição, dispositivos com offsets/página,
relações documentadas, cobertura e origem de cada decisão. IDs internos de banco
não são identidade portátil: resolver PDF por SHA-256 e extração por digest.

Usar seleção de fontes separada em
`benchmarks/corpus/municipal_natal/pilot-source-selection.v1.json`.
Ela pode reutilizar os hashes dos mesmos documentos públicos, mas não conter
perguntas, respostas esperadas, `expected_*` ou rótulos de avaliação.
O builder não pode importar `queries.ai.jsonl` nem as respostas Gold para montar
respostas. Análise IA anterior adotada é entrada declarada do piloto; sua
exposição ao desenvolvimento continua declarada na avaliação retrospectiva.

Reexecutar com entradas idênticas devolve a mesma revisão. Uma correção cria
sucessora; o builder nunca substitui a extração aceita ou muda `review_status`
de candidatos. Falta de PDF/extrato gera item com motivo e cobertura incompleta.

### 5.2 Identidade e referência

- Norma: jurisdição + espécie + número normalizado + ano do ato.
- Edição: hash do PDF + metadado da compilação; ano da edição não substitui ano do ato.
- Dispositivo: caminho estrutural estável (`art:21`, `art:18/par:2`, etc.).
- Evidência: hash da extração, offsets exatos, página 1-based, trecho e URL/PDF local.
- Evento: fonte/dispositivo modificador, ação, alvo tipado, alcance, trecho,
  publicação, início/fim de efeitos e estado de resolução de cada campo.
- Citação: identificador estável derivado da evidência/escopo; não depende da
  posição do item em um top-k. O marcador visual pode continuar sendo `[[n]]`.

### 5.3 Projeção experimental

Reutilizar os algoritmos do motor existente por meio de um adaptador de dados;
preservar o caminho revisado. Não suprimir seus guards globais.
Um DTO experimental explícito permite aplicar somente eventos adotados e
documentados no escopo. A estrutura devolve redação anterior, redação posterior
ou revogação, fonte modificadora, intervalo conhecido, conflitos e cobertura.

Regras obrigatórias:

1. Ordenar a aplicação por **data de efeito comprovada**, não pelo número da lei.
   A varredura recente→antiga é uma estratégia de ingestão, não de aplicação temporal.
2. Substituição só quando o novo texto/alvo completo está recuperado; alteração
   fragmentária mostra comparação parcial, sem fabricar a parte omitida.
3. Revogação parcial altera somente o dispositivo-alvo. Guardar o texto histórico.
4. Revogação genérica não cria alvos. Menção a outra norma não vira alteração.
5. Data desconhecida permite cotejo documental, mas não atribuição em D−1/D/D+1.
6. Eventos concorrentes/conflitantes mantêm o dispositivo indeterminado.
7. Uma compilação de 2024 pode ser base de comparação daquela edição; não
   reconstruir automaticamente períodos anteriores a essa base.
8. Usar “sem alteração localizada no escopo” quando apropriado. Ausência no
   conjunto não prova ausência no universo legislativo.

### 5.4 Um dossiê para todas as superfícies

O mesmo resultado terá `casefile_id`, `corpus_revision`, `as_of`, `basis`,
`coverage`, `devices`, `events`, `sources` e `conflicts`.
`basis` distingue `reviewed`, `ai_pilot` e `documentary_candidate`.
Chat, comparação, grafo e exportação devem consumir esse resultado, sem quatro
interpretações independentes da mesma cláusula.

Na UI, agrupar em **Normas e acervo** com filtros “Todos”, “Consolidação
experimental”, “Documentos” e, quando houver, “Revisadas”. Uma norma pode ter
alguns dispositivos reconstruídos; mostrar “2 dispositivos cobertos”, não
“lei inteira consolidada”. O Gold mantém sua tela de avaliação separada.

### 5.5 Resposta e incerteza

A conclusão documental vem primeiro, com citação próxima da afirmação.
Quando não há data resolvida, dizer qual redação/alteração foi encontrada e
qual data falta. A nota do piloto fica uma vez no contexto da tela; detalhes
de hashes/processamento sob expansão. Ressalvas específicas ficam junto do
dispositivo que afetam.

O LLM redige explicações; não inventa URL, ação, alvo, data ou texto substitutivo.
As fontes são resolvidas pelo servidor e recebidas durante o SSE.

## 6. Sequência finita de tarefas

Cada M-## representa uma mudança coerente e revisável. Preservar o trabalho
existente e executar primeiro uma regressão relevante; só alterar aquilo que
falhar ou faltar. Nenhum commit/push/merge/switch é autorizado por este plano.
Comandos novos citados abaixo são **interfaces a implementar**, não comandos já
disponíveis. As suítes e scripts existentes são indicados por caminho real.

### M-01 — inicialização e identidade únicas

Pré-requisito: nenhum. Cobre R-08.

Arquivos: `docker-compose.audit.yml`, `scripts/start_pgm_mvp.ps1` (novo),
`scripts/status_pgm_mvp.ps1` (novo), `src/apps/core/build_identity.py`,
`src/tests/test_audit_stack_config.py`, `src/tests/test_build_identity.py`.

1. Implementar `start_pgm_mvp.ps1 -Port 8294` com raiz obtida de `$PSScriptRoot`.
2. Usar somente os serviços QA, declarando a configuração de interpolação
   explicitamente para não herdar configuração de produto.
3. Se a porta estiver ocupada, comparar build e perfil; reutilizar somente o
   processo compatível. Se incompatível, informar PID/porta e encerrar o comando
   sem matar o processo nem escolher porta aleatória.
4. Identificar revisão de Git **e digest do conteúdo dirty**; HEAD sozinho é
   insuficiente. Não expor caminhos de usuário/segredos na UI.
5. Conferir DB/Redis/migrations, worker e disponibilidade do modelo separadamente.
   O status deve indicar o URL exato e a revisão do corpus ativa.
6. Definir um armazenamento QA comum de blobs/manifestos para web e worker.

Aceite: duas execuções seguidas mantêm o mesmo URL/build; instância velha é
detectada; nenhum processo preexistente é encerrado. Verificar os testes de
build/Compose e a inicialização real duas vezes. Não executar migrations
novas automaticamente sem mostrar seu plano; se forem necessárias, apenas aditivas no QA.

### M-02 — materializar as 20 fontes do piloto

Pré-requisito: M-01. Cobre R-01/R-06/R-07.

Arquivos: `src/processing/pilot_corpus.py` (novo),
`src/apps/ingestion/management/commands/build_pgm_pilot_qa.py` (novo),
`benchmarks/corpus/municipal_natal/pilot-source-selection.v1.json` (novo),
`src/tests/test_pilot_corpus.py` (novo), `scripts/normative_qa.py`.

1. Resolver os 20 PDFs por hash e conferir o blob no armazenamento canônico.
   Copiar um blob de outro volume QA apenas após verificar origem/hash; preservar a origem.
2. Reutilizar extrações existentes compatíveis; extrair apenas fontes ausentes,
   em lotes limitados e retomáveis, guardando página/offset.
3. Produzir manifesto com universo/processados/falhas e revisão por conteúdo;
   recusar sobrescrever outra revisão.
4. Disponibilizar as 20 identidades e os dispositivos selecionados, mantendo
   explicitamente a diferença entre edição, ato original e compilação.
5. Adicionar o comando ao runner QA com flags e diretório de saída restritos.

Aceite: 20/20 PDFs abrem, 20/20 têm fonte técnica pesquisável; repetição não
duplica registros. Estado jurídico, extração aceita e vínculos de produto
ficam iguais antes/depois. Testar blob ausente, hash divergente e colisão LO/LC.

### M-03 — referência tipada, títulos e edições

Pré-requisito: M-02. Cobre R-02/R-06.

Arquivos: `src/processing/normative_query.py`,
`src/processing/coordinated_article_references.py`,
`src/processing/qa_archive_rag.py`, `src/processing/pilot_corpus.py`,
`src/tests/test_normative_query.py`, `src/tests/test_qa_archive_rag.py`.

1. Interpretar CTM/Código Tributário Municipal e Código de Obras a partir de
   títulos/aliases comprovados pelo manifesto, não de número fixado no prompt.
2. Reconhecer “compilação”, “consolidação” e ano da edição, vinculando o ano
   apenas à referência correspondente na frase.
3. Reutilizar o parser de artigos agrupados e o contexto da conversa.
4. Resolver referência exata antes de top-k; ambiguidade entre duas normas
   retorna candidatos apenas para a referência incerta.

Aceite: consulta por Art. 20/CTM/compilação 2024 recupera o documento da edição
pedida sem exigir que o usuário conheça 3.882/1989. Edição 2022 não é trocada
pela 2024; LO e LC com mesmo número permanecem distintas. Forma natural de
REV-02 e forma explícita devolvem os mesmos pares.

### M-04 — catálogo operacional das normas experimentais

Pré-requisitos: M-02/M-03. Cobre R-01/R-03.

Arquivos: `src/apps/legislation/workspace_views.py`,
`src/apps/legislation/views.py`, `src/apps/legislation/templates/legislation/norma_list.html`,
`src/apps/legislation/templates/legislation/workspace/search.html`,
`src/apps/legislation/templates/legislation/workspace/_sidebar.html`,
`src/tests/test_workspace_routes.py`.

1. Ler o manifesto piloto no catálogo comum, sem converter todos os candidatos
   em `Norma.status=consolidated`.
2. Exibir os 20 como normas disponíveis para consulta experimental; agrupar
   dispositivos/edições sob a identidade normativa.
3. Preservar os documentos gerais e seus filtros; separar contagens de norma,
   PDF, dispositivo coberto e revisão.
4. Manter um link secundário para o Gold e eliminar o estado vazio global
   quando há conteúdo experimental consultável.

Aceite: Nova pesquisa→Normas→LC 258→dispositivo→PDF funciona sem parâmetro
`corpus=archive-qa`. Filtro “Revisadas” vazio continua verdadeiro e específico.

### M-05 — eventos experimentais com proveniência

Pré-requisito: M-02. Cobre R-04/R-06.

Arquivos: `src/processing/pilot_corpus.py`,
`src/processing/pilot_events.py` (novo),
`src/apps/ingestion/document_relation_candidates.py`,
`src/apps/ingestion/management/commands/build_pgm_pilot_qa.py`,
`src/tests/test_pilot_events.py` (novo).

1. Criar eventos derivados de cláusulas operativas e das adoções IA já
   autorizadas; registrar origem, versão, citação e alcance de cada decisão.
2. Vincular alvos por identidade estrutural, nunca apenas por embedding.
3. Normalizar antes/depois integral, acréscimo e revogação parcial/total.
4. Conservar referências não resolvidas e conflitos com motivos específicos.
5. Incluir publicação/efeito/fundamento como campos separados; não calcular
   vigência usando nome de arquivo ou data da sessão.

Aceite: LC 258, Art. 260, V, atinge apenas Art. 21 da LP 275. I/II/VII não
recebem alvo inventado; LC 55 mantém conflito; LC 208/261 mantém data desconhecida
se a fonte não a resolve. Um segundo processamento não duplica evento.

### M-06 — projeção e comparação experimental por dispositivo

Pré-requisito: M-05. Cobre R-04/R-05.

Arquivos: `src/processing/pilot_projection.py` (novo),
`src/processing/normative_projection.py`, `src/processing/legal_diff.py`,
`src/tests/test_pilot_projection.py` (novo),
`src/tests/test_normative_projection.py`.

1. Extrair/reutilizar as operações puras do motor; adicionar adaptador para o
   manifesto piloto sem desativar `_reviewed_base()` do percurso revisado.
2. Projetar somente o dispositivo e intervalo com evidências suficientes.
3. Revogação marca o alvo e mantém o texto anterior; substituição registra
   ambas as versões e o ato modificador.
4. Retornar os estados `reconstructed`, `partial`, `conflict`, `unknown_date`
   e `out_of_coverage`, acompanhados das fontes.
5. Implementar D−1/D/D+1 quando D for comprovado; para data desconhecida,
   produzir cotejo documental sem marcar uma redação como vigente naquela data.

Aceite: testes de ordenação por efeito, revogação parcial, dupla alteração,
conflito, compilação posterior à data pedida e ausência de data. A inferência
do texto não depende de LLM. Projeções idênticas têm o mesmo digest.

### M-07 — dossiê único, abas e grafo do produto

Pré-requisitos: M-04/M-06. Cobre R-03/R-05.

Arquivos: `src/processing/pilot_casefile.py` (novo),
`src/processing/normative_casefile.py`, `src/processing/normative_graph.py`,
`src/processing/evidence_export.py`, `src/apps/legislation/workspace_views.py`,
`src/apps/legislation/workspace_urls.py`,
`src/apps/legislation/templates/legislation/workspace/normative_casefile.html`,
`src/apps/core/static/js/jurix-normative-casefile.js`,
`src/tests/test_normative_casefile.py` (novo, se ausente),
`tests/js/normative-casefile-tabs.test.mjs`.

1. Implementar um adaptador de dossiê experimental com o contrato da seção 5.4.
2. Abrir a ficha por identidade/edição, sem depender de UUID histórico hardcoded.
3. Abas: “Texto e comparação”, “Alterações”, “Grafo”, “Fontes”.
4. Usar os mesmos eventos no grafo, nos estados dos dispositivos e na exportação.
5. Grafo navegável com alcance parcial/total e conflitos visíveis; equivalente
   em lista para teclado e telas pequenas.
6. A demo passa a selecionar casos do percurso comum. A view não incorpora
   novas regras específicas de CTM ou LC 258.

Aceite: as três cadeias abrem pelo mesmo componente/serviço; comparar, abrir
aresta, seguir fonte e exportar preservam `casefile_id` e `corpus_revision`.
Nenhum link retorna ao visitante uma ficha sem permissão; fonte pública segue
seu caminho oficial ou o endpoint QA já autorizado.

### M-08 — assistente consome o mesmo corpus e dossiê

Pré-requisitos: M-03/M-07. Cobre R-01/R-02/R-04/R-05.

Arquivos: `src/processing/pilot_rag.py` (novo),
`src/processing/qa_archive_rag.py`, `src/processing/adaptive_rag_service.py`,
`src/apps/legislation/api_search.py`, `src/apps/legislation/serializers.py`,
`src/llm_engine/prompts.py`, `src/tests/test_pilot_rag.py` (novo).

1. Roteador escolhe leitura de artigo, visão de norma, comparação ou consulta
   temporal antes de gerar. A seleção de corpus é visível/persistente.
2. Referência exata usa índice direto; lei pequena recupera cobertura ampla;
   similaridade serve a pergunta temática, sem decidir sozinha a abrangência.
3. Pedido de data consulta a projeção experimental se houver escopo; tirar a
   recusa temporal incondicional apenas desse caminho suportado.
4. Se só parte estiver resolvida, responder essa parte e apontar precisamente
   a pendência, com as respectivas evidências.
5. Redigir conclusão primeiro e prosa natural. A aplicação resolve URLs e
   marcadores de citação; a resposta pode funcionar em modo documental se
   Ollama estiver indisponível, identificado como extração/cotejo.

Aceite: “O que mudou?”, “E o artigo anterior?” e “isso revogou a lei inteira?”
mantêm a identidade da conversa. Uma pergunta da mesma cadeia obtém os mesmos
alvos/datas da ficha; nenhuma resposta infere vigência além da cobertura.

### M-09 — streaming, fontes, cópia e estados

Pré-requisito: M-08. Cobre R-03/R-05.

Arquivos: `src/apps/core/static/js/jurix-rag.js`,
`src/apps/core/static/css/jurix-rag.css`,
`src/apps/legislation/templates/legislation/chatbot.html`,
`src/apps/legislation/chat_api_helpers.py`,
`tests/js/streaming.behavior.test.mjs`, `src/tests/test_serializers.py`.

1. Disponibilizar fontes ao receber `sources`, mesmo com geração em andamento.
   Reservar espaço e usar transição discreta; respeitar reduced-motion.
2. Resolver citações da resposta parcial; `done` consolida o estado sem
   recriar desnecessariamente a mensagem inteira.
3. Copiar Markdown com links produzidos a partir dos mesmos metadados.
4. Persistir evidências/corpus da conversa; cancelar/interromper não deixa
   resposta em estado final falsamente concluído.
5. Testar envio, falha do modelo, interrupção, retry, F5, voltar/avançar e fontes
   por teclado. Não esconder conclusão insuficiente com animação.

Aceite: fonte abre antes do `done`; cópia mantém URLs; F5 mantém as citações;
botões acessíveis em 360/768/1280/1920 px e zoom 200%; zero erro JS introduzido.

### M-10 — medir o corpus certo e conferir negativos

Pré-requisitos: M-08/M-09. Cobre R-07.

Arquivos: `scripts/collect_normative_rag_experiment.py`,
`scripts/evaluate_pgm_project_gold.py`,
`scripts/evaluate_pgm_project_gold_archive.py`, `scripts/normative_qa.py`,
`src/tests/test_normative_rag_experiment_collection.py`,
`src/tests/test_pgm_project_gold_archive.py`.

1. Coletor recebe explicitamente a revisão do corpus piloto. Baseline, grafo e
   grafo temporal usam as mesmas fontes elegíveis, modelo e orçamento.
2. Antes da geração, conferir a correspondência de **todas** as fontes esperadas
   com o corpus avaliado; não aceitar só uma fonte com hash como prova de alinhamento.
3. Registrar seleção/latência/fontes/ação/alvo/data/abstenção, mesmo em falhas.
   Uma exceção vira resultado falho do caso, não exclusão do denominador.
4. Medir 28 consultas×3 braços, com predições separadas do Gold. Declarar que
   a referência e parte das decisões operacionais têm autoria IA/exposição prévia.
5. Acrescentar 12 perguntas novas de regressão a partir dos documentos, criadas
   antes de observar saídas; quatro temáticas, quatro seguimentos e quatro
   negativas. Guardar separado, sem editar o Gold v1.
6. Sem ganho do grafo é um resultado válido; não exigir melhora artificial
   para liberar software. Falha de rastreabilidade é defeito de produto.

Aceite: cumprir G-09 da seção 7 e gerar relatório imutável. Tuning após olhar
resultados é desenvolvimento; uma rodada posterior não vira teste independente.

### M-11 — demonstração reproduzível e usabilidade real da aplicação

Pré-requisito: M-10. Cobre R-01/R-03/R-05/R-08.

Arquivos: `tests/js/pgm-mvp-acceptance.mjs` (novo),
`tests/js/pgm-workflow-smoke.mjs`, `scripts/normative_qa.py`,
`docs/research/JURIX_MVP_DEMO.md` (novo).

1. Automatizar o roteiro da seção 8 em navegador com PDFs reais QA.
2. Verificar build/corpus antes de interagir e nomes acessíveis nos controles.
3. Executar desktop e mobile; testar teclado e uma rodada de zoom nativo 200%.
4. Registrar screenshots sem dados pessoais e logs de falhas no root QA.
5. Demonstrar três cadeias e um conflito, inclusive uma pergunta sem resposta
   resolvida. A demo não pode depender de chat pré-preenchido ou de porta antiga.

Aceite: todo roteiro passa partindo de Nova pesquisa e de um navegador limpo.
Esse ensaio é de engenharia/usabilidade da aplicação, sem atribuir participação
de procuradores a interações do agente.

### M-12 — empacotar, restaurar e encerrar

Pré-requisitos: M-01–M-11. Cobre R-08 e fechamento da entrega.

Arquivos: `scripts/verify_pgm_mvp_release.py` (novo),
`scripts/export_pgm_pilot_qa.py` (novo),
`scripts/restore_pgm_pilot_qa.py` (novo),
`docs/research/JURIX_MVP_DELIVERY.md` (novo), `README.md`.

1. Empacotar revisão do corpus/sidecars e apontar como obter PDFs de fonte
   pública ou fornecer bundle local. Separar código e dados; conferir condições
   de redistribuição de cada origem antes de publicar PDFs.
2. Restaurar em banco/armazenamento QA descartáveis com nome único, verificar
   hashes, mesmas três cadeias e mesmos resultados determinísticos. Preservar QA principal.
3. Executar a suíte relevante Python/JS e os checks de instalação. Documentar
   falhas de baseline sem ignorar regressões do trabalho novo.
4. O verifier emite G-01–G-12 com evidência e `pass/fail/not_run`; só retorna
   sucesso quando todos passam. Presença de arquivo não equivale a runtime.
5. Produzir entrega com versão, comandos, universo coberto, resultados e
   limitações. Atualizar o README mantendo a estrutura existente.

Aceite: instalação/restauração limpa em ambiente QA independente e todos os
gates verdes. Em seguida, **encerrar a versão MVP**. Melhorias opcionais vão
para backlog posterior, sem reabrir automaticamente a entrega.

## 7. Gates de conclusão

Todos são obrigatórios para o MVP. Cada gate exige evidência executada.

- **G-01 Ambiente:** comando único e duas inicializações idempotentes; build,
  corpus e porta correspondem aos artefatos atuais.
- **G-02 Integridade:** 20/20 fontes PDF verificadas por hash e abertas pela UI;
  zero alteração de revisão/aceitação/promoção de candidatos.
- **G-03 Descoberta:** encontrar as 20 por identidade exata sem parâmetro técnico;
  lei/edição e LO/LC distintas; navegação comum chega aos dispositivos.
- **G-04 Relações:** nos eventos suportados, ação/alvo/alcance coincidem com a
  cláusula e sua evidência. Todos os conflitos conhecidos preservados.
- **G-05 Comparação:** três cadeias usam o mesmo dossiê; ao menos uma alteração
  textual integral e uma revogação parcial, mais uma transição/datada quando
  documentalmente resolvida. Data desconhecida tem teste de abstenção temporal.
- **G-06 Grafo:** cada aresta abre evidência; mesmos IDs/eventos da comparação
  e exportação; lista equivalente funciona por teclado/mobile.
- **G-07 Assistente:** resposta direta, visão de norma e follow-up funcionam;
  parte não coberta é localizada; URLs vêm dos metadados e as citações resolvem.
- **G-08 Interação:** streaming/fontes antes do fim, cancelamento/retry,
  cópia com links e F5 preservando a associação; zero erro JS introduzido.
- **G-09 Avaliação técnica:** 28×3 resultados preservados; 100% das fontes
  esperadas são identificadas no inventário antes de avaliar; recall de fonte
  >=90% e de dispositivo >=85% no top 12 do braço de entrega. Os oito cenários
  negativos precisam passar suas asserções de não inventar alvo/data/totalidade;
  isso não exige recusar toda resposta útil. Os limiares são metas de engenharia
  propostas, não acurácia jurídica validada. Não alterar gabarito para atingi-los.
- **G-10 Espera e falha:** mostrar estado inicial em <=1 s; fontes em <=5 s p95
  em consultas exatas da amostra aquecida. Medir p50/p95 de resposta e TTFT local.
  Aos 60 s sem texto, oferecer modo documental/cancelamento; timeout configurável
  termina a operação com retry, sem spinner infinito. Se hardware não cumpre a
  geração LLM, modo documental continua entregando consulta/cotejo verificável.
- **G-11 Uso:** roteiro completo e doze perguntas novas em desktop/mobile,
  teclado, zoom 200% e reduced-motion; falhas críticas/altas corrigidas.
- **G-12 Reprodutibilidade:** restore QA independente e mesma revisão/hash;
  instruções completas e pacote de evidências; nenhuma dependência desta conversa.

Os gates de integridade, alvo, data, conflito e citação não admitem tolerância
estatística para casos conhecidos. Os limites de cobertura devem acompanhar
o relatório; casos não resolvidos continuam no denominador.

## 8. Roteiro de demonstração de dez minutos

1. Iniciar pelo comando M-01 e conferir build/corpus/serviços na tela de status.
2. Em Normas e acervo, pesquisar `258/2024` e abrir a ficha experimental.
3. Perguntar: “A LC 258/2024 revoga a LP 275/2009 inteira ou só parte dela?
   Mostre o dispositivo modificador e a fonte.” Ver Art. 21 como alcance parcial.
4. Abrir Grafo, selecionar a aresta e abrir o PDF no trecho. Mostrar os alvos
   não resolvidos da mesma cláusula como pendência, não nó confirmado.
5. Abrir o CTM na compilação de 2024, Art. 20, e comparar a redação transcrita
   na LC 271/2025, Art. 1º. Separar edição, publicação e efeitos tributários.
6. Abrir LC 208, Art. 18, § 2º, e LC 261, Art. 118. Mostrar texto e eventual
   pendência de data com a mesma fonte da ficha.
7. Consultar a regra de transição da LC 258 e pedir uma data fora da cobertura;
   o app explica o limite específico sem inventar vigência.
8. Mostrar a divergência da LC 55, Art. 34, no dossiê e no assistente.
9. Copiar uma resposta, verificar links, recarregar a conversa e exportar evidências.
10. Abrir o Gold de avaliação, conferir as 20 normas e explicar seu papel de
    gabarito interno. Ele não é o mecanismo que abastece respostas prontas.

Se um passo falhar, a demo ainda não passou. Não preparar screenshots de sucesso
como substitutas da funcionalidade que o usuário precisa demonstrar ao vivo.

## 9. Verificações e execução pelo Luna

Nesta rodada foram executados: leitura do código/planos, inventário Git,
Graphify AST, Context7 e validação estática Gold. Não foram executados chat,
OCR, migração, consolidação, restore ou usabilidade de runtime nesta data.
O app/dados precisam ser levantados e rechecados na M-01/M-02.

Comando já verificado para conferir o pacote Gold sem servidor:

```powershell
uv run --no-project --python 3.12 --with jsonschema python scripts/pgm_project_gold.py
```

O runner atual exige `JURIX_QA_ONLY=1` e `JURIX_QA_ROOT` sob a pasta temporária;
usar o root que contém os blobs do QA conferido, não presumir outro volume.
Depois de M-01/M-02, executar testes existentes pelo runner protegido e os
novos testes da tarefa. A suíte completa pertence ao gate final; não repetir
84 gerações depois de alteração de CSS ou documentação.

Prompt para iniciar a implementação:

```text
Implemente docs/research/JURIX_MVP_CLOSURE_PLAN_2026-10-27.md.
Use esforço alto. O objetivo é entregar e encerrar o MVP de pesquisa documental
e consolidação experimental descrito nesse arquivo. Comece na M-01 e avance
até a M-12, respeitando dependências e G-01–G-12. Preserve todo trabalho local.
Revalide o que já está pronto; não reimplemente funções que cumprem o aceite.
O corpus/adoções por IA são autorizados para este piloto; não aguarde procurador
para concluir software. Preserve autoria, conflitos e limites documentais.
Não use o gabarito para gerar as respostas nem promova candidatos a revisão humana.
Trabalhe em QA. Não faça commit, push, merge, troca de branch ou operações
destrutivas. Não altere planos ou o Gold v1. Registre decisões/evidências no
arquivo de entrega. Crie apenas testes ligados aos contratos alterados.
Execute as três cadeias e o roteiro completo pela UI; empacote e restaure em
QA independente. Ao passar todos os gates, encerre o MVP e entregue o resultado.
Se faltar dependência externa real, registre qual gate não pôde ser executado
e continue as tarefas independentes. Não declare gate verde com fixture ou
somente leitura de código quando ele exige PDF/servidor/navegador real.
```

Regra de parada: após M-12/G-01–G-12, não iniciar outro ciclo de melhoria por
conta própria. Pesquisa independente, novos lotes e produção pública pertencem
à próxima versão. Isso permite ao responsável declarar concluída sua entrega
de software, mantendo resultados científicos e validação institucional com
seus estados reais.
