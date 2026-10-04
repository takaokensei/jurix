# Jurix — entrega do ciclo de grafo normativo

**Estado em 03/10/2026:** implementação de software e QA técnico avançados; piloto jurídico e experimento científico **não avaliados**. O trabalho foi exercitado na branch `main`, HEAD inicial `0426e53`; alterações permanecem locais, sem commit, push, merge ou troca de branch nesta etapa.

## O que está implementado neste checkout

- Identidade de documentos e normas separa jurisdição, série/tipo, número e ano; metadado desconhecido não é inferido pelo nome do arquivo.
- Ingestão do ZIP tem inventário, hashes, limites, extração versionada, promoção explícita e fronteira QA. O ZIP original foi inventariado sem extração em massa; dados experimentais ficaram no diretório QA temporário.
- Eventos normativos têm evidência/spans, fingerprint, estado de revisão, política temporal e projeção em snapshots; referência temática não é tratada como alteração.
- Endpoints de norma, dispositivo, timeline, versão e relações aplicam limites e regras de acesso. Relações públicas são expostas apenas conforme status/configuração.
- RAG pode expandir contexto por relações revisadas quando `RAG_GRAPH_CONTEXT_ENABLED` estiver ativo; a expansão é limitada, rastreada, exige texto da fonte/alvo e mantém fallback para a recuperação base.
- Interface de norma inclui ações de comparação, linha do tempo e painel de relações, com representação móvel em lista. Citações versionadas carregam identidade/hash e URLs oficiais sem fragmento histórico de texto.
- Catálogo sintético de casos difíceis, avaliador JSONL, analisador de experimento RAG e microbenchmark offline foram adicionados para tornar próximas medições reproduzíveis.

## O que esta entrega não demonstra

- O corpus real não foi importado nem aprovado; não há adjudicação humana suficiente para métricas científicas. O avaliador deve retornar `not_evaluated` abaixo do mínimo configurado de 20 normas humanas distintas.
- O analisador RAG consome predições já produzidas; não executa os braços nem comprova que grafo melhora respostas. Nenhuma comparação válida baseline/graph/graph-temporal foi rodada.
- O QA contém fixtures sintéticas e 40 PDFs importados em área isolada, ainda pendentes de revisão de identidade/uso jurídico. Em 03/10/2026, o assistente consultou LC 120/2010 no corpus QA, mostrou fontes durante a geração e informou cobertura parcial de 20/39 artigos; isso prova o fluxo RAG/SSE com documentos extraídos, mas **não** valida a norma, o corpus ou a resposta como orientação jurídica. Não foram medidos TTFT/tokens nem confirmada por trace a origem do provider para cada token. Nenhum PDF foi promovido ao corpus consolidado.
- As filas e leases de impacto são primitivas; handlers de cada fase de processamento, agendamento, retry operacional integrado e observabilidade ponta a ponta ainda não fecham um pipeline de produção.
- `manage.py check --deploy` não passou no perfil temporário com `DEBUG=True` e chave sentinela; esse resultado não é uma avaliação do perfil implantado. Não foi declarada conformidade WCAG/HIG nem prontidão de produção.
- Importação/aprovação do corpus, migration em banco real, ativação de flags em produção, ingestão gradual e restauração de backup não foram executadas.

## Verificações executadas

- Testes focados dos incrementos de grafo, documentos, revisão, temporalidade, QA e limites foram rodados ao longo das tarefas; detalhes e contagens estão em `NORMATIVE_IMPLEMENTATION_PROGRESS.md`.
- Navegador Chromium real no servidor QA `http://127.0.0.1:8008`: seis rotas de workspace em 360, 768, 1280 e 1920 px, mais página de norma e pesquisa exata; zero overflow horizontal e zero erro JS detectado pelo smoke.
- Revalidação manual adicional no servidor QA `http://127.0.0.1:8015`: seis rotas carregadas; LC55/2004 e LO55/2004 ficaram distintas; referências LC198→LC55 permaneceram pendentes e sem aparecer como relações públicas; comparação sintética D−1/D exibiu “dez dias”/“vinte dias”; consulta de PDF QA mostrou 20 evidências e aviso de 20/39 artigos. Ver `NORMATIVE_IMPLEMENTATION_PROGRESS.md` para escopo e limitações.
- R13 exercitado com fixtures LO9001/2020→LO9002/2021: resposta recuperou a alteração e o efeito em 01/03/2021. A revisão manual detectou repetição da citação no texto e um selo genérico após a conclusão; o selo foi corrigido e, após reload, identifica claramente fixture sintética, enquanto o drawer informa que não é legislação real/evidência jurídica. Testes da mudança: 7 serializer tests e 39 streaming tests passaram; suite combinada de 42 incluiu uma falha preexistente/de ambiente, o teste SQLite-only executado em PostgreSQL QA (41 passaram).
- R14/R15/R18 exercitados em browser real no corpus QA: referência federal ausente produziu abstenção sem confusão com número municipal; pergunta sobre LC120/2010 expôs 20 fontes durante a geração e cobertura parcial de 20/39; cancelamento preservou a pergunta e marcou fontes recuperadas como não validadas (selo e drawer). Streaming JS atualizado: 40 testes passaram. Para R15, o uso de PDFs exige a URL do corpus QA; TTFT/provider trace continua não medido.
- Inspeção manual reproduziu busca por norma ausente e expansão de relações sem arestas públicas. Corrigidos o texto de estado vazio que chamava o resultado de “semântico” apesar de a busca exata ser lexical, o eyebrow que afirmava consolidação em registro pendente e a concordância de “1 dispositivo”.
- Evidências sanitizadas de fixture sintética ficam em `evidence/normative-graph/2026-10-03-qa8008/`. Viewport mobile não substitui zoom nativo 200%; zoom real, NVDA/VoiceOver e contraste completo de toda tela não foram auditados nesta rodada.
- Suíte JS e suíte Python integral estão registradas no progresso. Falhas não atribuídas a esta entrega permanecem explicitamente documentadas; não foram enfraquecidas para fazer o gate passar.

## Avaliação qualitativa

Reavaliação em 03/10/2026: **5,5/10 como MVP de produto jurídico** e **6,5/10 como demonstração técnica em QA**. A navegação e comparação temporal funcionam; o assistente agora percorre PDFs QA recuperáveis, expõe fontes durante o processamento e avisa quando a cobertura é parcial. Porém `/normas/` ainda reporta zero normas consolidadas e 40 candidatos pendentes, Coleções não permite criação nesta instalação, e não há aprovação jurídica/gold humano. Como **projeto de pesquisa/engenharia**, **7/10**: a infraestrutura de proveniência e avaliação é promissora, mas não existem ainda métricas humanas nem ganho experimental demonstrado. Nota qualitativa, não score objetivo nem substituto de banca, revisão jurídica ou estudo com usuários. O runbook R01–R24 continua parcial.

## Próximo gate

1. Confirmar licenciamento/condição de uso do arquivo recebido e selecionar amostra municipal intencional.
2. Executar inventário/dry-run em cópia QA; revisão humana explícita de identidade, spans, eventos, alvos e datas.
3. Completar e adjudicar ao menos 20 normas antes de abrir gate científico; manter os casos ambíguos fora das métricas até regra acordada.
4. Fechar handlers/leases para ingestão → extração → segmentação → eventos → snapshots → embeddings; instrumentar queries, latência e falhas.
5. Congelar corpus/modelo/hardware e executar avaliação pareada baseline, grafo e grafo-temporal. Publicar métricas e intervalos, incluindo erros e abstenções.
6. Só então preparar implantação separada com backup/restore testado, migrations revisadas, lote pequeno e aprovação operacional.

Consultar `NORMATIVE_GRAPH_OPERATIONS.md` para os comandos seguros e os gates de ativação. Este documento não autoriza uso de banco real.
