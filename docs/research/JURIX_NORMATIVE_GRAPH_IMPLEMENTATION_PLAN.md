# Jurix — acervo histórico, grafo normativo e RAG temporal

Plano de implementação para GPT 6 Luna, esforço **alto**.

Data: 02/10/2026. Fonte de verdade: checkout local `C:\Jurix`.
Baseline inspecionado: branch `main`, commit `0426e53`.

Este arquivo especifica trabalho futuro. Sua criação **não executa nem autoriza automaticamente** importação no banco real, migrations no ambiente real, publicação, commit, push ou merge. A implementação começa quando o usuário pedir explicitamente que o Luna execute este plano. As decisões técnicas abaixo estão fechadas para evitar perguntas repetitivas; os gates de dados reais e revisão jurídica permanecem obrigatórios.

Leia este plano inteiro e depois `JURIX_NORMATIVE_GRAPH_TEST_RUNBOOK.md`. Execute T-001 primeiro e apenas uma tarefa por vez. Use este plano, não os antigos T-001/T-014 dos documentos de auditoria: os identificadores aqui pertencem a um novo ciclo.

## 1. Resultado esperado e limites

Ao final, um usuário deve conseguir:

1. Pesquisar separadamente lei ordinária, lei complementar, decreto e as séries oficiais de leis promulgadas, sem classificação deduzida por LLM.
2. Abrir uma norma e conhecer os documentos que a representam, incluindo anexos, retificações e republicações.
3. Explorar relações `REFERENCIA`, `REGULAMENTA`, `ALTERA`, `SUBSTITUI`, `ADICIONA` e `REVOGA`, com dispositivo e evidência de origem.
4. Diferenciar uma relação extraída pendente de revisão de uma relação juridicamente validada.
5. Consultar uma redação na data escolhida, ou receber uma explicação precisa de por que essa redação não pode ser reconstruída.
6. Comparar versões e seguir citações para o documento e trecho correspondentes à versão usada.
7. Perguntar ao assistente sobre normas e relações, com evidências temporalmente compatíveis, cobertura informada, streaming funcional e cópia com referências.
8. Navegar por temas sem interpretar similaridade temática como alteração jurídica.
9. Acompanhar importação e sincronização retomáveis, sem milhares de tarefas disparadas simultaneamente.
10. Reproduzir um experimento que compare RAG atual e RAG com relações/tempo, sem resultados científicos inventados.

Não fazem parte deste ciclo: trocar Django por React; instalar Neo4j; publicar todos os PDFs no Git; ingerir o ZIP inteiro no banco real; decidir automaticamente controvérsias jurídicas; detectar revogação tácita como fato; importar mensagens de veto como se fossem leis; apagar textos vetados/revogados; garantir que o arquivo representa toda a legislação de Natal; construir um crawler genérico de todos os Diários Oficiais; implementar efeitos tributários, condicionais ou retroativos complexos sem revisão.

O recurso de relações deve ser utilizável independentemente do recurso de reconstrução temporal. Uma falha no Ollama não deve impedir pesquisa por identidade, leitura da norma, grafo ou timeline.

## 2. Evidência e estado inicial

### 2.1 Material recebido

ZIP original, somente leitura:
`C:\Users\Cauã V\Downloads\sistema2-20261003T011536Z-1-001.zip`.

Transcrição da reunião:
`C:\Users\Cauã V\.codex\attachments\58d9188c-f51a-4136-b70e-7199363aeba3\Texto colado.txt`.

Inventário observado no ZIP: 6.663 PDFs, 6.662 HTMLs, 8 DOCs, 2 DLLs e 4 scripts Python, além de outros arquivos auxiliares. Prefixos dos PDFs: 4.635 `Decreto`, 1.765 `LeiOrdinaria`, 234 `LeiComplementar`, 29 `LeiPromulgada`. Esses números são contagens de arquivos; não constituem contagem de normas únicas, validação do conteúdo ou certificação de completude. Recalcular com T-003 e registrar o hash do arquivo usado.

Exemplos que devem motivar testes, não correções automáticas:

- `LeiComplementar_20211220_198_.pdf`: cabeçalho indica 12/11/2021; filename contém 20/12/2021. Podem ser datas de naturezas diferentes.
- O art. 1º desse documento referencia o art. 21 da LC 055/2004, e o art. 2º referencia o art. 44. A ação é `REFERENCIA`, não `ALTERA`.
- `leiPromulgada_5789.pdf`: filename sugere uma categoria, mas o texto apresenta lei sancionada. Não resolver a divergência sem fonte oficial/revisão.
- `Decreto_20230831_12887_.pdf`: texto extraído apresenta possível conflito entre ano no cabeçalho e contexto documental. Registrar candidatos, não corrigir ano por maioria de ocorrências.
- Há filenames sem data, como `decreto_7795.pdf`, anexos e variantes de republicação. A primeira sequência de quatro dígitos **não é necessariamente um ano**.
- Alguns HTMLs do pacote classificam LC como `Lei`. PDF, HTML e filename não têm a mesma confiabilidade. Não executar os scripts ou DLLs recebidos.

### 2.2 Pontos de extensão já existentes

- `src/apps/legislation/models.py`: `Norma` (linha 12), `Dispositivo` (aproximadamente linha 183), `EventoAlteracao` (linha 457). `Norma` já tem publicação, vigência, SAPL, textos; `Dispositivo` tem identidade estrutural, revisão e embedding; eventos têm validação, fingerprint, proveniência e retenção de revisões inativas.
- `src/apps/ingestion/task_support.py:33`: normalização atual de tipo mapeia explicitamente somente código `1` para `Lei`. `:91`: resolução inicial exige tipo/número/ano e faz correspondência literal.
- `src/processing/normative_reference.py`: parser e funções `canonical_type`, `normalize_number`; reutilizar e ampliar, sem criar normalizadores divergentes.
- `src/processing/target_resolver.py`, `target_reconciliation.py`: resolução conservadora de dispositivos e segunda passagem quando o alvo chega depois.
- `src/apps/ingestion/segmentation_tasks.py:98`: metadados do colofão são preservados antes de remover o trecho editorial. Já há reconciliação para preservar PKs e vínculos dos dispositivos.
- `src/processing/event_revision.py`: identidade da extração. Não substituir por IDs que mudam em toda ingestão.
- `src/processing/consolidation_engine.py:37`: por padrão não aplica evento não validado. Ampliar a seleção temporal; não remover essa salvaguarda.
- `src/processing/temporal_scope.py`, `src/apps/legislation/temporal_api.py`: filtros, status e timeline. A existência desses filtros não prova que qualquer redação histórica já é reconstruível.
- `src/apps/ingestion/sapl_sync.py`: leases, checkpoints e hashes de payload. A parada em página inalterada depende de ordenação; não equivale a comprovar ausência de mudanças antigas ou no PDF.
- `src/processing/corpus_identity.py`, `src/apps/legislation/signals.py`: identidade persistente e invalidação. Hoje callbacks de vários saves podem recalcular o corpus repetidamente; tratar antes da importação em escala.
- `src/processing/adaptive_rag_service.py`, `adaptive_retrieval.py`, `rag_context_builder.py`: recuperação adaptativa e consulta de norma inteira já existem; estender, não substituir por top-k fixo.
- `src/apps/legislation/serializers.py`, `answer_contract.py` em `src/processing`, `source_urls.py`: contrato estruturado e URLs; estender com documento/versão, sem URLs produzidas pelo LLM.
- `benchmarks/corpus/municipal_natal/`: manifesto e anotação v1, protocolo e validator. O contrato v1 exige SAPL ID; o ZIP tem documentos ainda não associados a SAPL. Criar v2 compatível, sem IDs fictícios.
- Protocolo existente: 20 normas humanas no piloto científico; amostra intencional 150–200 normas; expansão 300 é operacional opcional. O acervo de milhares de PDFs não substitui esse desenho experimental.
- UI usa `legislation/workspace/base.html`, `norma_detail.html`, `norma_compare.html`, `jurix-legal-detail.js` e tokens em `jurix-tokens.css`.
- Infraestrutura de QA: `docker-compose.audit.yml`; testes Python em `src/tests`; JS em `tests/js`, com jsdom e puppeteer-core já disponíveis como dependências de desenvolvimento.

Linhas são pistas do baseline, não contratos permanentes. Antes de alterar uma função, localizar pelo nome e ler sua versão atual.

### 2.3 Preservação

Na elaboração deste plano estavam preexistentes:
` M docs/audit/2026-10-02/http-events.jsonl` e `?? GOAL.md`.
O servidor de auditoria em 8006 pode continuar acrescentando telemetria ao primeiro arquivo. Não incluir nenhum deles em commits da implementação e não parar esse servidor para liberar uma porta: usar QA em 8007, se livre.

## 3. Decisões fechadas de arquitetura

### 3.1 Norma, documento e identidade

**Norma** é a entidade jurídica; **documento** é uma manifestação documental; **extração** é uma versão técnica do texto de um documento. Vários documentos podem representar a mesma norma. Bytes diferentes não provam que existe outra norma; textos iguais não provam identidade jurídica.

Identidade normalizada candidata:
`jurisdição + tipo canônico + série de numeração + número normalizado + ano`.

Exemplo: `BR-RN-NATAL|lei_complementar|municipal_lc|55|2004`.
A série precisa de mapeamento explícito do catálogo. Usar códigos estáveis `municipal_lc`, `municipal_lo`, `municipal_decreto`, `municipal_lp` somente quando confirmados; séries desconhecidas permanecem desconhecidas.

- Preservar `Norma.tipo` e `numero` legados para apresentação/compatibilidade. Criar `identity_key` nullable/unique e `identity_json` para a chave revisada; não alterar em massa a constraint antiga sem um relatório de colisões.
- `055` e `55` podem ter a mesma chave numérica quando o identificador for puramente numérico; preservar grafia. Sufixos não numéricos, como `5-A`, não podem virar `5`.
- `LeiPromulgada` é rótulo/série do catálogo recebido. Preservar `municipal_lp`; não fundir automaticamente com lei ordinária nem concluir natureza jurídica pela palavra “promulgada”. Guardar natureza, série e autoridade promulgadora em campos distintos no JSON de identidade.
- Referência federal/estadual nunca recebe automaticamente um alvo municipal. O escopo faz parte da resolução.
- Ausência de SAPL ID continua `null`. Não construir `/norma/<número-da-lei>/` como se o número fosse SAPL ID.
- Toda associação ambígua permanece pendente. Um candidato único por nome, sem metadados confirmados, não ganha revisão jurídica automaticamente.

### 3.2 Datas e conflitos

Manter separadas: data do ato/epígrafe, data de publicação, data de início de vigência, data de produção de efeitos específica, data do documento/republicação, data de coleta e data de revisão.

Cada candidato a metadado guarda `field`, `value`, `source`, `document_key`, `page`, `quote`, offsets quando disponíveis e `status`. Datas diferentes de naturezas diferentes não são conflito. Datas discordantes para o mesmo campo são conflito.

Regra de escolha:

1. Decisão humana documentada para aquela revisão.
2. Campo oficial explícito do catálogo/documento, com semântica conhecida.
3. Epígrafe para data/número/tipo do ato; colofão explícito para publicação.
4. Filename como candidato, nunca para publicação/vigência sem comprovação.

Prioridade não significa apagar candidato vencido nem ignorar conflito. Enquanto há conflito material não resolvido, a reconstrução temporal correspondente fica `unknown`/`pending_review`.

Neste ciclo, cálculo automático de vigência aceita apenas cláusula inequívoca na data da publicação, com publicação confirmada, ou data ISO explicitamente revisada. Vacatio de dias, vigência por artigo, condição, retroatividade e regras especiais ficam candidatas para revisão. Não definir vigência como publicação por ausência de informação.

### 3.3 Relações e segurança jurídica

- Relações jurídicas usam `EventoAlteracao`; similaridade temática não usa essa tabela.
- `REGULAMENTA` exige texto que estabeleça regulamentação; um decreto que cita autorização orçamentária não recebe essa ação por ser decreto.
- Cláusula genérica de revogação fica uma observação sem alvo. Não inferir revogação tácita.
- Extrair vínculo não valida vínculo. Revisão deve confirmar ação, alvo, trecho e efeito temporal separadamente.
- `validado=True` legado continua visível, mas só autoriza nova projeção temporal se a evidência/revisão necessária ao contrato novo estiver disponível. Não fabricar autor/data de uma validação antiga.
- Dispositivo vetado/revogado permanece preservado; `is_active` do pipeline significa presença na extração atual, **não** vigência jurídica.
- Texto de projeto ou mensagem de veto não entra no conjunto de fontes operativas como norma promulgada. Veto rejeitado/promulgação posterior precisa de documento e evento revisados.
- Revogar uma norma alteradora não restaura automaticamente uma redação anterior. Marcar cenário não suportado para revisão, sem inferência automática de restauração.

### 3.4 Implementação leve do grafo

PostgreSQL relacional permanece a fonte de verdade. Endpoint constrói vizinhança limitada; frontend usa SVG nativo, JS modular e uma lista HTML equivalente.

Não instalar biblioteca de force simulation, React ou banco de grafo. Layout determinístico por camadas: vínculos recebidos à esquerda, norma foco no centro, vínculos produzidos à direita. Nó externo/não resolvido claramente rotulado. Colapsar múltiplos vínculos visuais entre duas normas sem perder eventos individualizados no painel.

Limites iniciais: profundidade 1 por padrão, máximo 2; até 40 nós e 80 arestas por resposta; consulta com revisão do corpus fixada; indicador `truncated` e ação explícita para refocar/filtrar. Não prometer expansão completa silenciosamente.

### 3.5 Modelos novos: contratos mínimos

Criar modelos no arquivo novo `src/apps/legislation/document_models.py`, importados explicitamente pelo módulo `models.py`, sem dependência circular. Usar referências de FK por string. Novas migrations são geradas pelo Django; o número deve ser a próxima folha real, **não** um número presumido deste plano.

`DocumentoNormativo`:

- UUID público; `document_key` unique: hash de fonte/identificador de origem/revisão dos bytes; `content_sha256` indexado, não unique.
- FK nullable `norma`, `PROTECT`; `source_kind` (`archive`, `sapl`, `official_gazette`, `legacy`); `source_ref` sem caminho absoluto público.
- `archive_sha256`, `entry_index`, `entry_name` privado; filename original; `role` (`original`, `republicacao`, `retificacao`, `anexo`, `indeterminado`).
- storage relativo content-addressed; tamanho; hash; URL oficial nullable; data da coleta; condição de uso `unknown` por padrão.
- `metadata_json`, `conflicts_json`, `extraction_status`, `review_status`, versão/parser e hash do texto bruto.
- `raw_text`, `legal_text`, mapa de páginas/offsets; limites de tamanho para não acumular imagens/OCR no JSON.
- Hashes e textos publicados como revisão documental são imutáveis. Extração com outra versão produz registro de extração versionado (`ExtracaoDocumento`), não overwrite silencioso. Para evitar duplicação, colocar textos/mapas na extração, e manter no documento só ponteiro nullable `accepted_extraction`.
- Documento candidato não ativa pipeline. Seleção do documento-base da norma é explícita, auditada e revisada.

`ExtracaoDocumento`: FK documento `PROTECT`; `extractor_version`, `policy_fingerprint`, textos bruto/legal, hashes, páginas/metadados/mapa de origem, qualidade; unique `(documento, extractor_version, policy_fingerprint)`; nova execução idêntica é no-op. Versão aceita não perde seu conteúdo quando outra extração chega.

`DocumentoDispositivo`: FK extração; `structural_key`, `parent_key`, tipo/número/ordem, texto, offsets em `legal_text`, origem na página quando comprovada; `marker` (`none`, `vetado`, `revogado`, `unknown`); unique `(extracao, structural_key)`. É imutável; não substitui o PK legado de `Dispositivo`.

`RevisaoJuridica`: registro append-only de decisão; objeto alvo + fingerprint esperado; ação (`approve`, `reject`, `supersede`), motivo, ator autenticado e timestamp; dados pessoais do ator não aparecem em APIs públicas. Use um modelo novo em `src/apps/legislation/review_models.py`, importado pelo módulo `models.py`. Para evitar GenericForeignKey desnecessária, FKs opcionais concretas a documento/evento e check de exatamente um alvo. Decisões metadata ficam vinculadas ao documento.

`SnapshotNormativo`: norma, `as_of`, corpus digest, policy version, base extraction FK, state (`supported`, `partial`, `not_reconstructable`, `pending_review`), reason codes, lista ordenada de eventos/revisões, hash da projeção; unique `(norma, as_of, corpus_digest, policy_version)`; não é versão oficial publicada pelo Município.

`SnapshotDispositivo`: snapshot, `structural_key`, texto exibido, estado jurídico, FKs de documento-dispositivo/base e proveniência dos eventos; unique `(snapshot, structural_key)`. Conteúdo histórico não utiliza o embedding do texto atual.

Em `Norma`: adicionar `identity_key` nullable/unique, `identity_json`, `data_norma` nullable, FK nullable `documento_base` com `PROTECT`. Não apagar campos antigos.

Em `EventoAlteracao`: adicionar `target_reference_json`, `evidence_json`, `effective_on` nullable, `effective_date_status` (`unknown`, `candidate`, `confirmed`), `effective_date_basis` JSON e `review_revision` nullable. Evidência inclui extração/hash/quote/offsets/ação e alvo. Reutilizar fingerprint existente com versão nova, preservando revisões anteriores.

Estado operacional/checkpoint do ZIP fica em `src/apps/operations/models.py`: `ArchiveImportRun` com hash, manifesto/hash, cursor, limites, stats, lease e status; não duplicar `SaplSyncState`.

### 3.6 DTOs, API e proveniência

Endpoint novo: `GET /api/v1/normas/<pk>/relations/?depth=1&action=REFERENCIA&as_of=2021-12-31&include_pending=false`.

Resposta contém:

```json
{
  "schema_version": 1,
  "corpus_digest": "hash",
  "focus": "norma:42",
  "scope": {"as_of": "2021-12-31", "depth": 1},
  "nodes": [{"id": "norma:42", "kind": "norma", "label": "LC nº 198/2021", "url": "/normas/42/"}],
  "edges": [{
    "id": "event:17:revision_hash",
    "source": "norma:42",
    "target": "external:reference_hash",
    "action": "REFERENCIA",
    "source_device_key": "stable_key",
    "target_device_key": null,
    "resolution": "unresolved",
    "review_status": "pending_review",
    "effective_on": null,
    "evidence": {"document_id": "uuid", "quote": "trecho literal", "page": 1},
    "official_url": null
  }],
  "truncated": false,
  "limits": {"nodes": 40, "edges": 80}
}
```

Dados do exemplo ilustram formato, não IDs do corpus. Só publicar trecho se a condição de uso estiver resolvida; para documentos pendentes, endpoint público omite texto e metadados privados. A API staff pode exibir candidatos em revisão mediante permissão.

`GET /api/v1/normas/<pk>/version/?as_of=AAAA-MM-DD` retorna snapshot, estado, razões, documento-base e dispositivos. Não modifica banco em GET: snapshot deve estar pré-computado; se ausente, montar projeção read-only limitada, ou responder estado `pending_review`/`not_reconstructable`. Persistência é feita por comando/tarefa autorizada, não por visita anônima.

Documento local recebe rotas read-only `GET /normas/documentos/<uuid>/` para evidência legível e `GET /normas/documentos/<uuid>/pdf/` para bytes daquela revisão. Declarar padrões antes de rotas genéricas, validar acesso/condição de uso e servir via storage autorizado; não expor caminhos ou aceitar filename arbitrário. Documento candidato não público exige staff com permissão. View HTML usa escape normal do template, nunca HTML do pacote. Anchor da extração identifica structural key e versão; PDF guarda sua identidade por UUID/hash. Não produzir `local_evidence_url` antes de essas rotas existirem e terem testes.

Fonte RAG acrescenta: `document_id`, `extraction_id`, `document_sha256`, `snapshot_id`, `version_hash`, `as_of`, `legal_status`, `evidence_role`, `relation_event_ids`, `official_url`, `local_evidence_url`. `citation_id` é estável por revisão da evidência; `[[1]]` é somente índice local daquela resposta.

Quando não há URL oficial confirmada, oferecer “Ver documento do acervo” com proveniência; não rotular como “Abrir no SAPL”. Nunca expor path de disco. A referência à norma abre a fonte base sem marca; referência ao dispositivo pode usar âncora local ou fragmento de texto gerado pelo código, com fallback para documento base.

### 3.7 Feature flags e mudanças de contrato

Configurar flags inicialmente desligadas: `NORMATIVE_ARCHIVE_ENABLED`, `NORMATIVE_GRAPH_ENABLED`, `NORMATIVE_HISTORY_ENABLED`, `RAG_GRAPH_CONTEXT_ENABLED`. Ligar apenas no QA por T-001. Manter comportamento legado se desligadas, exceto correções de normalização compatíveis cobertas por teste.

Manifestos/anotações científicos v1 continuam válidos. Criar v2 para documentos sem SAPL ID; não editar fixtures v1 para tornar teste verde. Contrato SSE mantém eventos existentes; campos novos são aditivos. Se a nova versão documental tornar alguma citação incompatível, servir fonte legada preservada sem inventar a versão histórica.

## 4. Regras de execução do Luna

1. Modelo sugerido pelo usuário: GPT 6 Luna com esforço alto. Não delegar julgamento jurídico ao próprio LLM.
2. Registrar status, branch, HEAD, staged/unstaged/untracked e resultado dos testes antes de editar. Não clonar, pull, trocar branch, reset, clean, stash ou descartar alterações.
3. Ler código e tests indicados antes de editar; usar `rg` e `apply_patch`.
4. Não exibir `.env`, strings de conexão, credenciais, chaves, conteúdo de conversas reais ou dados pessoais em logs/relatórios.
5. Só QA recebe migrations, importação, seed, validações sintéticas, interrupções e exclusões. ZIP original é read-only.
6. Uma tarefa coerente por vez. Rodar seus testes antes e depois; suites completas nos gates. Teste ausente antes da tarefa deve ser declarado como novo, não como executado.
7. Não mudar comportamento fora de “Arquivos a alterar”. Todos os outros arquivos são fora do escopo da tarefa, além dos explicitamente protegidos. Se o código atual exigir outro arquivo, explicar a dependência e pedir inclusão antes de editar.
8. Não atualizar snapshots/expectativas apenas para esconder regressão. Preservar testes de segurança, SSE, história, revisão, grounding e cache.
9. Não adicionar dependências: Python/Django/PyMuPDF, JS nativo e dependências dev atuais bastam. Uma necessidade nova exige decisão explícita.
10. Dividir internamente uma tarefa se o diff deixar de ser revisável; usar sufixos T-010a/T-010b e manter a ordem/dependências. Não eliminar critérios de aceite ao dividir.
11. Commit por tarefa **somente se o usuário autorizar commits na execução**. Sem autorização, preservar diff e checkpoints. Nunca fazer push/merge automático. Stage somente paths da tarefa, não `git add .`.
12. Rollback de código: revert do commit da tarefa se commits autorizados. Sem commit, reversão de hunks próprios, após conferir que não houve edição sobreposta do usuário. Nada de checkout destrutivo. Revert de código não desfaz efeitos no banco; usar flags e snapshot/backup QA.
13. Nunca reverter migration aplicada com dados relevantes por reflexo. Em QA descartar/recriar apenas ambiente explicitamente descartável, após confirmação do alvo; em banco real qualquer rollback exige procedimento próprio autorizado.
14. Se um gate falhar, parar aquela fase, informar comando/erro sanitizado e resolver no escopo autorizado. Não declarar completo, não pular teste crítico nem seguir para ativação real.
15. Não presumir que 8006 aponta para o novo banco/schema. Servidor novo fica em porta QA identificada, e o relatório informa HEAD, banco QA e flags sem secrets.

## 5. Fases e gates

**Fase A — fundação e staging, T-001 a T-009.** Resultado: inventário íntegro, extração, identidade e documentos candidatos em QA, sem promoção indevida. Gate: repetir importação não duplica registros, conflito não altera identidade real e nenhum documento pendente vira fonte operativa.

**Fase B — evidências, revisão e tempo, T-010 a T-015.** Resultado: revisões imutáveis, relações resolvíveis e projeções temporais conservadoras. Gate: efeitos pendentes não alteram redação; antes/depois de alteração comprovada produzem textos e citações distintos.

**Fase C — produto e recuperação, T-016 a T-022.** Resultado: grafo/lista, comparação, RAG temporal, fontes/cópia corretas e temas separados. Gate: navegação real desktop/mobile; nenhuma afinidade temática é tratada como efeito jurídico; histórico não usa texto futuro.

**Fase D — sincronização e mensuração, T-023 a T-028.** Resultado: atualização segura, propagação limitada e avaliação reproduzível. Gate: mudança antiga ou somente no PDF é detectável; não marcar completude a partir de parada parcial; custo por lote mensurado.

**Fase E — aceitação e entrega, T-029 e T-030.** Resultado: testes do aplicativo, screenshots sanitizados, documentação e relatório de pendências. Gate: regressões resolvidas; limitações jurídicas e gold humano pendente explicitados. Ativação em banco real é etapa operacional separada.

## 6. Tarefas atômicas

Os nomes de arquivos novos abaixo são decisões de implementação. Arquivo já existente deve ser lido e alterado estreitamente; nunca substituído por uma implementação do zero. “Não tocar” inclui todos os arquivos não listados, o ZIP, `.env`, `GOAL.md`, auditorias anteriores e bancos reais.

### T-001 — Ambiente QA protegido e baseline

Objetivo: permitir testes e browser sem gravar em banco/Redis/media reais.
Pré-requisitos: checkout atual; Docker disponível; não requer Ollama para preparar banco.
Arquivos a alterar/criar: `config/settings_normative_qa.py`, `scripts/normative_qa.py`, `src/tests/test_normative_qa_guard.py`, `docs/research/NORMATIVE_IMPLEMENTATION_PROGRESS.md`.
Não tocar: `.env`, `config/settings.py`, compose de produção, servidor 8006 e dados reais.

Passos:

1. Registrar baseline sanitizado e hashes/status dos arquivos preexistentes. Registrar versões Python/Node e paths dos executáveis, sem presumir PATH.
2. Usar os serviços db/redis de `docker-compose.audit.yml`, projeto Docker `jurix-normative-qa`. Não iniciar seu worker padrão, que não conhece o novo settings módulo.
3. Novo settings importa `config.settings`, mas exige opt-in `JURIX_QA_ONLY=1` e valida engine PostgreSQL, host loopback, porta 55432, DB `jurix_audit`, Redis loopback porta 16380. Em fixture unitária DB `test_jurix_audit` também permitido. Recusar outras combinações; não imprimir URL recebida.
4. O helper obtém somente as credenciais fixture dos serviços de auditoria já existentes, ou as recebe do ambiente. Nunca lê/substitui credenciais reais; não registra valores. Exporta `DJANGO_SETTINGS_MODULE=config.settings_normative_qa`, URLs QA e `JURIX_QA_ROOT` único fora do banco real.
5. Settings QA aponta media/raw/logs/relatórios ao QA root, desativa beat, usa queue/result backend QA, e não dispara jobs de ingestão na inicialização. Configurar eager só no teste unitário; runtime deve exercitar Celery real posteriormente.
6. Helper implementa `--check`, `--check-services`, `--run ...` com allowlist de subcomandos Python/Node da seção de verificação. Não aceita shell string arbitrária e não migra/seed automaticamente no `--check`.
7. Registrar baseline suites no QA antes de começar T-002. Se houver falha preexistente, não apagá-la; classificar e bloquear o fluxo que dependa dela.

Aceite: comandos contra DB real recusados; media/logs isolados; root e URLs não expostos; todos os testes executados apontam para QA; Git sem mudanças externas ao escopo.
Verificação: `python -m pytest src/tests/test_normative_qa_guard.py -q`; `python scripts/normative_qa.py --check-services`; suites do runbook seção 3.
Rollback: regra geral de código, sem apagar volumes desconhecidos.
Se falhar: não rodar migrations nem importar documentos; informar serviço/guard que falta.

### T-002 — Identidade e metadados determinísticos

Objetivo: unificar tipo/número/série/escopo e candidatos de data sem LLM.
Pré-requisitos: T-001.
Arquivos: `src/processing/normative_reference.py`, novo `src/processing/document_metadata.py`, `src/apps/ingestion/task_support.py`, `src/tests/test_normative_reference.py` se existir, novo `src/tests/test_document_metadata.py`, `src/tests/test_target_reconciliation.py`.
Não tocar: banco/migrations, ranking do histórico, prompts.

Passos:

1. Acrescentar aliases accent-insensitive de tipos do filename e cabeçalho à função canônica existente. `LC` e `LeiComplementar` resolvem LC; decreto legislativo continua diferente de decreto executivo.
2. Criar normalização de identidade que mantém sufixos e zera à esquerda só identificadores puramente numéricos. Não mudar `normalize_number` globalmente sem testes dos consumidores; fornecer função específica quando necessário.
3. Parser de filename aceita data apenas no segmento de oito dígitos em posição prevista, valida calendário, identifica role de republicação/retificação/anexo e mantém tokens não interpretados.
4. Parser de epígrafe opera antes da limpeza, em páginas iniciais delimitadas; referência citada no corpo não vira tipo/identidade do documento.
5. Candidatos de data do ato/publicação/vigência têm semântica separada. Material com mais de uma epígrafe principal recebe `multi_norm_document`; não escolher a primeira arbitrariamente.
6. Código SAPL desconhecido permanece desconhecido. Não ampliar o dicionário com números adivinhados; integração com catálogo vem em T-023.

Aceite: `decreto_7795` não recebe ano 7795; LC055/2004 e LC55/2004 têm chave igual; 5-A distinto de5; LP não fundida comLO; datas conflitantes preservadas; nenhum request/LLM no parser.
Verificação: pytest nos arquivos da tarefa e `src/tests/test_normative_query.py` se presente; regressões de follow-up/target resolver existentes.
Rollback: regra geral.
Se falhar: manter identidade como pendente; não inventar fallback.

### T-003 — Inventário seguro e reproduzível do ZIP

Objetivo: produzir manifesto técnico sem importar normas nem executar arquivos.
Pré-requisitos: T-002; ZIP somente leitura.
Arquivos: novo `src/processing/archive_inventory.py`, `scripts/inventory_normative_archive.py`, `src/tests/test_archive_inventory.py`.
Não tocar: conteúdo ZIP, banco, scripts recebidos.

Passos:

1. Ler diretório central com `zipfile`; identificar entradas pelo índice além do nome, pois nomes repetidos podem existir. Normalizar separadores, detectar paths absolutos, drive/UNC, `..`, symlinks, entradas cifradas e colisões case-insensitive.
2. Classificar extensões; DLL/PY/HTML/DOC ficam inventariados, não executados. Neste ciclo, pipeline jurídico aceita só PDFs; DOC fica pendente de conversão explícita futura.
3. Gerar hash do ZIP por streaming e, para PDFs seguros, hash dos bytes lendo chunks; não carregar 766 MB na memória, não usar `extractall`.
4. Limites de segurança explícitos/configuráveis: 50.000 entradas, 128 MiB por PDF, 8 GiB descompactados no lote, razão 500:1; nunca “liberar tudo” ao exceder. Se corpus legítimo superar, relatar para ajuste de política.
5. Saída JSONL UTF-8 ordenada por índice, com schema version, hash ZIP, entry/index/size/hash, filename metadata e flags. Resumo JSON apresenta counts por extensão/tipo/role, duplicatas exatas e possíveis colisões jurídicas separadamente.
6. CLI exige `--archive` e `--output`; se output existe, recusar overwrite. Manifesto só é `complete=true` depois de verificar todas as entradas selecionadas; saída interrompida é parcial e não serve ao apply.

Aceite: replay do mesmo arquivo gera mesmo conteúdo determinístico, exceto campo externo de execução; entradas inseguras bloqueadas; arquivos não-PDF não são extraídos; memória limitada; counts reconciliados com total.
Verificação: pytest novo; executar inventário real em pasta QA e registrar duração/hash/counts. Testes ZIP slip, duplicate entries, PDF excessivo, arquivo truncado, encrypted entry e compressão extrema com fixtures pequenas.
Rollback: regra geral; manter outputs para auditoria.
Se falhar: não extrair/importar entradas marcadas inseguras.

### T-004 — Extração nativa com OCR seletivo e offsets

Objetivo: aproveitar texto do PDF sem perder proveniência ou anexos.
Pré-requisitos: T-003; PyMuPDF/Tesseract atuais.
Arquivos: novo `src/processing/document_extraction.py`, `src/apps/ingestion/ocr_tasks.py`, `src/processing/legal_parser.py`, novo `src/tests/test_document_extraction.py`, `src/tests/test_legal_parser.py`.
Não tocar: prompts, banco real, regras gerais de consolidação.

Passos:

1. Extrair por página texto nativo e mapa de origem. Separar texto bruto, normalização técnica e corpo jurídico; nunca substituir original.
2. Política inicial para considerar OCR: página com imagem e menos de 40 caracteres úteis, ou mais de 2% de replacement/control chars. Isso é triagem técnica, não confiança jurídica; página curta legítima sem imagem não recebe OCR automaticamente.
3. Reusar Tesseract já configurado. OCR por página, timeout inicial 90s, limite 200 páginas; documento acima disso fica pendente, não truncado como “completo”. Workload concorrente 1 no QA.
4. Guardar método por página (`native`, `ocr`, `unreadable`), hash de extração/policy, versões, duração e qualidade. Não conservar renderizações de todas as páginas em RAM.
5. Extrair epígrafe/colofão antes de limpar. `strip_closing_editorial_metadata` não pode descartar anexos/adendos com conteúdo normativo/orçamentário; classificar segmentos e manter anexos separados.
6. Offsets públicos referem-se a uma versão textual explicitada. Não declarar que offset do texto limpo é offset do PDF bruto. Mapas incompletos ficam nullable.
7. Validar literal `quote == legal_text[start:end]` quando houver span. PDF escaneado fornece texto OCR e indicação, não “cópia exata certificada”.

Aceite: PDF nativo não passa por OCR; misto usa OCR só onde necessário; art. final não absorve assinatura; adendos do decreto não desaparecem; timeout não marca documento aprovado.
Verificação: pytest da tarefa; smoke com amostras ZIP em QA, registrando contagens por método; ler visualmente ao menos uma página nativa e uma OCR real se disponível.
Rollback: regra geral.
Se falhar: preservar texto bruto e status pendente.

### T-005 — Manifestos e anotações v2 compatíveis com acervo

Objetivo: suportar documentos sem SAPL ID e revisões temporais no experimento.
Pré-requisitos: T-003/T-004.
Arquivos: novos `benchmarks/corpus/municipal_natal/manifest.v2.schema.json`, `annotation.v2.schema.json`, `graph-evaluation-protocol.md`; `scripts/validate_municipal_corpus.py`, `src/tests/test_municipal_corpus_contract.py`.
Não tocar: schemas/fixtures v1, contagens científicas exigidas, resultados anteriores.

Passos:

1. Manifesto v2 usa `norma_key` e `document_key`, `sapl_id` nullable, fonte archive/SAPL, hash/text version e condição de uso. Diferenciar registro documental de registro de norma.
2. Anotação v2 associa source document/span e target norma/device keys, scope, ação, revisão, data/basis e estado de resolução. Incluir `SUBSTITUI`; não alterar retrospectivamente enum v1.
3. Validator despacha por schema_version, valida hashes/path containment/spans e vínculo do documento; rejeita mistura de hashes/revisões.
4. Separar validade estrutural de gate humano: exit0 válido/aprovado, exit2 inválido, exit3 estrutura válida mas revisão humana ainda insuficiente.
5. Registrar piloto técnico alvo40 documentos, independente de 20 normas humanas científicas e amostra150–200. Admitir30–50 se composição/motivo documentados; não chamar múltiplos documentos da mesma norma de múltiplas normas revisadas.

Aceite: v1 ainda passa/falha como antes; v2 aceita SAPLnull, não aceita fonte oficial inventada; casos sintéticos nunca satisfazem gate humano; offsets comprováveis.
Verificação: pytest; validator em exemplos sintéticos v1/v2; invalidar ano/id/hash/conflicting-span intencionalmente em fixtures, não em dados reais.
Rollback: regra geral.
Se falhar: não exportar registros como gold.

### T-006 — Persistência documental aditiva

Objetivo: guardar documentos e extrações sem substituir normas existentes.
Pré-requisitos: T-005.
Arquivos: novo `src/apps/legislation/document_models.py`; `src/apps/legislation/models.py`; novo `src/apps/legislation/review_models.py`; `src/apps/operations/models.py`; migrations novas nas duas apps; novo `src/tests/test_normative_document_models.py`.
Não tocar: migrations antigas, PKs existentes, constraint legada de identidade.

Passos:

1. Criar DocumentoNormativo, ExtracaoDocumento e DocumentoDispositivo conforme seção3.5. Criar campos aditivos em Norma; RevisaoJuridica e ArchiveImportRun.
2. Relações PROTECT onde exclusão apagaria proveniência. Modelos públicos nunca serializam storage path, email ou payload livre do ator.
3. Migrations de schema não fazem importação nem backfill automático. `identity_key` legado começa null; seleção documento-base começa null.
4. Garantir que o Django descobre modelos importados e que imports não têm ciclos. Testar constraints e concorrência em PostgreSQL QA.
5. Acrescentar validações de imutabilidade no serviço; documentar que bulk SQL não deve ser usado para sobrescrever textos históricos. Testar update rejeitado após aceite.

Aceite: migrations QA passam sem eliminar dados; legacy URLs/serializers continuam; duplicate key não cria documento duplicado; conteúdo imutável após aceite.
Verificação: `makemigrations --check --dry-run` após gerar migrations; `migrate --plan` e migrate só QA; pytest tarefa + test_migrated_schema.
Rollback: regra geral; flags desligadas preservam comportamento legado, não desfazer schema com dados por reflexo.
Se falhar: interromper persistência/importação.

### T-007 — Invalidação por fronteira de lote

Objetivo: evitar recalcular todo o corpus a cada save durante importação.
Pré-requisitos: T-006.
Arquivos: `src/apps/legislation/signals.py`, `src/processing/corpus_identity.py`, novo `src/processing/corpus_write_boundary.py`, `src/tests/test_corpus_identity.py`, `src/tests/test_corpus_cache_signals.py`.
Não tocar: cache de sessões/credenciais, budgets para esconder crescimento.

Passos:

1. Criar contexto explícito de escrita de corpus que agrega dirty state por transação/lote, com ContextVar e limpeza em finally; nada de flag global process-wide.
2. No commit externo, atualizar digest e invalidar uma vez. Rollback não publica nova revisão. Escrita fora do contexto continua coberta pelos signals existentes.
3. Documentos em staging não alteram digest jurídico. Seleção de base, extração aceita, revisão de evento e efeito temporal alteram digest; acrescentar metadata necessária ao algoritmo.
4. bulk_update/bulk_create só usados pelo serviço que marca fronteira; nunca confiar que disparam signals.
5. Registrar falha de atualização sem secrets e impedir declarar freshness confirmada enquanto revisão estiver dirty. Preservar best-effort sem quebrar escrita jurídica.

Aceite:50 saves no mesmo lote resultam em no máximo1 recomputação; rollback0; saves externos ainda invalidam;2 processos não compartilham flag; staging não finge atualizar corpus.
Verificação: pytest corpus/cache; teste transacional real QA; medir contador de chamadas, não apenas presença de string no código.
Rollback: regra geral.
Se falhar: não executar importação em escala.

### T-008 — Importador staging retomável e idempotente

Objetivo: registrar documentos candidatos em lotes seguros.
Pré-requisitos: T-007; manifesto completo validado de T-003.
Arquivos: novo `src/apps/ingestion/archive_import.py`, `management/commands/import_normative_archive.py`, novo `src/tests/test_archive_import.py`.
Não tocar: norma.texto_original/consolidado existentes, beat, banco real.

Passos:

1. CLI default dry-run; `--apply` requer guardQA, hash ZIP igual ao manifesto e output QA explícito. Sem migrations implícitas.
2. `--limit` default40, `--batch-size` default10, `--resume` com hash/versão do mesmo run; `--all` não existe neste ciclo. Arquivos fora do manifesto não entram.
3. Content-addressed copy do PDF aceito para storage QA, via staging temporário e promoção atômica; path calculado por hash, nunca filename do ZIP. Não sobrescrever blob com hash diferente.
4. Lease/checkpoint por ArchiveImportRun; persistir uma entrada concluída transacionalmente antes de avançar cursor. Reexecução não perde entrada que falhou. Falha por documento é registrada e retry limitado3, sem loop infinito.
5. Criar candidatos/extrações, jamais promover revisão/licença nem associar automaticamente conflito. Sem chain automática OCR/embedding/LLM para todas as entradas.
6. Queda entre copiar blob e DB deixa objeto recuperável; reexecução reutiliza hash. Orphans entram em relatório, sem exclusão automática.

Aceite: duas execuções idênticas não duplicam; interromper/reiniciar preserva hash/cursor; mudar ZIP recusa resume; candidato não aparece como texto consolidado; counters created/unchanged/failed honestos.
Verificação: pytest task; dry-run ZIP; apply40 sóQA após teste; interromper fixture no meio e repetir.
Rollback: regra geral e flags; não apagar candidato/arquivo auditável automaticamente.
Se falhar: preservar checkpoint e relatar entrada/fase.

### T-009 — Revisão de metadados e promoção explícita

Objetivo: ativar documento-base apenas quando identidade e condição de uso forem resolvidas.
Pré-requisitos: T-008.
Arquivos: novo `src/apps/ingestion/document_promotion.py`, `src/apps/legislation/admin.py`, novos `src/apps/ingestion/management/commands/promote_normative_documents.py`, `src/apps/ingestion/management/commands/seed_normative_qa.py`, `src/tests/test_document_promotion.py`, `src/tests/test_normative_qa_seed.py`.
Não tocar: schema v1, datas conflitantes reais, corpus todo.

Passos:

1. Admin mostra candidatos por campo, origem/quote e conflitos; não deixa apagar revisão/texto. Aprovar requer motivo e fingerprint da extração atual.
2. Serviço propõe match por identity_key e SAPLID confirmado. Se há colisão/categoria discrepante/múltiplosmatches, fica pendente; não merge/delete.
3. Seleção original/republicação/retificação/anexo é explícita. Republicação não cria segunda Norma e não altera vigência automaticamente. Anexo não substitui base.
4. Backfill legacy gera plano somente leitura; apply só no QA, com IDs/hash allowlist revisada. Legacy texto não ganha certificado de origem retroativo.
5. Promoção usa select_for_update, checks de revisão e contexto T-007. Copia compatibilidade para Norma só com base aprovada; conserva documento/extração anteriores; não promove human_review por resultado sintético.
6. Criar seed QA mínimo agora: dois tipos com número homônimo, documentos/extrações sintéticos, candidato conflitante e usuário revisor fixture. Guard QA obrigatório, execução idempotente e mapfile sem credenciais. Decisões são identificadas como sintéticas, nunca gold humano. T-015 acrescenta a cadeia temporal; T-025 amplia estratos. Assim o browser não depende de corpus real aprovado para concluir os gates intermediários.

Aceite: usuário não-staff não promove; stale approval409/erroadmin; conflitos não sobrescrevem; promoção repetida no-op; condição unknown impede uso público de trecho importado.
Verificação: pytest promoção/permissão/concurrency; browser admin só com usuário QA; revisar um candidato com conflito e outro inequívoco.
Rollback: código/flags; decisões anteriores permanecem como histórico.
Se falhar: sem documento-base novo; explicar pendência.

### T-010 — Dispositivos documentais imutáveis

Objetivo: preservar a fonte exata de cada dispositivo ao reprocessar.
Pré-requisitos: T-009.
Arquivos: novo `src/processing/document_segmentation.py`, `src/apps/ingestion/segmentation_tasks.py`, `src/processing/device_revision.py`, novo `src/tests/test_document_device_revision.py`, `src/tests/test_hierarchy_integrity.py`.
Não tocar: IDs legados de dispositivos, textos já revisados.

Passos:

1. Segmentar extração aceita, criando DocumentoDispositivo com structural key/parent key e spans. Reusar LegalTextParser e validação de hierarquia.
2. Não sobrescrever linhas de revisão anterior. Conteúdo mudou: nova extração/revisão, não editar dado aceito.
3. Reconciliação com Dispositivo legado preserva PK e não significa vigência. Manter mapa `(documento_dispositivo_id -> dispositivo_id)` na proveniência técnica.
4. Detectar quoted replacement text e epígrafes repetidas; numeração dentro de redação citada não pode virar indiscriminadamente artigo principal da norma alteradora. Caso não suportado fica flagged.
5. Marker “VETADO” não é conteúdo operativo nem motivo para excluir dispositivo. Criar marker sem inventar o texto que foi vetado.

Aceite: resegmentar não altera versão antiga; quote/span bate; artigo5-A distinto; hierarquia sem ciclos; colofão/anexo fora do artigo final conforme classificação; vetado preservado.
Verificação: pytest novo + parser/hierarchy/device identity e regressões existentes.
Rollback: regra geral; não desfazer proveniência persistida.
Se falhar: não liberar extração para eventos.

### T-011 — Extração de eventos com evidência localizada

Objetivo: associar ação/alvo ao trecho certo, não ao documento inteiro.
Pré-requisitos: T-010.
Arquivos: `src/processing/ner_extractor.py`, `src/processing/event_revision.py`, `src/apps/ingestion/ner_tasks.py`, `src/apps/legislation/models.py`, migration aditiva de eventos, novo `src/tests/test_normative_event_evidence.py`.
Não tocar: transformar score regex em validação; textos fontes.

Passos:

1. Introduzir campos de EventoAlteracao seção3.5. NER devolve action/reference/evidence spans com unidade textual e extractor version.
2. Ampliar padrões de ano por extenso em citações, LC/municipal/federal/estadual, artigos com letras, listas e ranges reusando tests atuais. Não assumir ano do documento para alvo sem ano.
3. Em frase com duas normas/ações, separar quando escopo é inequívoco; caso contrário guardar candidate unresolved, não produto cartesiano.
4. Texto que só cita lei produz REFERENCIA quando há remissão explícita; genérica “disposições em contrário” não produz REVOGA com alvo inventado.
5. Evidence inclui documento/extração/hash/quote/spans. Fingerprint v2 muda quando evidência muda; v1/revisões antigas continuam preservadas e passam por superseding explícito.
6. Referência interna à mesma norma não vira alteração na timeline; anotação pode guardar link interno sem poluir grafo entre normas.

Aceite: LC198→LC55 é referência; decreto orçamentário não regulamenta por tipo; ranges não aplicam parcialmente sem aviso; referência multi-norma ambígua não tem alvo validado; replay não perde decisões.
Verificação: pytest tarefa + test_ner_extractor*, event revision e consolidation safety existentes, usando paths descobertos por rg.
Rollback: regra geral; versão extrator anterior disponível.
Se falhar: eventos novos ficam pendentes sem efeito.

### T-012 — Resolução de alvos tipada e segunda passagem

Objetivo: resolver identidades/hierarquias sem confundir jurisdição ou série.
Pré-requisitos: T-011.
Arquivos: `src/processing/target_reconciliation.py`, `target_resolver.py`, `src/apps/ingestion/task_support.py`, `management/commands/reconcile_targets.py`, `src/tests/test_target_reconciliation.py`, `test_target_resolver.py`, `test_target_resolver_hierarchy.py`.
Não tocar: validar automaticamente eventos, ranking geral/histórico.

Passos:

1. Resolver por identity key e scope; usar compatibilidade legada só para candidato único com tipo/série/ano confirmados. Não filtrar LC somente com icontains `lei_complementar` em labels `Lei Complementar`.
2. Leading zeros tratados pelo contrato T-002; unknown/ano ausente não deduzido por norma fonte. Multiplematches permanece unresolved.
3. Para alvo fora do corpus, guardar target_reference_json/external key; não criar Norma vazia que aparenta ter texto/validade.
4. Resolver dispositivo por structural path incluindo artigo ancestral. Ranges mantêm conjunto e motivos; não escolher `.first()`.
5. Segunda passagem recebe escopo por identidades recém-importadas e limite. Atualiza FK apenas compare-and-set, registra revisão/resultado, não muda validado.

Aceite: norma alvo ingerida depois resolve link sem nova norma fake; federal4320 não liga municipal4320; LC55 !=LO55; inciso sem ancestral não é inventado; pendências mensuradas.
Verificação: pytest alvo/hierarquia; smoke import alteradora antes da alvo no QA.
Rollback: regra geral.
Se falhar: link externo/unresolved permanece explícito.

### T-013 — Revisão jurídica autenticada e auditável

Objetivo: dar ao revisor humano controle real sobre ação, alvo e evidência.
Pré-requisitos: T-012.
Arquivos: novo `src/apps/legislation/event_review.py`, `src/apps/legislation/admin.py`, `review_models.py`, migration se necessária, novo `src/tests/test_event_review_permissions.py`.
Não tocar: bypass auth/CSRF, decisões antigas, atores em APIs públicas.

Passos:

1. Admin de evento apresenta texto literal fonte, documento, dispositivo/target e candidaturas; edit fields validado/provenance ficam read-only fora do serviço.
2. Serviço exige staff + permissão `change_eventoalteracao`, motivo, fingerprint e target; approval por select_for_update; revisão append-only.
3. Aprovar relação não confirma sua data de efeito. Classificar pending/rejected/confirmed e recusar efeito operante se unresolved.
4. Aprovação da revisão anterior não é copiada para extração nova com hash diferente. Superseding preserva todas as decisões antigas.
5. Implementar ação para rejeitar/retirar validação com motivo sem apagar evento. CSRF obrigatório; GET nunca valida.

Aceite: guest403/login; staff semperm403; duplicate submit idempotente; stalefingerprint rejeitado; dados de ator não vazam; revisão negativa retira uso operativo e invalida cache.
Verificação: pytest permissão/concurrency/corpus; browser admin QA com quote e alvo conhecidos.
Rollback: código/flags; revisão jurídica não é deletada.
Se falhar: não permitir efeito automático.

### T-014 — Política de data de efeito por evento

Objetivo: separar publicação de efeito jurídico. Pré-requisito: T-013.
Arquivos: novo `src/processing/event_temporal_policy.py`; `src/processing/temporal_scope.py`; `src/apps/legislation/event_review.py`; novo `src/tests/test_event_temporal_policy.py`; `src/tests/test_temporal_scope_v4.py`, `test_temporal_timeline_v5.py`.
Não tocar: datas reais conflitantes. Esta T-014 não é a tarefa antiga sobre ranking do histórico.

Passos:

1. Retornar data, status, fundamento e motivo por evento; só `confirmed` afeta projeção.
2. Cláusula inequívoca na publicação exige publicação confirmada e registro da cláusula. Outras datas precisam de revisão documentada.
3. REFERENCIA usa publicação para disponibilidade documental, não uma data artificial de efeito modificador.
4. Timeline e queries de revogação usam a política por evento, diferenciando efeito parcial/total/indeterminado.
5. Restauração de redação, suspensão, efeitos condicionais/retroativos e veto rejeitado sem documento suficiente ficam não suportados, sem inferência automática.

Aceite: publicação em janeiro/efeito em março não altera consulta de fevereiro; evento sem data não modifica; fonte pendente não vira vigência confirmada.
Verificação: pytest nos arquivos da tarefa e `src/tests/test_historical_version_contract.py`; boundaries D-1/D/D+1.
Rollback: regra geral e flag história off. Se falhar: estado indeterminado, nunca latest rotulado como histórico.

### T-015 — Projeção temporal e snapshots

Objetivo: reconstruir versões com documentos/eventos revisados. Pré-requisito: T-014.
Arquivos: novo `src/processing/normative_projection.py`; `src/apps/legislation/document_models.py`; migrations de snapshots; `src/processing/consolidation_engine.py`; novo `src/apps/ingestion/management/commands/build_normative_snapshots.py`; `src/apps/ingestion/management/commands/seed_normative_qa.py`; `src/tests/test_normative_qa_seed.py`; novo `src/tests/test_normative_projection.py`; `src/tests/test_historical_version_contract.py`.
Não tocar: overwrite de original, aprovação automática ou efeito de evento pendente.

Passos:

1. Criar snapshots da seção3.5. Base exige documento aprovado e posição temporal conhecida; consolidado atual sem original não reconstrói passado.
2. Selecionar eventos revisados com `effective_on <= as_of`; ordenar por efeito. Empate material conflitante fica pendente, não decidido por PK.
3. Adapter reusa engine para ALTERA/SUBSTITUI/ADICIONA/REVOGA explícitos. REFERENCIA/REGULAMENTA não modificam redação.
4. Proveniência por dispositivo registra base e modificadoras. Revogar artigo afeta descendentes operativos sem apagá-los; revogação total preserva texto histórico.
5. Alvo/redação/data não resolvidos produzem projeção parcial/pendente. `is_active` técnico não reativa texto vetado/revogado.
6. Build: dry-run padrão, IDs permitidos, limite40, guard QA, transação e unique key. Nenhuma escrita em GET.
7. Falta de base suficiente retorna `not_reconstructable`, nunca o texto atual renomeado como histórico.
8. Ampliar o seed de T-009 com os cenários A/B, D-1/D/D+1 e remissão LC definidos no runbook. Seed cria explicitamente revisões sintéticas e snapshots QA, sem afirmar que foram adjudicados por humano. Publicar mapfile para testar T-017/T-018 antes de T-025.

Aceite: D-1 original/D alteração; proveniência distinta; futuro não vaza; mesmos inputs/mesmo hash; incompletude explícita.
Verificação: pytest projection/consolidation safety/historical/temporal; build QA com textos esperados.
Rollback: flag história off, snapshots preservados. Se falhar: não habilitar RAG histórico.

### T-016 — APIs limitadas de relações e versões

Objetivo: contrato seguro sem N+1. Pré-requisito: T-015.
Arquivos: novo `src/processing/normative_graph.py`; novos `src/apps/legislation/relations_api.py`, `document_views.py`, `templates/legislation/document_evidence.html`; `temporal_api.py`, `api_urls.py`, `urls.py` na mesma app; novos `src/tests/test_normative_graph_api.py`, `test_normative_document_access.py`.
Não tocar: rotas antigas/SSE ou serialização de dados privados.

Passos:

1. Implementar seção3.6; validar depth1/2, ações, ISO date e boolean estrito; erros400/404/405.
2. BFS limitado com visited set, dedupe por revisão e prefetch; ciclo A→B→A termina.
3. Público recebe apenas fontes permitidas e relações revisadas; pendentes exigem staff/permissão, sem efeito operativo.
4. Filtro temporal usa efeito para modificadoras e publicação para remissões; desconhecido não é confirmado.
5. Nós externos não têm URL falsa. Version API não grava objetos em GET; cache inclui data/digest/policy/autorização.
6. Implementar as rotas de documento da seção3.6. HTML exibe trecho/texto escapado e identificação da extração; PDF usa FileResponse e storage restrito, com content type e headers apropriados. Guest não lê candidato privado; UUID não substitui autorização. Nunca aceitar path enviado pelo cliente. Provar acesso, 404/403 e impossibilidade de traversal antes de gerar links locais no RAG.

Aceite: limites/truncated corretos, sem futuro ou paths privados; queries não crescem por aresta.
Verificação: pytest API/permissão/queries com1/10/40 nós; budget inicial até12 queries depth2.
Rollback: flag grafo off. Se falhar: erro recuperável, sem falso resultado completo.

### T-017 — Grafo SVG e lista acessível

Objetivo: explorar relações no shell atual. Pré-requisito: T-016.
Arquivos: novo `src/apps/legislation/templates/legislation/_norma_relations.html`; `norma_detail.html`; `src/apps/legislation/views.py`; novos `src/apps/core/static/js/jurix-normative-graph.js`, `src/apps/core/static/css/jurix-normative-graph.css`; novo `tests/js/normative-graph.test.mjs`; `tests/js/run-tests.mjs` só registro.
Não tocar: sidebar/shell base, logos, framework ou tokens globais.

Passos:

1. Carregar ao abrir Relações, sem bloquear leitura; estados vazio/loading/erro com retry preservando filtro.
2. SVG em camadas determinísticas, sem simulação contínua; aria-hidden no desenho e lista HTML equivalente para todas as ações.
3. Nó permite refocar; aresta abre painel com ação, origem/alvo, dispositivo, revisão, data/limitação, trecho e fonte.
4. Agrupar visualmente múltiplos vínculos com contador, mantendo eventos individuais no painel; referência não é alteração.
5. Teclado/Escape/devolução de foco e live region com contagem; não depender de cor/hover/arraste.
6. Lista primária até768px; reflow320px/zoom200%, alvos44px, tokens atuais, fade120–180ms e reduced-motion.

Aceite: evidência real, teclado completo e mobile utilizável; sem SVG bruto/URLs cruas.
Verificação: JS novo e runbook R01–R06; screenshots claro/escuro/larguras e contraste medido.
Rollback: flag off. Se falhar: lista funcional permanece obrigatória.

### T-018 — Timeline e comparação de versões

Objetivo: comparar redações sustentadas por datas. Pré-requisito: T-017.
Arquivos: `src/apps/legislation/temporal_api.py`, `views.py`; templates `norma_compare.html`, `norma_detail.html`; `src/processing/legal_diff.py`; `src/apps/core/static/js/jurix-legal-detail.js`, `src/apps/core/static/css/jurix-legal-detail.css`; novo `src/tests/test_normative_version_compare.py`.
Não tocar: textos originais ou transformação de HTML recebido em fonte oficial.

Passos:

1. Preservar compare route; validar from_as_of/to_as_of ou oferecer snapshots disponíveis.
2. Diff por structural key, com adicionado/removido/alterado/vetado em texto/ícone além de cor.
3. Timeline separa publicação, efeito, republicação e pendência; informa corpus/cobertura e “consolidação do Jurix”.
4. Datas na URL; reload/back restaura. Versão ausente explica limite, sem exibir latest como passado.
5. Links por dispositivo/versão continuam; exportação/cópia não fingem redação oficial.

Aceite: diferenças esperadas D-1/D, parcial explícito e atalhos antigos sem regressão.
Verificação: pytest compare/legal_diff; runbook R07–R10, teclado/mobile/reload.
Rollback: regra geral/flag história. Se falhar: não oferecer datas com dados falsos.

### T-019 — Recuperação temporal por versão

Objetivo: recuperar texto compatível com as_of. Pré-requisito: T-018.
Arquivos: novo `src/processing/temporal_retrieval.py`; `adaptive_retrieval.py`, `adaptive_rag_service.py`, `rag_context_builder.py`, `rag_cache_helpers.py` em src/processing; novo `src/tests/test_normative_snapshot_retrieval.py`; `src/tests/test_temporal_retrieval_v5.py`.
Não tocar: modelo LLM, ranking do histórico ou top-k global.

Passos:

1. Identidade+as_of seleciona snapshot elegível; adapter expõe texto/proveniência sem mutar objetos legados.
2. Sem embedding por versão neste ciclo: lexical limitado sobre texto histórico, não embedding do texto atual.
3. Pergunta temática histórica não suportada informa cobertura/abstenção; nunca relaxa data para latest.
4. Preservar norma inteira adaptativa e coverage; pequena cobre relevantes, grande explicita amostragem/budget.
5. Cache inclui as_of/snapshot/version/digest/policy. Vetado/revogado só como evidência de história/status, não obrigação atual.

Aceite: passado usa texto anterior; ausência de original não recebe latest; fontes/coverage honestas.
Verificação: pytest novo+temporal+adaptive+whole-norma existentes com provider mock.
Rollback: flag história off preservando abstenção segura. Se falhar: bloquear recuperação histórica incorreta.

### T-020 — RAG assistido por relações

Objetivo: contexto jurídico pertinente e limitado. Pré-requisito: T-019.
Arquivos: novo `src/processing/graph_retrieval.py`; `normative_query.py`, `adaptive_rag_service.py`, `rag_context_builder.py`, `rag_prompt.py`; novo `src/tests/test_graph_assisted_rag.py`.
Não tocar: URL gerada por LLM, confiança jurídica percentual ou grounding desligado.

Passos:

1. Reusar provision/overview; adicionar relação/história explícitas, sem classificador LLM obrigatório.
2. Semente da norma/fontes baseline; expansão1hop, até8 evidências adicionais dentro do budget total.
3. Priorizar dispositivo, versão, modificadora e remissão útil. Citar alvo sem recuperar seu texto não sustenta afirmação sobre ele.
4. Registrar fontes adicionadas/descartadas com motivo e event path; mais fontes não aumentam confiança automaticamente.
5. Prompt conversacional, conteúdo/versão/marcadores, sem URLs/HTML ou seção para cada artigo.
6. Flag off reproduz baseline; falha do grafo usa fallback temporal compatível ou abstenção.

Aceite: “quem alterou art.5?” traz evento/evidência; vizinho irrelevante não entra; remissão não vira alteração.
Verificação: pytest graphRAG/query/grounding e runbook R11–R14; comparar flags com fontes registradas.
Rollback: flag RAG grafo off. Se falhar: não aumentar todos os limites para esconder seleção errada.

### T-021 — Citações e cópia por versão

Objetivo: proveniência consistente em streaming/histórico/clipboard. Pré-requisito: T-020.
Arquivos: `src/apps/legislation/serializers.py`, `source_urls.py`; `src/processing/answer_contract.py`; JS `jurix-markdown.js`, `jurix-rag.js`, `jurix-chat-controller.js` em src/apps/core/static/js; novo `src/tests/test_versioned_citation_contract.py`; novo `tests/js/versioned-citations.test.mjs`; `tests/js/run-tests.mjs`.
Não tocar: nomes SSE/identidade do turno, paths privados em URLs ou validação final.

Passos:

1. DTO aditivo seção3.6; ID estável por evidência; fallback legado explícito; nenhum SAPL ID inventado.
2. Norma abre base sem marca; dispositivo usa fonte confirmada com trecho ou âncora local versionada; fragmento não usa preview truncado.
3. Resolver [[n]] pelo conjunto daquele turno; marcador inválido não aponta para outra fonte.
4. Clipboard gera Markdown das mesmas URLs/versões; histórico e F5 preservam DTO, sem HTML cru/secrets.
5. Sources recebidas são associadas imediatamente; fade no primeiro aparecimento, abertura durante streaming; done não duplica/reconstrói tudo.
6. Finalização pode abster/corrigir com feedback honesto. Insuficiência nunca escondida por resposta plausível; descartadas não aparecem como usadas.

Aceite: clique/cópia/F5/version corretos; fontes sem F5; sources→chunk→done sem duplicação; cópia parcial identificada.
Verificação: pytest DTO/answer/history/streaming, JS novo/security/streaming, runbook R15–R18.
Rollback: regra geral preservando campos legados. Se falhar: fonte legada limitada, não hyperlink errado.

### T-022 — Temas e coleções

Objetivo: afinidade temática distinta de efeito jurídico. Pré-requisito: T-021.
Arquivos: novo `src/processing/normative_topics.py`; novo `src/apps/legislation/topic_models.py`; `models.py`, migration nova, `workspace_views.py`, template `workspace/search.html`; novo `src/tests/test_normative_topics.py`.
Não tocar: permissões/propriedade de coleções ou EventoAlteracao para temática.

Passos:

1. Topic/NormaTopic comcode estável, origem manual/rule/semantic, candidate/confirmed e versão; educação/saúde/ambiente/urbanismo/orçamento/servidor/tributário iniciais.
2. Tags automáticas são candidatas; assunto ambiental em orçamento não significa regulamentação ambiental.
3. Assuntos relacionados separados de relações jurídicas; similaridade limitada sob demanda, sem materializar todos os pares O(N²).
4. Coleções continuam privadas por usuário; salvar norma não muda tema oficial/efeito legal.
5. Filtros combinam tema/scope/data; histórico mantém ranking atual.

Aceite: tema não altera redação, coleção privada e candidato rotulado.
Verificação: pytest topics/collections/workspace e runbook R19–R20.
Rollback: controles off/dados preservados. Se falhar: pesquisa legal independente.

### T-023 — Catálogo SAPL e sincronização

Objetivo: tipos corretos e mudanças detectáveis sem falsa completude. Pré-requisito: T-022.
Arquivos: novo `src/clients/sapl/sapl_types.py`; `sapl_client.py`, `sapl_normas.py`; `src/apps/ingestion/core_tasks.py`, `sapl_sync.py`, `task_support.py`; novos `src/tests/test_sapl_type_catalog.py`, `test_sapl_document_sync.py`; testes existentes de sync.
Não tocar: endpoint configurado ou crawler genérico do DOM.

Passos:

1. Descobrir catálogo Natal via API/read-only, sem presumir path. Se indisponível, mapping explícito revisado; unknown preservado.
2. Guardar code/label originais e série por instalação; falha do catálogo não transforma tudo em Lei.
3. Conflito com revisão humana entra em fila; semântica de campo data SAPL precisa confirmação antes de chamar publicação.
4. Janela recente é heurística. Detectar página repetida/ordenação incerta e partial; next validado por host.
5. PDF-only change: ETag/LastModified quando disponíveis; caso contrário sweep limitado de bytes/hash.
6. Full scan só marca ausentes após cobertura provada e sem erro; nunca delete/complete por limite.
7. Job diário recente e sweep semanal retomável com até50 documentos/batch, sem ativar beat real.

Aceite: old/PDF-only changes detectados em fixtures; unknown não genérico; repeatedpage não certifica fullscan; falha conserva cursor.
Verificação: pytest sync/type/document; requests reais read-only limitados de catálogo/metadados.
Rollback: novos jobs off/leases preservados. Se falhar: freshness não confirmada.

### T-024 — Impacto e filas limitadas

Objetivo: atualizar alvos sem backlog descontrolado. Pré-requisito: T-023.
Arquivos: novos `src/apps/ingestion/normative_impact.py`, `normative_tasks.py`; `tasks.py` só export; `src/apps/operations/models.py`, migration workitem; `config/celery.py`, `config/settings_normative_qa.py`; novo `src/tests/test_normative_impact_queue.py`.
Não tocar: beat/config produção ou reescrita das tasks antigas.

Passos:

1. Workitem dedupe identidade/revisão/stage, lease e pipeline changed→extração→review→segment/event→reconcile→snapshot/invalidate.
2. Documento candidato aguarda revisão; evento aprovado/rejeitado afeta alvo; visited set encerra ciclos, só modificadoras propagam redação.
3. Queue normative_qa, concurrency1/poolsolo, batch<=10/checkpoint/retry limitado; não disparar6.663 jobs.
4. Completed/awaiting_review/failed/cancelled e retry manual; cancelamento preserva fonte e nunca marca parcial como completo.
5. Embedding só de fonte aprovada com compare-and-set; sem Ollama informar etapa dependente, sem travar grafo/leitura.
6. Invocação manual QA, sem beat real; invalidação por lote T-007.

Aceite: concorrência/idempotência/crash/ciclo testados; pending não altera texto; import não roda no processo de chat.
Verificação: pytest queue/bounded/embedding; worker real QA e interrupção somente do processo próprio.
Rollback: flags off/parar worker QA identificado, manter checkpoints. Se falhar: sem ativação real.

### T-025 — Piloto técnico e anotação humana

Objetivo: casos difíceis e amostra revisável. Pré-requisito: T-024.
Arquivos: `src/apps/ingestion/management/commands/seed_normative_qa.py`, `build_pilot_manifest.py`, `src/tests/test_normative_qa_seed.py`; `benchmarks/corpus/municipal_natal/graph-evaluation-protocol.md`.
Não tocar: gold fictício, metas20/150–200 ou corpus real.

Passos:

1. Ampliar o seed iniciado em T-009/T-015: namespace próprio, hashes e mapfile dos IDs; segunda execução no-op, guard obrigatório. Não criar outro seeder paralelo.
2. Casos: LC referencia LC, LO homônima, ALTERA datada, revoga inciso/total, adiciona5-A, genericrevocation, federalexternal, vetado, multiactions, republicação/retificação, original ausente, futuro e conflito.
3. Decisões sintéticas têm synthetic_fixture e não contam como20 humanas nem são exportadas como gold real.
4. Selecionar40 PDFs porhash/entry com estratos/roles/motivo;30–50 apenas se justificado; não aprovar conflito automaticamente.
5. Build manifest v2 opt-in, v1 compatível; exportar20 normas candidatas para revisão, nunca aprovação.

Aceite: guard/idempotência/map funcionam; negativos presentes; documentos não contados como normas humanas distintas.
Verificação: pytest seed/municipal; gatehumano3 enquanto faltar revisão.
Rollback: código/flags. Se falhar: browser não usa PK arbitrário de dados reais.

### T-026 — Métricas de extração/relações

Objetivo: precisão sem autocertificação jurídica. Pré-requisito: T-025 e gold humano para resultados científicos.
Arquivos: novo `scripts/evaluate_normative_graph.py`; `scripts/evaluate_municipal_v1.py` só adapter; novo `src/tests/test_normative_graph_evaluation.py`; protocolo graph.
Não tocar: resultados anteriores ou ajuste de threshold no conjunto de teste.

Passos:

1. Runner offline valida gold/pred, keys, hashes e splits; nenhum SAPL/LLM/writeDB.
2. Accuracy tipo/série/número/ano, abstenção e precisão/recall de conflitos; ato diferente de publicação não é erro automático.
3. Events por chave/span/ação/alvo, não posição; missing/extra FN/FP, reorder invariável; unresolved e matriz por ação.
4. Separar extração, resolução e efeito confirmado; fixtures validam matemática, não accuracy jurídica.
5. Sem adjudicação: not_evaluated/exit3; manter20 normas humanas gate.

Aceite: reorder invariável e falso vínculo FP; sem acerto artificial por abstenção.
Verificação: pytest evaluation/municipal; fixtures correct/wrong/empty/unreviewed e hashes.
Rollback: regra geral. Se falhar: não divulgar0/100 como estudo concluído.

### T-027 — Experimento RAG comparativo

Objetivo: medir ganho/custo. Pré-requisito: T-026, corpus/model/hardware identificados e gold humano para ciência.
Arquivos: novo `scripts/run_normative_rag_experiment.py`; novo `src/tests/test_normative_rag_experiment.py`; protocolo graph; novos schemas de cases/predictions em benchmarks/corpus/municipal_natal.
Não tocar: enfraquecer baseline/baixar modelos automaticamente.

Passos:

1. Braços baseline, +relações, +relações+tempo; mesmos corpus/model/temperature/budget/hardware, diferenças documentadas.
2. Estratos artigo/norma/alteração/tema/história/externo/sem evidência; sem gold apenas smoke técnico.
3. Recall/MRR IDs, precisão de versão/citação, suporte/abstenção humanos, erro temporal e retrieval/TTFT/final/n; n pequeno não estima p95.
4. Cache cold/warm separados, policy/revision/embedding registrados; repeats mecânicos e variação LLM mensurada.
5. Split por cadeia de relações; versões/normas ligadas não vazam entre ajuste/teste; congelar antes de calibrar.
6. Até12 consultas reais QA iniciais; expansão científica após revisão, não LLM-as-judge.

Aceite: braços equivalentes, fontes rastreáveis e limites honestos.
Verificação: pytest/fakeprovider e Ollama real limitado.
Rollback: flag off/reports preservados. Se falhar: sem comparação de braço não executado.

### T-028 — Escala, segurança e resiliência

Objetivo: provar limites antes de ingestão ampla. Pré-requisito: T-027.
Arquivos: novo `scripts/benchmark_normative_pipeline.py`; novo `src/tests/test_normative_pipeline_limits.py`; `scripts/architecture_budget_v2.py` só novos módulos; `scripts/README.md`.
Não tocar: budgets legados ou relaxamento de segurança.

Passos:

1. Bench1/10/40/300/1000 entidades sintéticas QA: queries/tempo/memória/rows/cache. Sem ZIP inteiro.
2. Graph40nodes/80edges<=12 queries;20requests após warmup, p50server alvo300ms; falha hardware reportada, não passed falso.
3. ZIP slip/bomb/truncado/cifrado/symlink, XSS em quote/ementa, SSRF/redirect, IDOR/CSRF/double/stale approval.
4. Nenhum HTML recebido trusted; URL/downloader valida host/redirect/limits; paths privados nunca href.
5. Falhas serviços só em infraestrutura QA própria; mocks quando isolamento não existir, identificados.
6. JS+CSS novos do grafo<=45KiBraw; nenhuma dependência pesada; nada O(N²) ou invalidação por aresta.
7. Novos módulos orçamento350linhas; dividir por responsabilidade sem mudar budgets antigos.

Aceite: limites/segurança/métricas reais, sem perda de dados.
Verificação: pytest security/limits, architecturebudget, benchmark e suites completas; check--deploy é advisory QA.
Rollback: flags off/reports preservados. Se falhar: bloquear ingestão/ativação ampla.

### T-029 — Uso real pós-implementação

Objetivo: auditar app inteiro, não somente HTML/mock. Pré-requisito: T-028, QA8007/mapfile/browser.
Arquivos: novo `tests/js/normative-product-smoke.mjs`; `tests/js/package.json` só scriptdev; novos artefatos em docs/research/evidence/normative-graph/<run-id>/.
Não tocar: código para esconder falha visual sem tarefa nova, chats reais ou auditorias anteriores.

Passos:

1. Puppeteer existente, baseURL QA explícita/mapfile; recusar host remoto.
2. Viewports320/360/768/1280/1920 e zoom200 separado, claro/escuro; registrar método de zoom.
3. Perguntas com Ollama real sobre norma/artigo/follow-up/alteração/história; mocks só faults/SSEordering e rotulados.
4. Teclado/Escape, grafo/painel, copy/F5/back, busca/coleções; console/network sanitizados.
5. Screenshot só fixture/texto normativo permitido; achado com reprodução, viewport, evidência e arquivo.
6. Executar R01–R24; indisponibilidade é não executado, não passed.

Aceite: zero falhas centrais; scroll/sidebar/composer/drawer sem regressão; citações/fontes semF5; keyboard sem trap; mock/real separados.
Verificação: smoke novo, suites JS e inspeção manual runbook.
Rollback: evidências preservadas. Se falhar: tarefa estreita de correção e reteste+regressões.

### T-030 — Entrega e operação

Objetivo: implementação verificável/ativação controlada. Pré-requisito: T-029.
Arquivos: README.md mesma estrutura; scripts/README.md; benchmarks/corpus/municipal_natal/README.md; novos docs/research/NORMATIVE_GRAPH_DELIVERY.md e NORMATIVE_GRAPH_OPERATIONS.md; progressdoc.
Não tocar: branches/push/merge ou claims de compliance completa.

Passos:

1. Documentar flags/rotas/comandos/limites e projeção Jurix versus texto oficial.
2. Testes/diffs/gates de licença/gold/tempo/cobertura; software pronto não implica experimento avaliado.
3. Plano real separado: backup/restoretest, dryrun/matching, allowlist, migration review, lote20/50 e ativação gradual; não aplicar aqui.
4. Rollback flags/filas preserva documentos; revert código não restaura DB; restore exige autorização própria.
5. Git conserva mudanças preexistentes; stage não inclui HTTPlogs/GOAL/PDFs/secrets; commit apenas autorizado.
6. Entregar URLQA/HEAD/config sanitizada; porta aberta não prova versão atual.

Aceite: documentação factual/reprodução e pendências claras, nenhuma operação real.
Verificação: documentationcontract/check/suites finais/links/CLIhelp/Git.
Rollback: documentação própria. Se falhar: não anunciar pronto para produção.

## 7. Protocolo de reporte por tarefa

Atualizar `NORMATIVE_IMPLEMENTATION_PROGRESS.md` sem segredos:

```text
Tarefa: T-###
Estado: não iniciada | em andamento | concluída | bloqueada
HEAD/branch inicial e final:
Arquivos alterados:
Mudança observável:
Testes antes: comando, exit code, passed/failed/skipped
Testes depois: comando, exit code, passed/failed/skipped
Runtime: real | mock | não executado (motivo)
Evidências: paths relativos sem dados privados
Gate/revisão jurídica: cumprido | pendente | não aplicável
Commit: hash ou não autorizado
Próxima tarefa elegível:
```

Não copiar logs inteiros com credenciais. Cada etapa tem status independente: software, QA, revisão humana, importação operacional e resultado científico.

## 8. Critérios finais de aceite

- Nenhum arquivo recebido foi executado; nenhum PDF original foi alterado.
- Identificação de tipo/série/número/ano funciona sem LLM e com abstenção em conflito.
- Original/republicação/retificação/anexo não se fundem sem revisão.
- Evidência literal tem documento/extração/hash/span; vínculo explícito é diferente de afinidade temática.
- Aprovação autenticada, compare-and-set e append-only; pendência não modifica norma.
- Textos vetados/revogados preservados; efeitos incertos permanecem indeterminados.
- Snapshot não inventa original perdido; consultas históricas não mostram texto futuro.
- Grafo, lista móvel e teclado funcionam; cor não é o único indicador.
- Citações, clipboard, fontes, streaming, histórico e F5 preservam documento e versão.
- Sync detecta alterações de payload/PDF; scan incompleto não declara ausência ou completude.
- Lotes idempotentes, leases, concorrência, interrupção e retry verificados.
- Performance/latência medidas com método; estimativas não rotuladas como medições.
- Experimento congelado/adjudicado ou `not_evaluated`;20 normas humanas continuam o gate científico.
- Contratos Python/JS/security passam, ou falhas preexistentes são documentadas sem alegação de sucesso.
- Roteiro browser executado no aplicativo real QA, não apenas fixtures HTML.
- Base/Git reais preservados; ativação operacional exige aprovação própria.

## 9. Referências primárias e uso

- [LC95/1998, texto compilado](https://www.planalto.gov.br/ccivil_03/leis/lcp/lcp95compilado.htm): estrutura, identificação das alterações e preservação das indicações de dispositivos. É referência de técnica legislativa; não automatizar interpretação de toda regra municipal com base nela.
- [SAPL Natal, tramitação de vetos e promulgação](https://sapl.natal.rn.leg.br/materia/pesquisar-materia?ano=2024&materiaassunto_null=true&page=6): exemplos oficiais de veto derrubado e posterior promulgação; consultar documentos próprios da norma antes de inferir seu estado.
- [Django5.2 — transações](https://docs.djangoproject.com/en/5.2/topics/db/transactions/): atomicidade e fronteira on_commit.
- [Celery5.4 — tasks](https://docs.celeryq.dev/en/v5.4.0/userguide/tasks.html): implementação deve consultar versão instalada5.4; leitura geral stable não autoriza usar features posteriores.
- [PyMuPDF — OCR](https://pymupdf.readthedocs.io/en/latest/recipes-ocr.html): custo do OCR e aproveitamento de texto nativo. Conferir APIs com PyMuPDF1.28.2 instalado antes de editar.
- [Python — zipfile](https://docs.python.org/3/library/zipfile.html): tratamento de ZIPs não confiáveis; validar limites/paths além da biblioteca. Usar APIs disponíveis noPythonlocal, não presumir3.14.
- [WCAG2.2](https://www.w3.org/TR/WCAG22/): teclado, contraste, reflow, foco e alvos. Exige verificação por critério, não selo por existência deCSS.
- [AppleHIG — layout](https://developer.apple.com/design/human-interface-guidelines/layout): referência de hierarquia/layout; conteúdo textual completo não foi recuperado pelo navegador de pesquisa nesta elaboração. Não declarar conformidadeHIG auditada.

## 10. Prompt inicial para o Luna

```text
Implemente o plano de acervo, grafo normativo e RAG temporal do Jurix.
Use esforço alto. Leia integralmente:
1. docs/research/JURIX_NORMATIVE_GRAPH_IMPLEMENTATION_PLAN.md
2. docs/research/JURIX_NORMATIVE_GRAPH_TEST_RUNBOOK.md
Comece por T-001 e avance uma tarefa por vez, cumprindo os gates.
Mantenha o checkout/branch atuais e preserve alterações preexistentes.
Você pode editar os arquivos previstos, testar e operar apenas o ambiente QA.
Não use banco real para migrations, ingestão, revisão sintética ou testes destrutivos.
Não execute arquivos do ZIP; não invente relações, datas, URLs oficiais ou revisão humana.
Não faça push, merge ou commit sem autorização específica do usuário.
Não encerre declarando funcional sem testar os fluxos do runbook no aplicativo real.
Quando houver bloqueio humano/jurídico, marque-o; não tente certificá-lo com o LLM.
Reporte testes reais, limitações, URL do QA, tarefas concluídas e próximas elegíveis.
```
