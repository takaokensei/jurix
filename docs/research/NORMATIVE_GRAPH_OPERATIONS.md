# Operação segura — acervo e grafo normativo

Este roteiro separa desenvolvimento/QA de ativação. Ler junto com
`JURIX_NORMATIVE_GRAPH_IMPLEMENTATION_PLAN.md` e
`JURIX_NORMATIVE_GRAPH_TEST_RUNBOOK.md`. Nenhum comando abaixo autoriza mudar
banco de produto, baixar/importar o ZIP, aprovar relações ou ligar flags fora de
um ambiente explicitamente isolado.

## Ambiente QA usado neste ciclo (revalidado em 05/10/2026)

- Aplicação Django temporária: `http://127.0.0.1:8019` (código inclui a correção de seguimento contextual e a ficha compacta de evidência documental); `8018` contém a mesma correção de backend, `8017` forneceu a medição R15 anterior e `8008` permanece como ambiente QA anterior. Os servidores anteriores foram preservados; não presumir que sirvam a versão mais recente.
- PostgreSQL QA em loopback porta `55432`; Redis QA em `16380`; raiz isolada em
  `%TEMP%\jurix-normative-qa-340c2736960a4c4fb65ea63446cb635b`.
- Settings `config.settings_normative_qa`; flags de arquivo/grafo/histórico e
  expansão RAG habilitadas somente nesse perfil.
- Ollama em `127.0.0.1:11434` respondeu a `/api/tags`; modelos locais listados
  incluíram famílias Qwen/Llama e embeddings Nomic. Nenhuma inferência jurídica
  integrada foi considerada aprovada por essa checagem.
- O banco QA contém fixtures sintéticas e um lote de 40 PDFs históricos autênticos
  do acervo recebido, sem promoção: identidade, uso, extração e segmentação
  continuam pendentes de revisão. As capturas R15 usam uma consulta a esse lote,
  sem dado pessoal. O perfil tem `DEBUG=True` e segredo sentinela; nunca usar em
  exposição externa.
- O teste Chromium/Ollama em `8017` mediu, em uma consulta, `sources`=87 ms,
  primeiro texto DOM=626 ms e `done`=1.119 ms; é smoke técnico de n=1, não SLA,
  p95 ou validade jurídica.
- Em `8018`, a pergunta “Qual é o piso do vencimento básico?” após uma consulta
  sobre a LC 120/2010 herdou a norma, recuperou só o Art. 18 e manteve resposta e
  fonte após F5. A extração continua pendente de revisão humana.
- Em `8019`, a ficha do mesmo PDF histórico mantém identificação, alertas,
  metadados e ações principais visíveis sem expandir automaticamente as 23
  páginas de texto extraído. O rascunho continua disponível em disclosure
  recolhido/expansível; essa alteração de apresentação não aprova nem altera a
  extração.

Para repetir testes, abrir PowerShell em `C:\Jurix` e definir explicitamente
`JURIX_QA_ONLY=1` e `JURIX_QA_ROOT` para diretório temporário novo/isolado. Rode
`python scripts/normative_qa.py --check` e `--check-services` antes de qualquer
comando; use o wrapper para executar pytest, `manage.py check`, `migrate --plan`,
`makemigrations --check --dry-run` e os comandos QA allowlisted. O runner recusa
hosts/portas externos para DB/Redis. Não contorne o guard se um serviço faltar.

Smoke de browser no host QA (requer Chrome/Edge já instalado e Puppeteer Core):

```powershell
$env:JURIX_QA_ONLY = '1'
$env:JURIX_QA_ROOT = '<diretorio-temporario-qa>'
$env:JURIX_BASE_URL = 'http://127.0.0.1:8008'
$env:JURIX_FIXTURE_MAP = Join-Path $env:JURIX_QA_ROOT 't015-fixture-map-v2.json'
$env:JURIX_EVIDENCE_DIR = 'C:\Jurix\docs\research\evidence\normative-graph\<run-id>'
python scripts/normative_qa.py --run node tests/js/normative-product-smoke.mjs
```

Mapfile deve declarar `synthetic_not_gold`; o smoke recusa host remoto/porta
diversa e mapfile fora da pasta temporária. Não incluir nome de usuário, senha,
dados de conversa real, chave, PDF ou texto privado nas capturas/relatórios.

## Flags e endpoints

No settings QA as flags `NORMATIVE_ARCHIVE_ENABLED`, `NORMATIVE_GRAPH_ENABLED`,
`NORMATIVE_HISTORY_ENABLED` e `RAG_GRAPH_CONTEXT_ENABLED` são habilitadas para
teste. Em settings de produto ausentes equivalem a `False`; manter desligadas até
aprovação operacional independente. Alterar uma flag não importa documentos nem
aprova eventos.

O beat de sync SAPL também exige opt-in separado: `SAPL_SYNC_SCHEDULE_ENABLED=1`
define o incremental diário às 02:00 e o full sweep aos domingos às 03:00, ambos
com no máximo 50 registros por chamada. O padrão é desligado, e o perfil QA mantém
`CELERY_BEAT_SCHEDULE` vazio; não iniciar beat para validar a configuração. Isso
apenas declara cadências: não comprova paginação SAPL, segurança do uso do acervo
ou aptidão jurídica dos documentos.

Rotas relevantes incluem `/normas/`, `/normas/<id>/`, `/normas/<id>/compare/`,
`/normas/<id>/tree/`, `/normas/documentos/<uuid>/`, e APIs em
`/api/v1/normas/<id>/timeline/`, `conflicts/`, `relations/` e `version/`.
Consultar `src/apps/legislation/urls.py` e `api_urls.py` para fonte atual. IDs e
visibilidade dependem de revisão/status; resposta 200 não prova validade legal.

## Gates antes de qualquer banco real

1. Verificar licença/uso permitido, retenção, integridade e hash do arquivo; o
   inventário não deve extrair/executar entradas.
2. Backup PostgreSQL verificável e restauração ensaiada em instância separada;
   registrar quem autorizou, janela e plano de retorno.
3. Revisar cada migration e saída de `migrate --plan`; operação real exige
   autorização própria, não usar `normative_qa.py` para contornar o isolamento.
4. Dry-run de identidade com allowlist de tipos/anos e amostra inspecionada;
   rejeitar colisões/conflictos para fila humana, não usar modelo para decidir.
5. Ingestão em lote inicial de 20–50 documentos em staging com contagens antes/
   depois, hash, falhas, tempo, uso de memória e rollback/restore comprovados.
6. Não promover evento por heurística. A pessoa revisora deve ver documento,
   trecho literal, offsets, alvo, ação, datas/publicação/efeito separadas e hash.
7. Manter `RAG_GRAPH_CONTEXT_ENABLED` desativado até revisão amostral das arestas,
   testes de regressão e experimento pareado. Ativação gradual exige owner,
   monitoramento, critério de pausa e plano para desligar sem apagar evidências.
8. Medir geração real em modelo/corpus/hardware congelados e avaliar citações,
   abstenções, falsos positivos, cobertura e latência. Sem 20 normas adjudicadas,
   publicar apenas `not_evaluated`; não chamar smoke técnico de resultado.

## Rollback e incidentes

- Desligar a flag reduz exposição funcional, mas não reverte escrita no banco.
- Interromper worker só após confirmar o nome/ID do worker QA próprio; leases
  expiram/retry conforme fila. Não parar Celery ou containers compartilhados.
- `git revert` reverte código, não migrations, documentos, eventos ou snapshots.
  Recuperação de banco usa backup aprovado e procedimento de restore separado.
- Em divergência de identidade, fonte, data, evidência ou permissão: interromper
  promoção, manter registro pendente, guardar logs sanitizados e solicitar
  revisão humana. Não corrigir por inferência nem apagar o original.

## Registro de execução — 06/10/2026

- QA Django em `127.0.0.1:8015`, PostgreSQL/Redis QA isolados e Ollama local; smoke browser/RAG pode ser repetido conforme `JURIX_NORMATIVE_GRAPH_TEST_RUNBOOK.md`. A evidência RAG sanitizada mais recente está sob `%TEMP%\jurix-normative-qa-live-dfb2d6512b764c1e96e47c0ab97b499d\evidence\2026-10-06-live-rag-smoke-r8\`; ela não armazena corpo integral da resposta/fonte.
- Regressão Python registrada: 1.317 passed, 3 skipped, 7 warnings; suíte JS exit 0, grupo Chromium 37/37; smoke de produto 42 rota×largura, 15 interações e seis verificações claras, zero falhas. Ver `NORMATIVE_IMPLEMENTATION_PROGRESS.md` para escopo e exclusões.
- Limitações vigentes: worker Celery de produto unhealthy (não usar para jobs); zoom nativo 200% e leitor de tela não testados; PDFs ainda pendentes de revisão humana; comparativo RAG sem gold e sem cache de resposta warm; nenhum sync SAPL completo ou write externo foi executado. Não habilitar flags nem promover documentos a partir desses resultados.

## Registro de execução — 07/10/2026

- Revalidado Docker QA PostgreSQL/Redis (`55432`/`16380`), Ollama (`11434`) e aplicação QA em `127.0.0.1:8022`. A tela `/normas/` informa 0 normas consolidadas e 40 documentos em revisão. Reexecute o smoke real conforme o bloco RAG do runbook; evidência da execução atual: `%TEMP%\jurix-normative-qa-live-dfb2d6512b764c1e96e47c0ab97b499d\evidence\2026-10-07-user-ollama-smoke-r21\`.
- `/assistente/` no Docker do produto `:8000` respondeu 500, `/normas/` excedeu 15 s, worker `jurix-worker-1` unhealthy. Leitura sanitizada de 500 linhas dos logs encontrou 8 falhas de resolução do hostname do banco (`django.db.utils.OperationalError`/`psycopg2.OperationalError`) e 4 marcadores HTTP 500; o healthcheck Docker reportava `healthy`, insuficiente para atestar as rotas. Não usar esses containers para jobs nem anexá-los ao PostgreSQL/Redis QA; nenhuma configuração foi mudada.
- Reconciliação SAPL dos 40 PDFs foi somente leitura; há nove URLs candidatas, todas sem hash idêntico, e não houve associação/promoção. Relatórios de metadados e similaridade textual ficam na pasta `evidence` da raiz QA acima. O catálogo não encontrar um registro não comprova inexistência legal.
- Zoom nativo 200% e leitor de tela continuam pendentes; tentativa de controle de Chrome foi bloqueada pela proteção de automação antes da navegação. Não marcar R24 como aprovado. Sem revisão humana do acervo/gold e sem avaliação científica.
