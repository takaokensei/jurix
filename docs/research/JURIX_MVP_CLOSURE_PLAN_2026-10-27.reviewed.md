# Jurix — plano revisado de fechamento do MVP

Data: 27/10/2026. Destino: execução por GPT 6 Luna em esforço **alto**.
Checkout inspecionado: `L:\Jurix`, `main`, HEAD `1ac3ab75`, incluindo trabalho não commitado.
Status deste documento: **plano revisado após conferência de código e dados; implementação ainda não executada**.
Esta versão é a referência para a próxima implementação. O plano original de
27/10 foi preservado. As correções e evidências da revisão estão na seção 10.

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

**Nível de entrega:** produto local de pesquisa, com operação individual,
corpus delimitado e consolidação experimental rastreável. Um resultado de alta
qualidade nesse escopo é uma meta verificável; este documento não garante uma
nota futura nem equivale a homologação para decisões institucionais. Qualidade
será avaliada no aplicativo entregue, inclusive quando uma pergunta falha.

## 2. Escopo fechado

### Incluído na entrega

1. **Acervo geral:** busca e abertura dos documentos efetivamente disponíveis,
   com contadores de cobertura derivados do banco em uso.
2. **Coleção operacional de 20 normas:** todas descobríveis por tipo/número/ano,
   título quando comprovado e links dos dispositivos selecionados. O corpus
   operacional usa as extrações dos PDFs; o gabarito permanece na avaliação.
   São 20 documentos principais e três fontes auxiliares distintas no pacote
   atual: **23 PDFs**, dos quais **21 são exigidos pelas 28 perguntas**.
   Contar normas, edições, fontes e dispositivos separadamente.
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

A instalação deste MVP fica restrita a loopback, com documentos legislativos
públicos. Uso em rede, contas institucionais e processos sigilosos não estão
incluídos no aceite local. As proteções das superfícies alteradas continuam
obrigatórias, mesmo no piloto. Não publicar o perfil QA como configuração de produção.

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

### 5.0 Conferência de viabilidade antes da integração

M-02 deve produzir `readiness.json` com as 20 identidades, os 23 hashes, extrações
utilizáveis, dispositivos, referências auxiliares e as três cadeias propostas.
Para cada cadeia registrar: texto anterior, cláusula modificadora, alvo,
novo texto/alcance, evidência de publicação/efeito e o que continua desconhecido.
M-05 só inicia após essa conferência para a cadeia correspondente.

Exigir uma substituição textual integral recuperável, uma revogação parcial e
ao menos um efeito/transição com data e fundamento recuperados para o ensaio
temporal. O teste de data desconhecida é adicional, não substitui esse último.
Se faltar fonte, procurar o hash nos armazenamentos QA e, depois, na origem
oficial registrada. Registrar tentativas e falhas, sem iniciar OCR do acervo
inteiro. O gate permanece pendente até resolver a fonte ou obter mudança explícita
de escopo; continuar tarefas independentes sem fingir que o caso foi entregue.

### 5.1 Corpus operacional e gabarito

Criar uma **revisão imutável do corpus piloto**, em armazenamento QA, derivada
de `DocumentoNormativo`/`ExtracaoDocumento` e das adoções IA autorizadas.
Pode ser um manifesto JSON versionado e seus sidecars: não é necessário criar
outro conjunto de tabelas para entregar a primeira versão.

Reutilizar os contratos de `build_pilot_manifest.py`, `normative_casefile.py` e
`normative_projection.py`. Os arquivos `pilot_*` são adaptadores pequenos com
contratos próprios, não uma segunda aplicação. Não duplicar parser de referência,
resolvedor de fonte, renderer ou algoritmo temporal já coberto por testes.

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

Calcular `corpus_revision` sobre JSON canônico ordenado e hashes dos conteúdos,
incluindo versão do schema/extrator/regras. Excluir hora de execução, caminho
absoluto e PK local; registrar esses dados somente no relatório operacional.
Publicar arquivos completos em diretório de revisão imutável e ativar a revisão
por referência atômica apenas após validação. Transação SQL não reverte escrita
de arquivos: falha antes da ativação conserva a revisão anterior. Havendo SQL,
invalidar cache/enfileirar somente após commit; tornar repetição e concorrência
idempotentes. Nunca truncar o manifesto ativo durante uma requisição.

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
9. Diferenciar data de publicação, início de vigência e início de efeitos.
   Um único `effective_on` não responde indistintamente às três perguntas.
   Usar datas civis e intervalos `[início, fim)` quando resolvidos; desconhecido
   permanece `null`, sem fallback para data da sessão/arquivo/ingestão.
10. A base compilada tem fronteira temporal própria. Não reaplicar alteração
    já incorporada àquela edição; dúvida sobre incorporação gera pendência.
    Revogar uma lei revogadora não restaura automaticamente o texto anterior.
    Alteração/revogação de artigo trata descendentes explicitamente, sem duplicar
    texto de parágrafos ou apagar dispositivos vizinhos.
11. O adaptador não pode chamar `ConsolidationEngine.consolidate()` como motor
    temporal sem revisão: seu ordenamento legado usa publicação/número/PK.
    Reutilizar apenas operações puras comprovadas. O caminho experimental usa
    efeitos documentados e mantém empates materiais como conflito, sem tie-break por PK.

### 5.4 Um dossiê para todas as superfícies

O mesmo resultado terá `casefile_id`, `corpus_revision`, `as_of`, `basis`,
`coverage`, `devices`, `events`, `sources` e `conflicts`.
`basis` distingue `reviewed`, `ai_pilot` e `documentary_candidate`.
Chat, comparação, grafo e exportação devem consumir esse resultado, sem quatro
interpretações independentes da mesma cláusula.

Cada mensagem fixa `corpus_revision` e `casefile_id`. Cache deve incluir revisão,
identidade, escopo/data, versão de prompt/modelo quando aplicável e isolamento
da sessão. Mudança do corpus não altera silenciosamente resposta antiga: mostrar
que há versão mais recente e oferecer nova consulta. PDFs/citações exportados
resolvem por hash; links portáveis são reconstruídos no destino, sem eternizar
`localhost:8294` ou UUID de um banco antigo. Não carregar todos os PDFs por request.

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

Afirmações materiais (texto, ação, alvo, alcance, data e conflito) devem sair do
dossiê estruturado. A síntese não pode converter `partial`/`unknown_date` em
vigência confirmada. Na avaliação, verificar se cada afirmação é sustentada pelo
trecho, além de conferir que o hyperlink existe. Evidência ausente é uma pendência
localizada, não uma resposta inventada nem recusa indiscriminada.

### 5.6 Confiabilidade, segurança e acabamento do percurso

- Documentos e respostas do modelo são dados não confiáveis. Preservar sanitização
  Markdown/HTML e políticas de URLs; o LLM não recebe permissão para escrever no
  banco, chamar ferramentas ou mudar eventos. Não baixar URL produzida pelo modelo.
- Reusar controle de acesso dos PDFs, conversas e exportações. Testar outra sessão,
  CSRF, caminhos fora do armazenamento, esquema `javascript:` e instruções maliciosas
  dentro de evidência. Nenhum segredo, prompt completo ou dado de conversa em logs públicos.
- Cancelar/timeout encerra ou limita a requisição upstream; retry não duplica
  mensagem/tarefa. Duas abas concorrentes não misturam fontes, tokens ou sessões.
- Interface pronta inclui estados vazio, carregando, parcial, erro e sucesso;
  foco visível, restauração de foco de modal, leitura e ações sem hover obrigatório.
  A mensagem principal domina; metadados técnicos ficam recolhidos; fonte abre
  com trecho/página e fallback PDF se não for possível realçar o texto.
- Nos percursos centrais, medir contraste, alvos, teclado e reflow; usar tokens
  existentes de claro/escuro. Não trocar framework nem redesenhar todas as telas.

Referências verificadas: [Django — deployment](https://docs.djangoproject.com/en/5.2/howto/deployment/checklist/),
[Django — transações](https://docs.djangoproject.com/en/5.2/topics/db/transactions/),
[OWASP — prompt injection](https://genai.owasp.org/llmrisk/llm01-prompt-injection/),
[WCAG 2.2](https://www.w3.org/TR/WCAG22/) e
[Apple HIG — acessibilidade](https://developer.apple.com/design/human-interface-guidelines/accessibility).
São princípios de implementação e teste, não certificações obtidas nesta revisão.

## 6. Sequência finita de tarefas

Cada M-## representa uma mudança coerente e revisável. Preservar o trabalho
existente e executar primeiro uma regressão relevante; só alterar aquilo que
falhar ou faltar. Nenhum commit/push/merge/switch é autorizado por este plano.
Comandos novos citados abaixo são **interfaces a implementar**, não comandos já
disponíveis. As suítes e scripts existentes são indicados por caminho real.

M-01–M-12 são pacotes de entrega; não precisam caber em uma edição enorme. Dentro
de cada pacote seguir contratos/testes → implementação → interação real, registrando
subetapas e diff. Arquivos fora da lista só podem ser ampliados com justificativa
de dependência concreta; não reescrever módulos inteiros por conveniência.
Antes/depois de cada pacote executar seus testes; manter um mapa
`gate → cenário → comando → evidência → resultado`. A reversão local deve repor
somente o delta desta implementação, preservando alterações anteriores e dados;
não usar reset, clean ou revert de commits que incluam trabalho alheio.
Em M-04, M-07 e M-09, executar imediatamente um fluxo de navegador da mudança;
M-11 consolida o aceite, não é a primeira vez que a interface será usada.

### M-01 — inicialização e identidade únicas

Pré-requisito: nenhum. Cobre R-08.

Arquivos: `docker-compose.audit.yml`, `scripts/start_pgm_mvp.ps1` (novo),
`scripts/status_pgm_mvp.ps1` (novo), `src/apps/core/build_identity.py`,
`src/tests/test_audit_stack_config.py`, `src/tests/test_build_identity.py`,
`src/tests/test_normative_qa_guard.py`.

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
7. Gravar recursos QA identificáveis e inventário de origem/destino; não escolher
   um volume vazio como substituto do acervo atual. Identificar executável Python,
   versão Ollama, modelo/tag/digest e orçamento de contexto. Nenhuma alteração
   silenciosa de modelo para obter melhor benchmark.
8. Evitar hash de blobs, `.env`, caches e logs no digest de build; incluir código,
   templates e assets não rastreados relevantes. Verificar bind somente em loopback.

Aceite: duas execuções seguidas mantêm o mesmo URL/build; instância velha é
detectada; nenhum processo preexistente é encerrado. Verificar os testes de
build/Compose e a inicialização real duas vezes. Não executar migrations
novas automaticamente sem mostrar seu plano; se forem necessárias, apenas aditivas no QA.

### M-02 — materializar 20 normas e seu inventário de fontes

Pré-requisito: M-01. Cobre R-01/R-06/R-07.

Arquivos: `src/processing/pilot_corpus.py` (novo),
`src/apps/ingestion/management/commands/build_pgm_pilot_qa.py` (novo),
`benchmarks/corpus/municipal_natal/pilot-source-selection.v1.json` (novo),
`src/tests/test_pilot_corpus.py` (novo), `scripts/normative_qa.py`,
`src/tests/test_normative_qa_guard.py`.

1. Resolver por hash os 20 PDFs principais e três auxiliares registrados em
   `reference/supporting-evidence.jsonl`: inventário atual de 23 PDFs únicos.
   Conferir em processo de validação, separado do produto, que as 21 fontes
   exigidas pelas consultas congeladas estão nesse inventário. A fonte adicional
   usada pelas consultas é `aux:F10`; não omitir a compilação auxiliar da LC 55.
   Copiar um blob de outro volume QA apenas após verificar origem/hash; preservar a origem.
2. Reutilizar extrações existentes compatíveis; extrair apenas fontes ausentes,
   em lotes limitados e retomáveis, guardando página/offset.
3. Produzir manifesto com universo/processados/falhas e revisão por conteúdo;
   recusar sobrescrever outra revisão.
4. Disponibilizar as 20 identidades e os dispositivos selecionados, mantendo
   explicitamente a diferença entre edição, ato original e compilação.
5. Adicionar o comando ao runner QA com flags e diretório de saída restritos.
6. Gerar `readiness.json` conforme 5.0, mapa de fonte→norma/edição/dispositivo e
   offsets verificáveis contra a extração. Documento com vários atos precisa
   de limites de ato/páginas; não atribuir todo o PDF à lei de seu primeiro título.
7. Testar geração concorrente, interrupção antes da ativação, revisão anterior
   preservada e resolução após restore com novos PKs. A busca usa índice/manifesto
   carregado por revisão; não refaz extração nem embedding por pergunta exata.

Aceite: 23/23 PDFs abrem, 20/20 normas têm os dispositivos selecionados
pesquisáveis e 21/21 fontes requeridas pelas consultas são resolvíveis; repetição não
duplica registros. Estado jurídico, extração aceita e vínculos de produto
ficam iguais antes/depois. Testar blob ausente, hash divergente e colisão LO/LC.
Falha de uma fonte não fica escondida em média: M-02 não passa com item ausente.

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
`src/tests/test_workspace_routes.py`, `src/apps/legislation/workspace_urls.py`,
`src/apps/core/static/css/workspace.css`.

1. Ler o manifesto piloto no catálogo comum, sem converter todos os candidatos
   em `Norma.status=consolidated`.
2. Exibir os 20 como normas disponíveis para consulta experimental; agrupar
   dispositivos/edições sob a identidade normativa.
3. Preservar os documentos gerais e seus filtros; separar contagens de norma,
   PDF, dispositivo coberto e revisão.
4. Manter um link secundário para o Gold e eliminar o estado vazio global
   quando há conteúdo experimental consultável.
5. Paginar o acervo geral, preservar filtros no URL e na navegação voltar/avançar;
   diferenciar sem resultado, corpus vazio e serviço indisponível. Índices/consultas
   não podem produzir uma consulta SQL extra para cada card. Testar contagem de
   queries em 1 e 20 cards e explicar qualquer aumento.

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
6. Exigir evidência do novo texto e da delimitação do alvo; manter menção,
   alteração, revogação e regulamentação distintas. Importar adoção IA somente
   se seu fingerprint ainda corresponde aos textos e documentos escolhidos.

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
6. Cobrir os invariantes 5.3.9–11: base compilada sem duplo efeito, intervalos,
   vigência distinta de efeitos, descendentes, vetos, revogação da revogadora,
   empate material e aplicação idempotente. Fixtures pequenas são permitidas
   nesses testes algorítmicos; os três casos reais continuam obrigatórios.

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
`tests/js/normative-casefile-tabs.test.mjs`,
`src/apps/core/static/css/jurix-casefile.css`,
`src/apps/core/static/css/jurix-legal-detail.css`.

1. Implementar um adaptador de dossiê experimental com o contrato da seção 5.4.
2. Abrir a ficha por identidade/edição, sem depender de UUID histórico hardcoded.
3. Abas: “Texto e comparação”, “Alterações”, “Grafo”, “Fontes”.
4. Usar os mesmos eventos no grafo, nos estados dos dispositivos e na exportação.
5. Grafo navegável com alcance parcial/total e conflitos visíveis; equivalente
   em lista para teclado e telas pequenas.
6. A demo passa a selecionar casos do percurso comum. A view não incorpora
   novas regras específicas de CTM ou LC 258.
7. Comparação mostra o artigo e contexto necessário; removido/substituído tem
   rótulo textual além de cor/risco. Seleção no grafo destaca a mesma evidência
   na lista, sem resetar zoom ou filtro. No mobile, lista/comparação continua
   utilizável mesmo se o desenho precisar de pan/zoom. Evitar grafo como enfeite.

Aceite: as três cadeias abrem pelo mesmo componente/serviço; comparar, abrir
aresta, seguir fonte e exportar preservam `casefile_id` e `corpus_revision`.
Nenhum link retorna ao visitante uma ficha sem permissão; fonte pública segue
seu caminho oficial ou o endpoint QA já autorizado.

### M-08 — assistente consome o mesmo corpus e dossiê

Pré-requisitos: M-03/M-07. Cobre R-01/R-02/R-04/R-05.

Arquivos: `src/processing/pilot_rag.py` (novo),
`src/processing/qa_archive_rag.py`, `src/processing/adaptive_rag_service.py`,
`src/apps/legislation/api_search.py`, `src/apps/legislation/serializers.py`,
`src/processing/rag_prompt.py`, `src/tests/test_pilot_rag.py` (novo).

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
6. Separar limite de recuperação do orçamento de contexto do LLM. Visão de norma
   pequena cobre todos os dispositivos selecionados relevantes; norma grande
   informa cobertura e dispõe do restante na ficha. Medir o que foi recuperado,
   o que entrou no contexto e o que foi efetivamente citado. Não truncar uma
   cláusula operativa para caber no prompt nem chamar amostra de leitura integral.
7. Sessão e cada mensagem mantêm a revisão usada. Invalidar cache por revisão
   e testar duas conversas com leis diferentes, inclusive pergunta “e o art. 7?”.

Aceite: “O que mudou?”, “E o artigo anterior?” e “isso revogou a lei inteira?”
mantêm a identidade da conversa. Uma pergunta da mesma cadeia obtém os mesmos
alvos/datas da ficha; nenhuma resposta infere vigência além da cobertura.

### M-09 — streaming, fontes, cópia e estados

Pré-requisito: M-08. Cobre R-03/R-05.

Arquivos: `src/apps/core/static/js/jurix-rag.js`,
`src/apps/core/static/css/jurix-rag.css`,
`src/apps/legislation/templates/legislation/chatbot.html`,
`src/apps/legislation/chat_api_helpers.py`,
`tests/js/streaming.behavior.test.mjs`, `src/tests/test_serializers.py`,
`src/processing/pilot_rag.py`, `src/apps/legislation/api_search.py`,
`src/processing/llm_provider.py`, `src/tests/test_pilot_rag.py`,
`src/tests/test_llm_provider.py`, `tests/js/chat.security.test.mjs`.

1. Disponibilizar fontes ao receber `sources`, mesmo com geração em andamento.
   Reservar espaço e usar transição discreta; respeitar reduced-motion.
2. Resolver citações da resposta parcial; `done` consolida o estado sem
   recriar desnecessariamente a mensagem inteira.
3. Copiar Markdown com links produzidos a partir dos mesmos metadados.
4. Persistir evidências/corpus da conversa; cancelar/interromper não deixa
   resposta em estado final falsamente concluído.
5. Testar envio, falha do modelo, interrupção, retry, F5, voltar/avançar e fontes
   por teclado. Não esconder conclusão insuficiente com animação.
6. Contrato de eventos usa request/message ID e sequência. `done`, erro e cancelado
   são terminais mutuamente exclusivos; tokens tardios de requisição anterior
   são descartados. Retry tem chave idempotente. Ao cancelar, liberar leitura
   HTTP/recursos upstream quando suportado e manter timeout máximo se não for.
7. PDFs/fontes já recuperados continuam navegáveis com modelo parado. Reinício
   web/worker não duplica uma conversa salva nem apaga suas referências. Testar
   retorno fora de ordem em duas abas e queda após `sources`, antes de `done`.

Aceite: fonte abre antes do `done`; cópia mantém URLs; F5 mantém as citações;
botões acessíveis em 360/768/1280/1920 px e zoom 200%; zero erro JS introduzido.

### M-10 — medir o corpus certo e conferir negativos

Pré-requisitos: M-08/M-09. Cobre R-07.

Arquivos: `scripts/collect_normative_rag_experiment.py`,
`scripts/evaluate_pgm_project_gold.py`,
`scripts/evaluate_pgm_project_gold_archive.py`, `scripts/normative_qa.py`,
`src/tests/test_normative_rag_experiment_collection.py`,
`src/tests/test_pgm_project_gold_archive.py`,
`benchmarks/corpus/municipal_natal/pilot-regression.v1.jsonl` (novo).

1. Coletor recebe explicitamente a revisão do corpus piloto. Baseline, grafo e
   grafo temporal usam as mesmas fontes elegíveis, modelo e orçamento.
   Baseline usa recuperação textual; grafo acrescenta vizinhos documentados;
   grafo temporal acrescenta seleção/projeção na data. Registrar regras de cada
   braço antes de medir. Não entregar o resultado da projeção ao baseline.
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
7. Parametrizar métricas em k=5 e k=12 sem renomear arbitrariamente resultado
   existente. Recall é micro: soma de pares (consulta, fonte/dispositivo)
   recuperados / soma de pares esperados. Reportar também resultado por consulta,
   casos com cobertura parcial e precision dos itens que têm rótulo conhecido.
8. Separar hashes de PDF, extração completa, recorte e projeção. Hoje
   `expected_versions` usa digest do recorte Gold; não comparar esse valor
   diretamente com digest da extração/projeção inteira. O avaliador mapeia spans
   por fonte+dispositivo+texto/offset e identifica métricas não comparáveis.
   Nunca copiar o hash esperado para uma predição sem conferir o conteúdo.
9. Para cada resposta dos 28 casos, registrar afirmações materiais e evidência
   que as sustenta: texto, ação, alvo, alcance e datas. Usar asserções objetivas
   para fatos estruturados e registrar explicitamente inspeção por IA da prosa.
   LLM juiz pode sinalizar, mas não substitui esses registros nem vira revisão
   independente. Conferir cobertura no contexto e na resposta, além de recall.
10. No braço de entrega, executar as 12 novas perguntas em duas passagens
    (24 resultados) e exigir fatos estruturados consistentes. As quatro perguntas
    temáticas não citam número de lei nem palavra-chave escolhida da resposta;
    representam tarefas de licenciamento, tributo ou planejamento sustentadas
    pela coleção. Seguimentos referenciam a conversa, não repetem toda a pergunta.

Aceite: cumprir G-09 da seção 7 e gerar relatório imutável. Tuning após olhar
resultados é desenvolvimento; uma rodada posterior não vira teste independente.

### M-11 — demonstração reproduzível e usabilidade real da aplicação

Pré-requisito: M-10. Cobre R-01/R-03/R-05/R-08.

Arquivos: `tests/js/pgm-mvp-acceptance.mjs` (novo),
`tests/js/pgm-workflow-smoke.mjs`, `scripts/normative_qa.py`,
`docs/research/JURIX_MVP_DEMO.md` (novo),
`src/apps/core/static/css/workspace.css`, `src/apps/core/static/css/jurix-rag.css`,
`src/apps/core/static/css/jurix-casefile.css`,
`src/apps/core/static/js/jurix-normative-casefile.js`,
`src/apps/legislation/templates/legislation/workspace/normative_casefile.html`,
`src/apps/legislation/templates/legislation/chatbot.html`.

1. Automatizar o roteiro da seção 8 em navegador com PDFs reais QA.
2. Verificar build/corpus antes de interagir e nomes acessíveis nos controles.
3. Executar desktop e mobile; testar teclado e uma rodada de zoom nativo 200%.
4. Registrar screenshots sem dados pessoais e logs de falhas no root QA.
5. Demonstrar três cadeias e um conflito, inclusive uma pergunta sem resposta
   resolvida. A demo não pode depender de chat pré-preenchido ou de porta antiga.
6. Executar a matriz G-11 nas telas de catálogo, chat, dossiê, modal de fontes e
   exportação. Registrar problema, correção pontual e repetição do cenário; não
   iniciar redesenho geral. A existência de screenshot não comprova interação.
7. Congelar 30 operações de uso contínuo (buscar, navegar, perguntar, cancelar,
   copiar, exportar) em duas sessões/abas. Nenhuma falha de servidor não tratada,
   vazamento entre sessões, perda de referência ou loading sem saída é aceitável.

Aceite: todo roteiro passa partindo de Nova pesquisa e de um navegador limpo.
Esse ensaio é de engenharia/usabilidade da aplicação, sem atribuir participação
de procuradores a interações do agente.

### M-12 — empacotar, restaurar e encerrar

Pré-requisitos: M-01–M-11. Cobre R-08 e fechamento da entrega.

Arquivos: `scripts/verify_pgm_mvp_release.py` (novo),
`scripts/export_pgm_pilot_qa.py` (novo),
`scripts/restore_pgm_pilot_qa.py` (novo),
`docs/research/JURIX_MVP_DELIVERY.md` (novo), `README.md`,
`docs/current-status.md`, `CONTRIBUTING.md`,
`config/settings_normative_qa.py`, `config/settings_normative_container_qa.py`,
`scripts/normative_qa.py`, `src/tests/test_normative_qa_guard.py`,
`src/tests/test_api_security.py`, `src/tests/test_normative_document_access.py`,
`src/tests/test_security_headers.py`, `tests/js/chat.security.test.mjs`,
`scripts/validate_release_contract.py`.

1. Empacotar revisão do corpus/sidecars e apontar como obter PDFs de fonte
   pública ou fornecer bundle local. Separar código e dados; conferir condições
   de redistribuição de cada origem antes de publicar PDFs.
2. Restaurar em banco/armazenamento QA descartáveis com nome único, verificar
   hashes, mesmas três cadeias e mesmos resultados determinísticos. Preservar QA principal.
   Os settings atuais aceitam `jurix_audit` ou `jurix_migtest_<dígitos>`. Implementar
   explicitamente namespace `jurix_mvprestore_<dígitos>` para restore, com root
   isolado e conta QA, ou usar instância inteiramente separada com contrato
   igualmente restrito. O restore deve recusar QA principal, diretório não vazio,
   path traversal e colisão; nunca ampliar a allowlist para qualquer banco/host.
3. Executar a suíte relevante Python/JS e os checks de instalação. Documentar
   falhas de baseline sem ignorar regressões do trabalho novo.
4. O verifier emite G-01–G-12 com evidência e `pass/fail/not_run`; só retorna
   sucesso quando todos passam. Presença de arquivo não equivale a runtime.
5. Produzir entrega com versão, comandos, universo coberto, resultados e
   limitações. Atualizar o README mantendo a estrutura existente.
6. Rodar testes de segurança das superfícies tocadas e `check --deploy` no perfil
   apropriado, classificando exceções de localhost sem declarar produção aprovada.
   Conferir dependências efetivas, lock e vulnerabilidades conhecidas; achado
   crítico/alto alcançável nesses fluxos bloqueia entrega. Scanner indisponível
   é verificação não executada, não resultado limpo. Não atualizar stack sem vínculo
   com falha; preservar isolamento QA/produção e segredos fora do pacote.
7. Instalação/restore deve usar caminhos relativos e dependências declaradas
   (Python/Node/Docker/modelo, hashes e licenças), sem `.venv` copiado, caches ou
   caminho do computador original. Incluir checks reproduzíveis para PR/CI;
   inferência local pesada fica no teste de aceitação com modelo identificado.
8. Medir duas inicializações completas, restore em root novo e G-10/G-11 no
   destino. A nota final apresenta dimensões e evidências; não converter número
   de tarefas concluídas em percentual de maturidade jurídica ou qualidade.

Aceite: instalação/restauração limpa em ambiente QA independente e todos os
gates verdes. Em seguida, **encerrar a versão MVP**. Melhorias opcionais vão
para backlog posterior, sem reabrir automaticamente a entrega.

## 7. Gates de conclusão

Todos são obrigatórios para o MVP. Cada gate exige evidência executada.

- **G-01 Ambiente:** comando único e duas inicializações idempotentes; build,
  corpus e porta correspondem aos artefatos atuais.
- **G-02 Integridade:** 20 normas e inventário atual de 23 PDFs verificados por
  hash/abertura; 21 fontes exigidas pelas consultas presentes e legíveis no escopo.
  Readiness das três cadeias registrado; offsets/extratos resolvem na fonte.
  Zero alteração de revisão/aceitação/promoção de candidatos; publicação do
  manifesto interrompida não invalida a revisão ativa.
- **G-03 Descoberta:** encontrar as 20 por identidade exata sem parâmetro técnico;
  lei/edição e LO/LC distintas; navegação comum chega aos dispositivos.
- **G-04 Relações:** nos eventos suportados, ação/alvo/alcance coincidem com a
  cláusula e sua evidência. Todos os conflitos conhecidos preservados.
- **G-05 Comparação:** três cadeias usam o mesmo dossiê; ao menos uma alteração
  textual integral e uma revogação parcial, mais um efeito/transição com data e
  fundamento documental recuperados, testado em D−1/D/D+1. Data desconhecida tem
  teste adicional de abstenção temporal; não substitui o caso datado. Os invariantes
  temporais 5.3 passam sem inventar base anterior à edição nem reaplicar evento.
- **G-06 Grafo:** cada aresta abre evidência; mesmos IDs/eventos da comparação
  e exportação; lista equivalente funciona por teclado/mobile.
- **G-07 Assistente:** resposta direta, visão de norma e follow-up funcionam;
  parte não coberta é localizada; URLs vêm dos metadados e as citações resolvem.
  Consulta temática sem número encontra conteúdo pertinente; 12 perguntas novas
  em duas passagens preservam fatos estruturados e contexto. Modelo real gera
  respostas no perfil anunciado; fallback documental é testado como contingência.
- **G-08 Interação:** streaming/fontes antes do fim, cancelamento/retry,
  cópia com links e F5 preservando a associação; zero erro JS introduzido.
  Cancelamento termina a operação visível em até 1 s e leitura upstream tem
  encerramento/limite demonstrado. Resposta parcial não ganha estado concluído;
  duas abas e tokens tardios não misturam mensagens/revisões/sessões.
- **G-09 Avaliação técnica:** 28×3 resultados preservados; 100% das fontes
  esperadas são identificadas no inventário antes de avaliar; recall de fonte
  >=90% e de dispositivo >=85% no top 12 do braço de entrega. Os oito cenários
  negativos precisam passar suas asserções de não inventar alvo/data/totalidade;
  isso não exige recusar toda resposta útil. Os limiares são metas de engenharia
  propostas, não acurácia jurídica validada. Não alterar gabarito para atingi-los.
  As quatro novas negativas também passam. Toda citação emitida resolve uma
  evidência válida; zero ação/alvo/alcance/data material contraditórios aos fatos
  comprovados nos casos de aceite. Auditar afirmações e registrar fonte/trecho,
  incluindo resultado parcial. Expor métricas de contexto, resposta e falhas;
  recall isolado não aprova este gate. Julgamento da prosa por IA é identificado.
- **G-10 Espera e falha:** mostrar estado inicial em <=1 s; fontes em <=5 s p95
  em consultas exatas da amostra aquecida. Na amostra de 12 novas consultas ×2,
  meta de TTFT <=15 s p95 e conclusão <=90 s p95 com modelo carregado; registrar
  p50/p95, CPU/GPU/RAM, modelo, contexto, tamanhos e falhas, separando execução fria.
  Aos 60 s sem texto, oferecer modo documental/cancelamento; timeout configurável
  termina a operação com retry, sem spinner infinito. Valores são metas propostas,
  não medições atuais. Se o hardware/modelo não atende, avaliar configuração menor
  e repetir qualidade; o modo documental não torna o aceite do assistente verde
  sozinho. Uma edição apenas documental exige declaração/mudança de escopo explícita.
- **G-11 Uso:** roteiro completo e doze perguntas novas em desktop/mobile,
  teclado, zoom 200% e reduced-motion; falhas críticas/altas corrigidas. Matriz
  nas cinco superfícies de M-11: 320/360/768/1280/1920 px, claro/escuro, contraste
  de texto >=4,5:1 (>=3:1 para texto grande) e UI >=3:1; tamanho mínimo de alvo
  24 CSS px ou exceção justificada WCAG 2.5.8, alvo de projeto 44 px para controles
  primários de toque. Sem scroll horizontal da página em 320 px; grafo/tabela
  pode ter região própria e alternativa textual. Modais/abas/fonte operáveis por
  teclado, foco visível e não encoberto pelo compositor, nomes acessíveis e erro
  associado ao campo. As 30 operações contínuas terminam sem perda/mistura de dados.
- **G-12 Reprodutibilidade:** restore QA independente e mesma revisão/hash;
  instruções completas e pacote de evidências; nenhuma dependência desta conversa.
  Testes de acesso/CSRF/XSS/traversal/injeção documental passam; dependências e
  checks de configuração verificados com exceções locais explícitas. Pacote sem
  segredos nem conversas pessoais. Nenhum defeito crítico/alto aberto no percurso
  entregue; falha já existente que afeta o MVP também bloqueia, não só regressão.

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
Na revisão do plano, também foram conferidos inventário de fontes, caminhos reais,
semântica dos hashes, guards do restore e referências oficiais. Isso não substitui
o ensaio do produto. A seção 10 registra os achados que motivaram esta versão.

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
Implemente docs/research/JURIX_MVP_CLOSURE_PLAN_2026-10-27.reviewed.md.
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

## 10. Resultado da revisão crítica de 27/10/2026

**Parecer:** a direção arquitetural e o recorte são apropriados para um MVP local
forte, mas o plano original precisava das correções abaixo. Cumprir esta versão
produz evidência de qualidade dentro do escopo; não permite prometer antecipadamente
um produto 9/10, precisão jurídica universal ou aceitação por procuradores.
O valor da entrega está em tarefas reais resolvidas com fonte, estado e limites
corretos, não em páginas de documentação ou quantidade de testes isolados.

### RV-01 — inventário subestimado (alto)

O plano original M-02/G-02 dizia 20 PDFs. A leitura de
`benchmarks/corpus/municipal_natal/ai-adjudicated-20261018-v1/reference/manifest.jsonl`
retorna 20 documentos principais; `supporting-evidence.jsonl` tem três hashes
auxiliares distintos. A união de `expected_source_ids` de `queries.ai.jsonl`
contém 21 hashes; a fonte adicional exigida é `aux:F10`, da compilação da LC 55,
hash `795c884ea3184e73da6368dfb8647f695f2e53ba1941756f45c09a4eaffbca24`.
Correção: M-02/G-02 distinguem 20 normas, 23 arquivos e 21 fontes consultadas pelo
benchmark. Verificado por leitura/contagem, sem reabrir PDFs nesta rodada.

### RV-02 — caminho de geração inexistente (médio)

`src/llm_engine/prompts.py`, citado em M-08 original, não existe.
`src/processing/qa_archive_rag.py:45` importa `build_prompt` de
`src/processing/rag_prompt.py`. Corrigido M-08; não criar um segundo prompt só
para satisfazer o caminho errado. Verificado por busca de arquivos e import.

### RV-03 — restore proposto incompatível com os guards (alto)

`config/settings_normative_qa.py` e `config/settings_normative_container_qa.py`
aceitam `jurix_audit` e namespace `jurix_migtest_<dígitos>`, não banco arbitrário.
M-12 prometia restore em nome único sem listar os settings/runner como dependência.
Correção: namespace restrito e testes negativos explícitos, preservando banco e
root principais. Verificado por leitura; restore continua não executado.

### RV-04 — métricas/identidades de versão incompatíveis (alto)

`scripts/evaluate_pgm_project_gold.py:44` corta fontes em cinco; o aceite original
usa top 12. O mesmo avaliador compara versões exatamente. Em
`scripts/build_pgm_ai_adjudicated.py:375`, versões esperadas são hashes de textos
selecionados, enquanto `scripts/collect_normative_rag_experiment.py:447–450`
usa `temporal_version.version_hash`. São domínios de identidade diferentes e
precisam de mapeamento comprovado, não igualdade presumida.
Correção: M-10 mede k explicitamente, separa identidades, não fabrica hash nem
usa Gold na geração. O resultado anterior não foi recalculado nesta revisão.

### RV-05 — recuperar fonte não comprova resposta correta (alto)

G-09 original exige recall e negativos, mas não verifica suficientemente a
associação afirmação→trecho nem cobertura da resposta. Não basta encontrar PDF
correto e emitir qualquer interpretação acompanhada de link.
Correção: M-08/M-10 e G-07/G-09 incluem fatos estruturados, inspeção declarada da
prosa, perguntas temáticas e repetição; a checagem por IA não é chamada independente.
É lacuna do critério original, não resultado de um teste de respostas nesta rodada.

### RV-06 — demonstração temporal poderia passar sem caso temporal (alto)

G-05 original condicionava o caso datado à disponibilidade, permitindo substituir
toda reconstrução na data por abstenção. M-02 agora exige readiness; G-05 exige
um efeito/transição datado real, além do caso desconhecido.
`src/processing/consolidation_engine.py:115` também tem ordenamento legado por
publicação/número/PK. A reutilização deve preservar o algoritmo temporal da
projeção, não adotar esse ordenamento inadvertidamente. Nenhuma data nova foi
declarada comprovada nesta revisão.

### RV-07 — estado versionado precisava de contrato operacional (alto)

O manifesto original incluía data de captura sem definir participação no digest,
ativação atômica, concorrência e cache por revisão. Isso deixa margem para revisão
nova em toda execução, leitura parcial ou resposta cacheada com corpus antigo.
Correção: 5.1/5.4, M-02/M-08/M-09 e G-02/G-08; falha deixa versão anterior íntegra.
São riscos identificados no desenho, não incidentes observados em runtime.

### RV-08 — segurança e acabamento insuficientes para a meta de qualidade (alto)

Os gates originais não exigiam explicitamente testes de autorização/CSRF/XSS,
injeção documental, contraste, reflow 320 px, duas abas, reinício e cancelamento
upstream. Existem testes reutilizáveis, por exemplo `test_api_security.py`,
`test_normative_document_access.py` e `tests/js/chat.security.test.mjs`.
Correção: 5.6, M-09/M-11/M-12 e G-08/G-10/G-11/G-12. Revisão documental baseada
nas fontes oficiais da seção 5.6; nenhuma certificação WCAG ou auditoria de
segurança concluída é alegada.

### RV-09 — qualidade do assistente não pode ser substituída por fallback (alto)

G-10 original permitiria cumprir parte da experiência com modo documental mesmo
sem desempenho utilizável do modelo. Isso pode entregar um leitor de documentos
quando foi prometido assistente conversacional.
Correção: amostra, hardware, modelo, TTFT e latência final explícitos; fallback
preserva utilidade na falha, mas não aprova sozinho o assistente anunciado.

### Verificações desta revisão e limites

- Validador Gold executado: válido; 20 normas, 41 recortes, 13 eventos,
  28 consultas, 37 arquivos conferidos. Zero PDFs/textos originais revalidados
  nesta execução; não confundir integridade do pacote com conteúdo conferido.
- Inventário de hashes contado diretamente: 20 principais, três auxiliares,
  23 na união, 21 nas consultas; oito casos negativos congelados.
- Caminhos e imports comparados; infraestrutura de restore, métricas e motor
  lidos. As tarefas novas permanecem marcadas como novas.
- Documentação oficial consultada: Django 5.2, WCAG 2.2, OWASP LLM01 e Apple HIG.
  A página HIG foi lida pela versão Markdown oficial após a versão HTML exigir JS.
- Probe nesta revisão: Ollama `11434` com listener; web `8294`, PostgreSQL QA
  `55432` e Redis `16380` sem listener. Não houve teste de inferência/UI, startup,
  migração, alteração de dados, commit ou push.
- Validação de contrato de documentação e `git diff --check` executadas; hashes
  dos arquivos preexistentes conferidos ao final no registro de evidência abaixo.

Registro reproduzível da revisão:
[`evidence/mvp-closure-review-20261027.json`](evidence/mvp-closure-review-20261027.json).

Para a entrega final, avaliar separadamente: (1) tarefas do usuário, (2) evidência
e correção documental, (3) estabilidade/latência, (4) UI/acessibilidade e
(5) instalação/segurança/reprodução. Nenhuma média compensa defeito crítico/alto
em qualquer dimensão. Só atribuir nota após executar os gates; hoje o parecer
é sobre a qualidade e viabilidade do plano revisado, não sobre produto pronto.
