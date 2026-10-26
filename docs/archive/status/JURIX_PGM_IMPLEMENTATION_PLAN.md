# Jurix — plano de implementação para o piloto PGM

Estado de referência: 07/10/2026, checkout `C:\Jurix`, branch `main`, HEAD `ab6c172` **com alterações locais preexistentes**. Ler antes a avaliação `JURIX_PGM_READINESS_ASSESSMENT_2026-10-07.md`, o plano de grafo original e seu runbook. Este documento complementa, não apaga, os gates anteriores.

Executor recomendado: **Luna em raciocínio alto**, uma tarefa por vez. Revisão técnica adicional nas tarefas de temporalidade, cadastro/promoção, cobertura e isolamento. Uma implementação extensa não dispensa revisão jurídica humana.

## Produto-alvo e fronteiras

Fluxo principal: assessor cola trecho de fundamentação → confirma normas/dispositivos detectados e datas → vê quais referências mudaram → abre ato modificador e texto antes/depois → exporta referências verificáveis → salva dossiê opcional. Pesquisa temática e grafo levam ao mesmo serviço de evidências. Assistente explica os resultados; não decide a regra aplicável ao processo.

MVP útil: biblioteca progressiva de PDFs autênticos, pelo menos 20 normas adjudicadas em três cadeias reais, conferência de texto, comparação temporal e citações de PDF. Não esperar que milhares de normas sejam revisadas para permitir pesquisa documental. Não afirmar que esse MVP cobre décadas integralmente.

Fora do primeiro ciclo: revogação tácita automática, avaliação de precedente vinculante, elaboração/assinatura de peça, integração a sistema processual, upload de Word com macros, coleta de dados confidenciais e envio de peças a modelos externos. Esses itens exigem decisões próprias.

## Regras de execução e verificação

1. Registrar branch, HEAD, `git status --short`, index e diff antes de cada tarefa. O baseline é dirty: não parar só porque há alterações conhecidas; identificar seus proprietários e não incorporá-las ao escopo. Se sobreposição for ambígua, parar e perguntar.
2. Não reset/clean/stash, trocar branch, promover dados reais, sincronizar remoto, commit/push/merge sem autorização nova. Uma tarefa corresponde a um diff atômico; **este plano não autoriza commits**. Se autorizados posteriormente, um commit por tarefa, sem misturar o baseline.
3. Usar `apply_patch`. Não reescrever módulos inteiros nem enfraquecer testes para fazê-los passar. Nenhuma dependência nova nesta fase, salvo decisão explícita registrada.
4. Reproduzir o problema antes; teste focal antes/depois e regressão integral por gate. Conferir comportamento no navegador com PDF real público além das fixtures sintéticas. Não promover dados com um script de teste.
5. Arquivos novos indicados abaixo devem ser criados somente se ausentes. Migrations: inspecionar as existentes; gerar o próximo número livre com Django, nunca adivinhar número nem editar migration aplicada. Incluí-las no diff da tarefa e no teste QA.
6. **Não tocar**, em todas as tarefas: `.env`, arquivos ZIP/PDF originais, banco/volumes reais, configurações pessoais, credenciais, documentos de auditoria anteriores, gold adjudicado congelado ou alterações não relacionadas. Exclusões adicionais abaixo reforçam esta regra.
7. Comandos novos devem ganhar allowlist específica e testes em `scripts/normative_qa.py` / `src/tests/test_normative_qa_guard.py`; não permitir shell genérico nem banco arbitrário para contornar restrições.
8. Rollback comum: se houver commit autorizado, reverter exclusivamente o commit da tarefa; sem commit, reverter apenas seus hunks após conferir o diff contra o baseline. Alteração de schema/dados exige plano próprio e restauração QA ensaiada; nunca apagar histórico documental para desfazer UI.
9. **Se falhar**, regra para todas as tarefas: parar, registrar comando/erro sanitizado, diff e causa; não improvisar migração de banco, inferência jurídica ou redução dos critérios. Dependentes ficam bloqueadas até revisão.

### Comandos comuns

Usar venv existente. Configurar variáveis **só no processo PowerShell**, mantendo `.env` intacto. Selecionar o diretório QA validado pelo runner; não presumir que a pasta temporária desta avaliação continue existindo.

```powershell
$env:JURIX_QA_ONLY='1'
$env:JURIX_QA_ROOT='<diretorio QA existente validado sob TEMP>'
./.venv/Scripts/python.exe scripts/normative_qa.py --check
./.venv/Scripts/python.exe scripts/normative_qa.py --run python manage.py check
./.venv/Scripts/python.exe scripts/normative_qa.py --run python -m pytest -q --tb=short
./.venv/Scripts/python.exe scripts/normative_qa.py --run npm test --prefix tests/js
./.venv/Scripts/python.exe scripts/normative_qa.py --run python scripts/architecture_budget_v2.py
./.venv/Scripts/python.exe scripts/normative_qa.py --run python scripts/validate_documentation_contract.py
```

Teste focal **F(paths)** abaixo significa o mesmo comando QA `python -m pytest -q --tb=short` seguido dos caminhos indicados. Lint **L(paths)**: `./.venv/Scripts/python.exe -m ruff check` seguido dos arquivos alterados. JS **J**: suíte `npm test --prefix tests/js` pelo runner. Não executar `migrate` fora da QA; primeiro `migrate --plan`. Para browser, ler como os smokes atuais recebem base URL/fixture map e apontar para a QA corrente, não para uma porta antiga.

## Fases e gates

- **Fase A — respostas honestas e acervo progressivo (P-001 a P-005).** Resolver pergunta sobre mudanças, tipo legado e caminho de ingestão/cadastro. Gate: arquivo inteiro inventariado e staging retomável; nenhum PDF pendente recebe selo de vigência. Risco principal: confundir identidade sugerida com aprovada.
- **Fase B — cadeia real e cobertura (P-006 a P-010).** Curadoria, edições, pipeline, reconciliação e temporalidade. Gate: ao menos uma cadeia real de cada cenário prioritário, com revisão, datas e antes/depois verificáveis. Risco: falta de original/evento interpretada como permanência.
- **Fase C — uso efetivo da PGM (P-011 a P-016).** Busca, exploração, conferência, exportação e dossiê. Gate do MVP: 20 normas reais revisadas em três cadeias; conferir cinco fundamentações públicas, inclusive referência superada e caso inconclusivo. Risco: selecionar automaticamente data de aplicação.
- **Fase D — atualização e assistente integrado (P-017 a P-019).** Diário Oficial, operação incremental e resposta natural. Gate: replay/retomada de edições ordinária e especial sem duplicação ou efeito jurídico automático. Risco: fonte indisponível escondida por resposta plausível.
- **Fase E — prova e piloto (P-020 a P-023).** Gold, experimento, usuários, privacidade e entrega. Gate: métricas publicadas com limites, restauração ensaiada e avaliação da PGM. Risco: chamar QA técnico de produção ou validade científica.

Ordem global: P-001 → P-023. Gates humanos podem ocorrer paralelamente às tarefas independentes, mas não podem ser simulados pelo executor. Dependências específicas prevalecem sobre essa ordem. Notas 9–10 exigem os gates finais, não só fechamento de tickets.

## Tarefas atômicas

### P-001 — perguntas de alteração não podem virar simples transcrição

Achados: PGM-01, PGM-04. Objetivo: manter a intenção relacional em todos os caminhos do assistente. Pré-requisitos: QA/Ollama para runtime; nenhum cadastro aprovado necessário para o caso inconclusivo.

Arquivos: `src/processing/normative_query.py`, `src/processing/qa_archive_rag.py`, `src/processing/rag_answer_pipeline.py`, `src/tests/test_normative_query.py`, `src/tests/test_qa_archive_rag.py`, `src/tests/test_rag_answer_pipeline_streaming.py`.
Não tocar: ranking do histórico, schema e guardrails de revisão, além das exclusões comuns.

1. Reproduzir a pergunta do art. 18 da LC120/2010 da avaliação; registrar intenção classificada e caminho usado sem logar peça do usuário.
2. Classificar “foi alterado”, “houve alteração”, “foi revogado”, “ainda vigora”, “redação em data” e combinações como consulta de cadeia, mesmo quando há artigo explícito. Preservar `relation_intent` na seleção de estratégia.
3. Se somente o PDF de origem estiver disponível, responder primeiro: não é possível confirmar mudanças posteriores no acervo verificado. O excerto pode aparecer em seguida como texto daquele documento, sem confiança de vigência.
4. Quando existirem relações revisadas, encaminhar ao serviço temporal existente. Não deduzir ausência de mudanças de `results=[]` nem usar LLM para preencher eventos ausentes.

Aceite: pergunta original não recebe somente transcrição; evento inexistente não vira “não houve alteração”; SSE/citações de excerto continuam funcionais; caso confirmado usa fonte do ato modificador.
Verificação: F(três testes acima); L(três módulos); browser pergunta original + artigo simples + relação fixture confirmada. Rollback: regra comum, apenas classificação/roteamento próprios.

### P-002 — resolver espécies legadas com proveniência

Achado: PGM-03. Objetivo: eliminar enumeração universal incorreta de IDs SAPL. Pré-requisito: P-001.
Arquivos: `src/apps/legislation/models.py`, `src/clients/sapl/sapl_types.py`, `src/apps/legislation/serializers.py`, `src/tests/test_sapl_type_catalog.py`; novo `src/tests/test_norma_type_display.py`.
Não tocar: valores persistidos em massa, catálogo externo, migration de tipos.

1. Trocar o mapeamento local do getter por resolução baseada em identidade textual/catalogada do registro; catálogo de origem ausente + ID desconhecido → “Tipo não identificado”, preservando código bruto em metadado.
2. Acrescentar testes para catálogo Natal: 3 Resolução, 5 Decreto Legislativo, 6 Emenda; outro catálogo com IDs diferentes; decreto executivo textual; ausência de catálogo. Não universalizar os códigos observados.
3. Garantir que template e serializer usem o mesmo resolver. Não inferir espécie pelo assunto ou aparência do nome.

Aceite: representação coerente; tipo incerto não é Lei por default; Decreto e Decreto Legislativo distintos. Verificação: F(testes acima, `src/tests/test_workspace_routes.py`); L(arquivos Python). Rollback: regra comum, sem transformação de registros.

### P-003 — inventário completo e staging retomável, sem limite global de 40

Achados: PGM-02, PGM-07. Objetivo: ingerir progressivamente o ZIP autêntico em área de staging controlada. Pré-requisito: P-002; armazenamento QA suficiente.
Arquivos: `src/processing/archive_inventory.py`, `src/apps/ingestion/archive_import.py`, `src/apps/legislation/document_models.py`, `scripts/inventory_normative_archive.py`, `scripts/normative_qa.py`, `src/tests/test_archive_inventory.py`, `src/tests/test_archive_import.py`, `src/tests/test_normative_qa_guard.py`; novos `src/apps/ingestion/corpus_staging.py`, `src/apps/ingestion/management/commands/stage_normative_corpus.py`, `src/tests/test_corpus_staging.py`; migration gerada se cursor persistido exigir campo novo.
Não tocar: cap do comando `import_normative_archive` QA atual, `.env`, arquivos originais e aprovação jurídica.

1. Inventariar todos os membros sem executar DLL/Python nem extrair paths arbitrários; guardar hash do ZIP, hash por PDF, tamanho, membro, falhas e contador por extensão.
2. Criar comando novo com `--dry-run`, `--manifest`, cursor persistido, `--batch-size` máximo 20, orçamento de bytes/tempo e `--resume`. Não usar `rows[:40]` como população total. Relatar selecionados/processados/restantes/falhas separados.
3. Importar documentos pendentes em lotes; OCR/extração posterior. Igual hash não duplica blob; igual norma com edição diferente não desaparece. Validar zip traversal/bombas, limites expandidos e saída exclusivamente no staging.
4. Testar lote maior que 40 em fixtures e retomar após interrupção. No arquivo real, começar com manifesto integral e dois lotes pequenos; jamais declarar milhares processados após um lote.

Aceite: todos os PDFs contabilizados; retomar sem duplicação; estado `partial` até fim/falhas tratadas; zero norma consolidada criada por staging. Verificação: F(todos testes indicados), inventário/dry-run com saída QA e reconciliação total. Rollback: interromper execução e preservar documentos/manifesto; regra comum para código.

### P-004 — registrar norma ausente após identidade aprovada

Achado: PGM-02. Objetivo: criar vínculo jurídico sem exigir Norma preexistente nem inventar sapl_id. Pré-requisito: P-003; revisão humana da identidade de um documento.
Arquivos: `src/apps/ingestion/document_promotion.py`, `src/apps/legislation/models.py`, `src/apps/legislation/review_models.py`, `src/tests/test_document_promotion.py`; novos `src/apps/ingestion/norma_registry.py`, `src/tests/test_norma_registry.py`; migration gerada somente para restrição faltante.
Não tocar: bypass de aprovação, texto consolidado e importador SAPL.

1. Implementar `register_reviewed_identity(document_id, reviewer, reason, fingerprint)` com autorização explícita, estado/condição de uso e fingerprint atuais.
2. Identidade inclui jurisdição, espécie/série, número normalizado e ano; usar chave canônica existente. Conflito com unique legado ou identidade divergente bloqueia; não mesclar pelo número apenas.
3. Transação/lock: procurar por identidade aprovada, criar pendente se ausente, preservar `sapl_id=None`, vincular documento; segundo submit concorrente retorna mesmo resultado. Promoção/consolidação permanece operação distinta.

Aceite: cadastro sem SAPL; concorrência/idempotência; desconhecido/conflito/usuário comum bloqueados. Verificação: F(testes acima, `src/tests/test_normative_document_models.py`), migrations plan/check em QA. Rollback: preservar revisão e vínculo; reversão de dado só após análise autorizada.

### P-005 — cobertura explícita do corpus e corte de atualização

Achados: PGM-04, PGM-08. Objetivo: diferenciar execução completa, acervo revisado e período documental coberto. Pré-requisitos: P-003/P-004.
Arquivos: `src/apps/operations/models.py`, `src/processing/rag_contract_helpers.py`, `src/apps/legislation/relations_api.py`, `src/tests/test_normative_snapshot_retrieval.py`; novos `src/processing/corpus_coverage.py`, `src/tests/test_corpus_coverage.py`; migration gerada.
Não tocar: `grounded` para significar vigência universal, enumerações de fonte sem migração.

1. Aproveitar `CorpusRevision`, `SaplSyncState` e import runs; criar registro de escopo por fonte/jurisdição/série/período, checksum, último sucesso, pendências e estado reviewed/partial/unknown. Contagens não provam cobertura histórica.
2. Serviço retorna `corpus_revision`, `checked_until`, `sources_checked`, `missing_intervals`, `pending_review`, `coverage_status`. Ausência de certificado de cobertura = unknown, não complete.
3. Incluir DTO em resultados temporais e SSE; sem expor paths/credenciais. Invalidar conforme mudanças de corpus/revisão.

Aceite: job completo com fonte incompleta continua cobertura parcial; SAPL sem decretos executivos não atesta esses atos; corte sempre visível na conferência. Verificação: F(testes acima, `src/tests/test_rag_answer_pipeline_streaming.py`), J contrato SSE. Rollback: regra comum; schema additive e histórico preservado.

### P-006 — mesa de curadoria documental acessível

Achados: PGM-02, PGM-04. Objetivo: revisar PDFs reais sem editar JSON/admin a mão. Pré-requisitos: P-004/P-005; revisor autorizado.
Arquivos: `src/apps/legislation/document_views.py`, `src/apps/legislation/urls.py`, `src/apps/legislation/templates/legislation/document_evidence.html`, `src/apps/legislation/review_models.py`, `src/tests/test_normative_document_access.py`; novos `src/apps/core/static/js/jurix-document-review.js`, `src/tests/test_document_review_workspace.py`, `tests/js/document-review.test.mjs`.
Não tocar: extração imutável, autorização global de staff, dados reais.

1. Mostrar PDF/excerto, identidade candidata e epígrafe, datas com origem, condição de uso, extração selecionada e conflitos; ações separadas aceitar identidade/extração/segmentação.
2. Exigir permissão/reason/fingerprint em POST com CSRF; stale revision retorna 409 e preserva formulário. Registrar antes/depois e autor; sugestão não confirma nada sozinha.
3. Teclado, foco, erros associados, loading e zero ação irreversível por GET. PDF completo via link independente se embed não suportado.

Aceite: revisor confirma uma identidade pública real; conflito demanda justificativa e evidência; leitor comum só consulta; saída de sessão não vaza painel privado. Verificação: F(testes acima), J; browser reviewer/anon, Escape/Tab/320px. Rollback: desativar ações, preservar revisões.

### P-007 — distinguir edições, anexos, vetos e erratas

Achado: PGM-04. Objetivo: não tratar edição mais recente como original ou soma de textos. Pré-requisito: P-006.
Arquivos: `src/apps/legislation/document_models.py`, `src/processing/document_metadata.py`, `src/processing/document_segmentation.py`, `src/processing/normative_projection.py`, `src/tests/test_document_metadata.py`, `src/tests/test_segmentation_revision.py`, `src/tests/test_normative_projection.py`; novo `src/tests/test_document_editions.py`.
Não tocar: assinatura do original, autoaprovação, remoção de trechos vetados.

1. Reutilizar roles existentes e ligação à identidade; edição com hash distinto ganha documento próprio. Relação substitutiva exige revisão e fonte, não timestamp do arquivo.
2. Datas da norma/publicação/eficácia/importação separadas; epígrafe coletada antes da limpeza. Colofão não entra no último artigo, mas metadados legítimos continuam disponíveis com spans.
3. Anexos e repúblicas não suprem silenciosamente original ausente; veto/revogação mantém dispositivo histórico rotulado. Conflito de data continua aberto até adjudicação.

Aceite: dois documentos mesma norma não perdem versões; Art. final termina antes da assinatura; projeção sem base adequada abstenha. Verificação: F(testes acima) com PDFs públicos e fixtures de conflito; L(módulos). Rollback: regra comum, nenhuma destruição de edição.

### P-008 — completar etapas e embeddings com cursores

Achado: PGM-07. Objetivo: limitar trabalho por lote sem limitar silenciosamente o resultado final. Pré-requisitos: P-006/P-007.
Arquivos: `src/apps/ingestion/normative_tasks.py`, `src/apps/ingestion/normative_impact.py`, `src/apps/operations/models.py`, `src/tests/test_normative_pipeline_limits.py`, `src/tests/test_normative_impact_queue.py`; novo `src/tests/test_normative_pipeline_resume.py`; migration gerada se necessário.
Não tocar: guardrail `_require_normative_qa`, filas de produção e geração Ollama.

1. Cada etapa persiste universo esperado, processados, cursor, hash/revisão, erros e próximo lote. Extração deve executar ou enfileirar serviço existente, não apenas reportar estado.
2. Remover sucesso integral sobre `[:10]`: percorrer todos os dispositivos elegíveis por batches de 10 com continuação; invalidar trabalho stale e nunca reutilizar embedding de revisão antiga.
3. Retomada após queda, lease, cancelamento, DLQ/retry limitado; revisão humana pode deixar bloqueado, não “completed”. Flag de piloto futuro separada, sem alterar ambiente neste commit.

Aceite: norma com 39 dispositivos indexa os 39 elegíveis; indisponibilidade Ollama retoma sem duplicar; conclusão só após todas etapas; pendência legal impede snapshot vigente. Verificação: F(testes acima), run QA com interrupção controlada. Rollback: desativar continuação, preservar jobs/cursors.

### P-009 — duas passagens de relações sobre o acervo

Achados: PGM-04/08. Objetivo: resolver relações mesmo quando norma alvo chegou depois. Pré-requisito: P-008.
Arquivos: `src/processing/normative_reference.py`, `src/processing/event_revision.py`, `src/apps/ingestion/normative_impact.py`, `src/apps/legislation/event_review.py`, `src/tests/test_normative_reference.py`, `src/tests/test_normative_event_evidence.py`; novos `src/apps/ingestion/reconcile_corpus.py`, `src/tests/test_corpus_reconciliation.py`.
Não tocar: transformar REFERENCIA em ALTERA, gold existente, veto por heurística.

1. Primeira passagem identifica referências com ação, dispositivo, span, origem e candidatos; segunda resolve alvo usando índice canônico. Persistir alvo ausente/ambíguo e obrigação de reprocessar quando identidade chegar.
2. Incremental visita novos atos e backlog referente às identidades alteradas; não varrer tudo a cada publicação. Lease/batch/cursor e fingerprint reutilizados.
3. Revisor confirma ação e data por evidência. Caso LC198/2021 referindo LC055/2004 não é alteração só por citar Arts.21/44. Proibir revogação tácita automática.

Aceite: alvo tardio resolve; ambiguidade permanece; referência temática não muda projeção; rerun idempotente. Verificação: F(testes acima), cadeia pública adjudicada + negativos reais. Rollback: impedir novos matches, manter versões de revisão.

### P-010 — provar projeções reais e limites de vigência

Achado: PGM-04. Objetivo: comparar datas sem transmitir certeza além da evidência. Pré-requisitos: P-005/P-009 e revisão humana da cadeia.
Arquivos: `src/processing/normative_projection.py`, `src/processing/event_temporal_policy.py`, `src/apps/legislation/document_models.py`, `src/tests/test_normative_projection.py`, `src/tests/test_normative_version_compare.py`; novo `src/tests/test_real_chain_projection_contract.py`.
Não tocar: escolher lei aplicável ao caso, apagar original, inferir data pelo filename.

1. Selecionar com responsável jurídico casos públicos: alteração de artigo, revogação parcial, vacatio, veto e original ausente. Fixtures de contrato reproduzem adjudicação, não a substituem.
2. Verificar D−1/D/D+1 e data anterior à publicação; estados unchanged_in_checked_scope/modified/revoked/vetoed/not_reconstructable com documento base, ato, data, fingerprint e cobertura.
3. Cache de snapshot inclui revisão/cobertura; uma nova revisão invalida comparação/export. “Reconstrução completa” do motor não implica acervo universalmente atualizado.

Aceite: cada mudança aponta fonte exata; conflito/intervalo sem cobertura não retorna selo vigente; não preenchimento nunca equivale a revogação. Verificação: F(testes acima) + conferência humana PDF/antes/depois. Rollback: fallback inconclusivo, conservar snapshots antigos com revisão.

### P-011 — pesquisa documental e normativa numa experiência

Achados: PGM-02/06. Objetivo: buscar todo staging e distinguir documento candidato de norma revisada. Pré-requisitos: P-005/P-008.
Arquivos: `src/apps/legislation/workspace_views.py`, `src/apps/legislation/norma_queries.py`, `src/apps/legislation/templates/legislation/workspace/search.html`, `src/processing/normative_topics.py`, `src/tests/test_workspace_routes.py`, `src/tests/test_normative_topics.py`; novos `src/processing/document_search.py`, `src/tests/test_document_search.py`; migration se índice GIN necessário.
Não tocar: pesquisa/ranking de conversas, troca de framework, status jurídico automático por tema.

1. Busca exata tipo/número/ano/dispositivo precede expansão temática. Combinar full-text português/GIN e mecanismo vetorial existente; não carregar todos os PDFs por request.
2. Resultados separados: norma revisada, documento pendente, fonte parcial; filtros tipo/ano/tema/situação de revisão/data. Sinônimos controlados lixo/resíduo/saneamento, com explicação de expansão e testes.
3. Metadata de arquivo e texto extraído disponíveis antes de consolidação; filtrar sintéticos fora da pesquisa de produto. Boilerplate de vigência não domina pergunta específica.

Aceite: “ambiental lixo” retorna documentos pertinentes quando presentes no lote; inexistência na amostra explicitada; query exata não se mistura com outra espécie/ano. Verificação: F(testes acima, `src/tests/test_qa_archive_rag.py`), J; browser vazio/erro/paginado/filtros. Rollback: feature flag para busca nova; preservar índice/dados.

### P-012 — exploração temática com grafo e lista equivalentes

Achado: PGM-06. Objetivo: selecionar normas e entender relações verificáveis por tema. Pré-requisitos: P-009/P-011.
Arquivos: `src/apps/legislation/relations_api.py`, `src/processing/normative_graph.py`, `src/apps/legislation/workspace_urls.py`, `src/apps/legislation/workspace_views.py`, `src/apps/legislation/templates/legislation/workspace/_sidebar.html`, `src/apps/core/static/js/jurix-normative-graph.js`, `src/apps/core/static/css/jurix-normative-graph.css`, `src/tests/test_normative_graph_api.py`, `tests/js/normative-graph.test.mjs`; novo template `src/apps/legislation/templates/legislation/workspace/explore.html`.
Não tocar: Neo4j, força/efeito jurídico por similaridade, novo shell paralelo.

1. Criar `/explorar/` com busca/tema/data e seleção; reutilizar renderer SVG/lista. Limitar viewport a 40 nós/80 arestas com indicação/paginação; consultar indexado, não expandir recursivamente sem cap.
2. Separar arestas jurídicas revisadas, candidatos autorizados e associação temática; legendas textuais e fonte ao clicar. Usuário comum não vê candidatos privados.
3. Uma norma abre ficha; uma aresta abre evidência; dispositivo abre PDF/antes-depois. Mobile/teclado oferecem mesma informação em lista sem depender do desenho.

Aceite: professor percorre tema → conjunto → artigo afetado → origem; tipos distinguíveis sem cor; zero aresta de alteração inventada. Verificação: F(testes indicados), J; browser 360/768/1280/1920 e lista teclado. Rollback: ocultar entrada `/explorar/`, manter API antiga.

### P-013 — serviço de conferência de múltiplas referências

Achado: PGM-05. Objetivo: transformar fundamentação colada em conferências auditáveis. Pré-requisitos: P-010/P-011.
Arquivos: `src/processing/normative_reference.py`; novos `src/processing/foundation_reference_parser.py`, `src/processing/foundation_check.py`, `src/tests/test_foundation_reference_parser.py`, `src/tests/test_foundation_check.py`.
Não tocar: interpretar mérito de ação, enviar texto a API externa, treinar modelo com peça.

1. Extrair múltiplas referências com offsets de texto, espécie/número/ano/artigo/inciso; agrupar somente associação textual verificável. Referência abreviada depende de antecedente próximo não ambíguo; pedir confirmação caso duas leis disputem o artigo.
2. Serviço recebe referências confirmadas + datas explícitas de comparação, retorna estados de P-010, evidências e cobertura. Não persistir texto integral por default; tamanho máximo 50 mil caracteres e tempo de request limitado.
3. Processar muitas referências em job limitado reutilizando fila/lease, com polling/cancelamento e IDs de evidência estáveis. Deduplicar consultas, não perder spans na peça.

Aceite: duas leis com mesmo Art.1 não se misturam; uma referência alterada e outra íntegra retornam separadamente; não localizada/incompleta são inconclusivas; resultado independe de LLM para datas/eventos. Verificação: F(testes novos, `src/tests/test_normative_reference.py`); L(novos serviços); casos públicos rotulados.
Rollback: regra comum, serviço inicialmente sem escrita de texto.

### P-014 — tela “Conferir fundamentação”

Achado: PGM-05. Objetivo: tornar P-013 utilizável pelo assessor sem conhecer RAG. Pré-requisito: P-013; fluxo autenticado do piloto.
Arquivos: `src/apps/legislation/workspace_urls.py`, `src/apps/legislation/workspace_views.py`, `src/apps/legislation/templates/legislation/workspace/_sidebar.html`, `src/apps/core/static/css/workspace.css`; novos `src/apps/legislation/templates/legislation/workspace/foundation_check.html`, `src/apps/core/static/js/jurix-foundation-check.js`, `src/tests/test_foundation_check_workspace.py`, `tests/js/foundation-check.test.mjs`.
Não tocar: composer/histórico existente, permissões por is_staff genérico, upload de arquivos.

1. Criar `/conferir/` com textarea rotulado, datas “comparar redação de” / “com redação em”, referências editáveis e botão Conferir. Explicar que data dos fatos/aplicabilidade é decisão do usuário.
2. Resultado começa por alertas acionáveis, depois lista de referências: alterada/revogada/vetada/sem mudança encontrada/inconclusiva; abrir antes/depois e ato origem. Mostrar corte de atualização e lacunas perto da conclusão, não enterrados em rodapé.
3. Loading/progresso/cancelamento, erro preservando texto e retry sem duplicatejob; POST+CSRF/autorização; foco no resumo e live region sem anunciar cada token.

Aceite: pessoa leiga no software completa cola → confirma → identifica artigo superado → abre evidência; 320px/zoom200/Tab utilizáveis. Verificação: F(teste novo, `src/tests/test_workspace_auth.py`), J; browser cinco casos reais públicos e erro/cancelamento. Rollback: ocultar rota/entrada, preservar serviços/evidências.

### P-015 — exportar pacote de evidência e referências

Achados: PGM-01/05. Objetivo: preservar rastreabilidade fora do Jurix. Pré-requisitos: P-010/P-014.
Arquivos: `src/apps/legislation/norma_pdf.py`, `src/apps/legislation/source_urls.py`, `src/processing/citation_enrichment.py`, `src/apps/core/static/js/jurix-markdown.js`, `src/tests/test_versioned_citation_contract.py`, `tests/js/versioned-citations.test.mjs`; novos `src/processing/evidence_export.py`, `src/tests/test_evidence_export.py`.
Não tocar: LLM gerando URL, expor documento privado publicamente, fragmento sobre lei inteira.

1. DTO exportável inclui norma/dispositivo, redação/data, evento, corpus/snapshot/revisão, documento/hash/página/spans, fonte oficial ou PDF local autorizado, limite da verificação.
2. Produzir Markdown e JSON; PDF reutiliza exporter existente. Whole-law reference abre documento sem marca; artigo/inciso abre evidência específica. Link antigo aponta snapshot imutável ou sinaliza revisão, não muda silenciosamente.
3. Cópia usa mesmo DTO do renderer; teste real de clipboard e reabertura. Exportação não inclui texto confidencial colado sem seleção explícita.

Aceite: fora do app leitor encontra ato e dispositivo citados; hash/revisão/corte presentes; cópia mantém links legíveis sem URL gerada pelo modelo. Verificação: F(testes acima), J e browser copiar/baixar/abrir URL com autorização. Rollback: desativar export novo sem apagar manifestos.

### P-016 — dossiês versionados e impactos

Achados: PGM-05/08. Objetivo: salvar referências conferidas sem substituir sua versão histórica. Pré-requisitos: P-014/P-015.
Arquivos: `src/apps/legislation/models.py`, `src/apps/legislation/workspace_views.py`, `src/apps/legislation/templates/legislation/workspace/collection_detail.html`, `src/apps/core/static/js/jurix-collections.js`, `src/tests/test_collections_workspace.py`; novo `src/tests/test_collection_evidence_versions.py`; migration gerada.
Não tocar: remover M2M/coleções existentes, compartilhamento público automático, conteúdo de processos reais.

1. Acrescentar entrada de coleção com dispositivo/snapshot/as_of/evidence hash, owner, versão e resultado da conferência; reusar coleções existentes como dossiê.
2. Salvar depende de ação explícita. Novo evento confirmado gera aviso de impacto, não reescreve texto salvo; usuário compara e decide atualizar versão.
3. Acesso por proprietário/grupo autorizado e testes IDOR; coleção não precisa guardar peça original para guardar referência.

Aceite: snapshot antigo preservado, alteração aparece com origem; outra conta não lê conteúdo; PDF pendente mantém rótulo pendente. Verificação: F(testes acima), J, browser dois usuários QA. Rollback: ocultar entradas novas, preservar histórico additive.

### P-017 — adapter do Diário Oficial e identidade das edições

Achado: PGM-08. Objetivo: cobrir atos executivos sem confundir SAPL legislativo com acervo completo. Pré-requisitos: P-003/P-005/P-009.
Arquivos: `src/processing/document_metadata.py`, `src/apps/legislation/document_models.py`, `src/tests/test_document_metadata.py`; novos `src/clients/dom_natal/client.py`, `src/clients/dom_natal/__init__.py`, `src/apps/ingestion/dom_sync.py`, `src/tests/test_dom_natal_client.py`, `src/tests/test_dom_sync.py`; migration somente se fonte precisar campo novo.
Não tocar: adivinhar API, desativar TLS, usar decreto legislativo como executivo, sincronizar produção nesta tarefa.

1. Descobrir links/identidade pelo catálogo oficial acessível; congelar fixtures HTML/PDF públicos sanitizados. Edição ordinária/especial e errata com ID próprio, URL observada, checksum e data; alterações de arquivo criam versão.
2. Host allowlist, redirects revalidados, limite bytes/páginas, timeout/retry, Content-Type+magicPDF, hash e licença/condição documentada. Não seguir rede privada nem arquivo arbitrário.
3. Segmentar atos dentro da edição mantendo página/spans e fronteiras; distinguir portarias/editais/avisos de norma. Criar candidatos, nunca consolidar automaticamente. Testar edição especial de mesma data e quebra de layout.

Aceite: ordinária e especial não colidem; reexecução idempotente; fonte inválida falha segura; dispositivo aponta página do ato na edição. Verificação: F(testes novos), testes offline e leitura externa pequena autorizada sem gravação real. Rollback: desabilitar adapter, preservar edições armazenadas.

### P-018 — atualização diária com retomada e saúde real

Achados: PGM-07/08. Objetivo: converter schedules existentes em operação observável. Pré-requisitos: P-008/P-009/P-017.
Arquivos: `config/settings.py`, `src/apps/ingestion/sapl_sync.py`, `src/apps/ingestion/normative_tasks.py`, `src/apps/operations/models.py`, `src/tests/test_sapl_sync_state.py`, `src/tests/test_sapl_sync_schedule.py`, `src/tests/test_normative_impact_queue.py`; novo `src/tests/test_source_sync_recovery.py`.
Não tocar: `.env`, flags/beat de produção ativos, remover full sweep paginado.

1. Reusar SAPL daily/full sweep opt-in; adicionar DOM por configuração separada do piloto, timezone e fila dedicada. QA beat permanece desligado por padrão.
2. Highwater/overlap e sweeps paginados detectam edições atrasadas; `limit=50` de SAPL é tamanho de página, não necessariamente população total. Distinguir fonte sem novidade de fonte indisponível.
3. Publicação nova dispara pipeline/reconciliação, pendência revisão e impactos; saúde verifica rotas/banco/fila/corte, não somente processo vivo. Retry após restart com evidência/contadores.

Aceite: duas rodadas sem duplicação; publicação atrasada descoberta; outage mostra acervo desatualizado; alteração não aprovada não vira vigente; queue consumer validado. Verificação: F(testes acima), worker QA+restart controlado e reconciliação métricas. Rollback: desligar opt-in, manter checkpoints.

### P-019 — assistente natural apoiado no mesmo serviço temporal

Achados: PGM-01/04. Objetivo: explicar evidências completas/parciais sem esconder abstenção. Pré-requisitos: P-010/P-013/P-015.
Arquivos: `src/processing/rag_prompt.py`, `src/processing/rag_context_builder.py`, `src/processing/rag_answer_pipeline.py`, `src/processing/qa_archive_rag.py`, `src/apps/core/static/js/jurix-rag.js`, `src/apps/core/static/js/jurix-chat-renderer.js`, `src/apps/core/static/css/jurix-chat-renderer.css`, `src/tests/test_qa_archive_rag.py`, `src/tests/test_rag_answer_pipeline_streaming.py`, `tests/js/streaming.behavior.test.mjs`, `tests/js/versioned-citations.test.mjs`.
Não tocar: remover grounding, cravar probabilidade jurídica, implementar resposta só em CSS, exigir LLM maior.

1. Prosa começa pela resposta; headings só mudança real de assunto. Citações estruturadas por afirmação/dispositivo, metadados geram links; modelo não gera URL.
2. Pergunta da norma inteira usa cobertura por capítulos/artigos e orçamento adaptativo, não top-k pequeno universal. Documento longo comunica dispositivos examinados/total e anexos ausentes; relação/temporalidade consulta P-013/P-010, não só texto semelhante.
3. `sources` associa evidências imediatamente e permite acesso; controle discreto durante geração, sem selo definitivo/cópia prematuros. Confiança/ações finais fade-in após validação; `done` consolida, não recompõe tudo. Prefer-reduced-motion obrigatório.
4. Evidência insuficiente explica qual parte falta e oferece conferir PDF/identidade/data; nunca esconder falta com afirmação inventada. Validar parágrafos antes de tratá-los como conclusão; erro/cancelamento preservam pergunta.

Aceite: streaming incremental/citação resolvível antes de done; cópia final com Markdown/links; follow-up mantém norma sem arrastar contexto ambíguo; overview/relação/tempo separados; zero falso “não mudou”. Verificação: F(testes acima, `src/tests/test_grounded_citations.py`), J, smoke Ollama QA frio/quente e perguntas reais julgadas por humano. Rollback: feature flag na estratégia nova, P-001 safety permanece.

### P-020 — gold jurídico e experimento reproduzível

Achado: PGM-09. Objetivo: medir qualidade jurídica em corpus real, sem elevar synthetic a gold. Pré-requisitos: P-010/P-019, responsável jurídico disponível.
Arquivos: `benchmarks/corpus/municipal_natal/README.md`, `scripts/evaluate_normative_graph.py`, `scripts/collect_normative_rag_experiment.py`, `scripts/run_normative_rag_experiment.py`, `src/tests/test_normative_graph_evaluation.py`, `src/tests/test_normative_rag_experiment.py`; novos `benchmarks/corpus/municipal_natal/pgm-pilot.manifest.v1.json`, `benchmarks/corpus/municipal_natal/pgm-pilot.cases.v1.jsonl` apenas após adjudicação; novo `docs/research/PGM_GOLD_ADJUDICATION.md`.
Não tocar: resultado/case antigo congelado, dados pessoais e passagem humana com autor falso.

1. Selecionar amostra intencional 150–200 documentos por tipo/década/tema; iniciar mínimo 20 normas distintas adjudicadas em três cadeias. Manifesto distingue PDF/documento/norma/pergunta e abstenções.
2. Revisores independentes + responsável desempata: identidade, extração, ação/alvo/data e resposta aceitável por pergunta. Definir rótulos antes de coletar predições; bloquear ciência abaixo dos mínimos.
3. Parear baseline/grafo/grafo-temporal nas mesmas consultas, corpus/modelo/hardware/cache/temperatura registrados. Métricas: resolução de alvo, ação/data, recall de mudanças, precisão das citações, cobertura/abstenção e latência. IC por bootstrap agrupado por norma/cadeia, não token.

Aceite: resultados negativos publicados; nenhum ganho científico quando gate humano falha; universo e vieses explícitos. Verificação: F(testes acima), scripts sobre fixtures e depois gold real aprovado. Rollback: novas versões de manifesto/resultados, não sobrescrever gold.

### P-021 — teste de uso PGM e polimento guiado por observação

Achados: PGM-05/06/09. Objetivo: comprovar que o assessor encontra mudança antes de citar. Pré-requisitos: MVP fase C e amostra adjudicada P-020.
Arquivos: `tests/js/normative-product-smoke.mjs`, `tests/js/normative-rag-live-smoke.mjs`; novo `tests/js/pgm-workflow-smoke.mjs`, `docs/research/PGM_USABILITY_RUNBOOK.md`, `docs/research/PGM_USABILITY_RESULTS.md`, `scripts/normative_qa.py`, `src/tests/test_normative_qa_guard.py`. Refinamentos de UI somente depois em tarefas próprias com arquivo/problema delimitado.
Não tocar: anotar sucesso de participante sem sessão real, gravação pessoal sem consentimento.

1. Cenários públicos: localizar norma exata; detectar artigo revogado numa fundamentação antiga; comparar data; buscar lixo/ambiente e inspecionar relação; exportar prova; incluir caso original faltante.
2. Teste técnico como usuário antes do piloto; desktop/mobile, claro/escuro, 320/360/768/1280/1920, zoom nativo200, Tab/Escape, copiar/abrir PDF, erros/jobs lentos. Separar observação visual de assertions DOM.
3. Convidar 3–5 assessores com consentimento; comparar tempo/acerto com rotina atual, sem intervenção do moderador. Alvos iniciais: ≥90% tarefas concluídas e redução mediana ≥50% na conferência; explicitar tamanho amostral, erros e limites, não métricas populacionais.
4. Todos os casos conhecidos de referência superada devem alertar; ausência de alerta reprova o gate, sem promessa universal de zero erro. Registrar cada problema em ticket reproduzível e reavaliar nota.

Aceite: resultados reais com método; barreiras críticas corrigidas em diffs próprios; tarefa inconclusiva não induz uso de texto vigente. Verificação: J, smoke novo QA e sessões PGM; sem participantes marcar “não executado”. Rollback: artefatos novos versionados, nenhum dado confidencial.

### P-022 — autorização, privacidade e operação do piloto

Achados: PGM-05/08/09. Objetivo: impedir que uma demonstração aberta vire tratamento indevido de peças. Pré-requisitos: P-014/P-016/P-018; responsável operacional/jurídico.
Arquivos: `src/apps/legislation/workspace_views.py`, `src/apps/legislation/document_views.py`, `config/settings.py`, `src/tests/test_workspace_auth.py`, `src/tests/test_normative_document_access.py`, `src/tests/test_settings_security.py`; novos `docs/research/PGM_PILOT_SECURITY.md`, `src/tests/test_pgm_authorization.py`.
Não tocar: `.env`, Docker/volumes reais, chaves pessoais e acesso de usuários reais durante QA.

1. Papéis consultar/revisar/exportar/administrar, checagem por objeto em toda rota/job/PDF/export; CSRF, IDOR, XSS, upload/SSRF gates mantidos. Mínimo privilégio, audit trail sem peça integral.
2. Texto colado efêmero por default, TTL e exclusão lógica definidos; salvar dossiê explícito. Não encaminhar conteúdo reservado a LLM externo só porque usuário cadastrou API key. Política organizacional/documental antes disso.
3. Pilot profile separado QA/produção: plano de migration, backup/restore ensaiado em cópia, worker/beat consumidores, health de dependências/rotas e alertas de corte documental. `check --deploy` no perfil apropriado, reportar warnings sem alterar config local por suposição.

Aceite: contas isoladas; zero secrets no browser/export/log; restore QA provado; ativação real somente com autorização independente. Verificação: F(testes acima), check/deploy seguro, testes de permissão negativos e restore cópia. Rollback: desativar acesso do piloto de modo autorizado, preservar trilha; nenhum rollback destrutivo de dados.

### P-023 — entrega única, documentação e reavaliação

Achados: todos. Objetivo: tornar rastreável qual versão está sendo testada e o que ela cobre. Pré-requisitos: gates A–E, sem fingir conclusão de gate humano pendente.
Arquivos: `README.md`, `docs/current-status.md`, `docs/research/NORMATIVE_GRAPH_DELIVERY.md`, `docs/research/NORMATIVE_GRAPH_OPERATIONS.md`, `src/apps/legislation/workspace_views.py`, `src/apps/legislation/templates/legislation/workspace/_topbar.html`; novos `docs/research/PGM_PILOT_DELIVERY.md`, `src/apps/core/build_identity.py`, `src/tests/test_build_identity.py`.
Não tocar: estrutura do README, trocar todas as portas, publicar dados do acervo sem direito/condição, remote Git.

1. Em `build_identity.py`, ler campos de release já existentes, se houver, ou receber metadata de build explícita; ausência retorna “build local não identificado”, não HEAD inventado. `workspace_views.py` passa DTO sanitizado ao topbar. Revisão/build e perfil/corpus em detalhe técnico sem executar Git por request; checkout dirty sinalizado só em diagnóstico local. Documentar uma porta do piloto corrente e comandos verificados, não prometer porta fixa eterna.
2. README preserva estrutura e distingue “consultável”, “revisado”, “consolidado”, “atualizado até” e “piloto validado”. Atualizar contagens comprovadas, não anteriores/copiar notas sem método.
3. Regressão integral Python/JS, check/lint/architecture/doc contract e smokes reais; publicar versão dos casos, limitações, problemas remanescentes e notas por rubrica.

Aceite: novo usuário encontra fluxo PGM/limites; nota ≥9 somente se gates satisfeitos e avaliação real justificar. Se ficar em 7, publicar 7 e próximos blockers; não ajustar nota para cumprir promessa. Verificação: comandos comuns + P-021/P-022; relatório sanitizado. Rollback: reverter somente documentação/build próprios, manter evidências anteriores.

## Atividades humanas/operacionais que não são patches

- Confirmar condição de uso e publicação do arquivo; não confundir natureza pública da norma com licença de redistribuição de um pacote contendo outros arquivos.
- Designar especialista para conflitos de identidade, datas, ação e redação, inclusive LC198/2021 e decreto12887 com datas conflitantes; não deixar executor escolher a verdade para destravar CI.
- Escolher três famílias prioritárias da PGM com eventos explícitos reais, incluindo atos antigos e modificadores. LC120/2010 é demonstração de busca, não cadeia temporal já certificada.
- Fornecer gold e participantes; autorizar separadamente piloto institucional, dados pessoais/reservados e eventuais provedores externos.

## Critério verificável para buscar 9/10

1. Arquivo completo inventariado e ingestão retomável; biblioteca documental pesquisável sem etiquetas jurídicas falsas.
2. Piloto com pelo menos 20 normas distintas, três cadeias reais adjudicadas e fontes/origens das datas abertas pelo usuário.
3. Fundamentação antiga → aviso do dispositivo superado → redação antiga/nova → ato modificador → exportação, sem depender de pergunta “perfeita” nem F5.
4. Em ausência de cobertura/original, resultado inconclusivo claro, não certeza por omissão.
5. Operação incremental comprovada com edição especial, chegada atrasada, outage e retomada; freshness visível.
6. Testes jurídicos/usuários, métricas científicas separadas das técnicas, segurança/restore e acessibilidade essencial verificados. Nenhuma afirmação universal de vigência/correção automática.

## Baseline desta reavaliação

Runtime QA8026: 40 PDFs pendentes, nenhuma norma consolidada nessa instância; consulta temática sem resultados na amostra; pergunta de alteração do art.18 resultou em transcrição, conforme screenshot da avaliação. Nenhum dado promovido. Regressão focal nova de quatro módulos: **71 passed em 17,09 s**, zero falhas, sem extrapolar para suíte integral. Comando registrado na avaliação. Git permaneceu main/ab6c172 com baseline dirty; somente artefatos novos desta avaliação são autorizados neste turno.
