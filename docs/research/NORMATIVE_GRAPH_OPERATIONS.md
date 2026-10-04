# Operação segura — acervo e grafo normativo

Este roteiro separa desenvolvimento/QA de ativação. Ler junto com
`JURIX_NORMATIVE_GRAPH_IMPLEMENTATION_PLAN.md` e
`JURIX_NORMATIVE_GRAPH_TEST_RUNBOOK.md`. Nenhum comando abaixo autoriza mudar
banco de produto, baixar/importar o ZIP, aprovar relações ou ligar flags fora de
um ambiente explicitamente isolado.

## Ambiente QA usado neste ciclo

- Aplicação Django temporária: `http://127.0.0.1:8008`.
- PostgreSQL QA em loopback porta `55432`; Redis QA em `16380`; raiz isolada em
  `%TEMP%\jurix-normative-qa-340c2736960a4c4fb65ea63446cb635b`.
- Settings `config.settings_normative_qa`; flags de arquivo/grafo/histórico e
  expansão RAG habilitadas somente nesse perfil.
- Ollama em `127.0.0.1:11434` respondeu a `/api/tags`; modelos locais listados
  incluíram famílias Qwen/Llama e embeddings Nomic. Nenhuma inferência jurídica
  integrada foi considerada aprovada por essa checagem.
- Arquivos no QA e capturas usam somente fixtures sintéticas. O perfil tem
  `DEBUG=True` e segredo sentinela; nunca usar em exposição externa.

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
