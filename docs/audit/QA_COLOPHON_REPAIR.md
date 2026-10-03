# QA: reparação reversível dos colofões

Estado: dry-run e reparação reversível dos sete colofões concluídos em cópia temporária isolada. Nas três divergências SAPL/OCR, o artigo foi limpo e todas as datas foram preservadas; nenhuma divergência foi resolvida automaticamente. **A base real não foi alterada.**

## Reprodução e evidência

O banco configurado pelo workspace é `C:\Jurix\db.sqlite3`. Não execute `manage.py repair_legal_colophons` diretamente contra essa configuração. A auditoria copiou o SQLite para uma pasta temporária usando conexão de origem `mode=ro`, redirecionou a conexão Django em memória para a cópia, gerou um manifesto dry-run e removeu a cópia. O SHA-256 da origem foi comparado antes/depois: `source_database_unchanged=true`.

Entradas do relatório [`2026-10-02/colophon-residuals.json`](2026-10-02/colophon-residuals.json), consultadas na cópia: dispositivos 214, 288, 312, 346, 348, 353 e 361 (normas 4, 6, 7, 9, 10, 11 e 12). Resultado: 7 normas analisadas; 7 propostas; manifesto dry-run `9bb14d1b2d6c8083a0ca458c169cc7616ab8e1a500bc23655852134b03e459e6`.

| Norma / dispositivo | Artigo final | Correção de texto | Publicação SAPL | Publicação OCR | Divergência | Vigência proposta |
| --- | --- | --- | --- | --- | --- | --- |
| 4 / 214 | Art. 4º | Sim | 2026-09-21 | 2026-09-21 | Não | 2026-09-21 |
| 6 / 288 | Art. 13 | Sim | 2026-09-21 | 2026-09-21 | Não | 2026-09-21 |
| 7 / 312 | Art. 8º | Sim | 2026-09-21 | 2026-09-21 | Não | 2026-09-21 |
| 9 / 346 | Art. 7º | Sim | 2026-09-09 | 2026-09-10 | **Sim** | Não proposta |
| 10 / 348 | Art. 2º | Sim | 2026-09-09 | 2026-09-10 | **Sim** | 2026-09-09 |
| 11 / 353 | Art. 5º | Sim | 2026-09-09 | 2026-09-10 | **Sim** | 2026-09-09 |
| 12 / 361 | Art. 4º | Sim | 2026-09-02 | 2026-09-02 | Não | 2026-09-02 |

As três divergências de data permanecem sem escolha automática. A proposta para norma 9 não inventa vigência a partir da data OCR divergente. Para as normas 10 e 11, a vigência proposta usa a publicação SAPL já existente, mas isso **não resolve** a divergência e não autoriza aplicação.

## Execução controlada na cópia QA — 2026-10-02

Foi criada uma cópia SQLite por `sqlite3.Connection.backup()` a partir da origem aberta em modo read-only. O `PRAGMA integrity_check` retornou `ok`; um backup adicional da cópia também passou no integrity check e teve hash de arquivo idêntico antes da aplicação. A origem foi hashada antes e depois e permaneceu igual (`source_database_hash_unchanged=true`).

Na cópia, foram aprovadas e aplicadas as sete propostas. O comando retornou `Correções aplicadas: 7`; o hash do manifesto aprovado foi `9bb14d1b2d6c8083a0ca458c169cc7616ab8e1a500bc23655852134b03e459e6`. Todos os artigos finais (dispositivos 214, 288, 312, 346, 348, 353 e 361) ficaram apenas com texto legal, sem assinatura/publicação/autoria. Nas normas 4, 6, 7 e 12, `data_vigencia` passou a igualar `data_publicacao` já registrada. Nas normas 9, 10 e 11, publicação e vigência permaneceram idênticas aos valores anteriores; o comando emitiu aviso de que as três divergências seguem para revisão. A invalidação de cache/embedding e a reconstrução do consolidado ocorreram pela rotina normal do comando.

Para separar limpeza do artigo da decisão sobre datas, o comando agora permite a correção textual quando `article_changes=true`, mas nunca atualiza datas em uma entrada com divergência SAPL/OCR. Uma divergência sem correção textual independente continua abortando antes de qualquer escrita. O teste `test_conflicting_publication_dates_allow_only_approved_article_cleanup` verifica a preservação das datas e a marcação `needs_review`.

A cópia SQLite, o backup e os manifestos temporários foram removidos ao fim da verificação; nenhuma cópia de corpus foi adicionada ao repositório.

## Gate antes de qualquer aplicação no corpus real

A autorização desta execução cobre somente a cópia QA temporária. Aplicar em produção continua exigindo nova autorização do usuário, manifesto revisado, backup verificado e hash exato. As datas divergentes das normas 9, 10 e 11 seguem marcadas para conferência documental/jurídica; o comando as preserva sem inferir nem substituir valores.

## Comandos verificados

`manage.py repair_legal_colophons --help` foi executado. As flags confirmadas são `--norma-id` repetível, `--manifest-out`, `--approved-manifest`, `--expected-manifest-sha256`, `--backup-verified` e `--apply`.

Exemplo de aplicação **somente depois da aprovação** e sempre com Django apontado a uma cópia descartável:

```powershell
python manage.py repair_legal_colophons `
  --norma-id 4 --norma-id 6 --norma-id 7 `
  --norma-id 9 --norma-id 10 --norma-id 11 --norma-id 12 `
  --apply `
  --approved-manifest CAMINHO_DO_MANIFESTO_APROVADO `
  --expected-manifest-sha256 HASH_EXATO_DO_MANIFESTO `
  --backup-verified
```

Para as normas 9, 10 e 11, essa execução autorizada pode limpar somente o texto do artigo final: se `article_changes=true` e houver divergência SAPL/OCR, o comando preserva publicação e vigência exatamente como estão e mantém `needs_review`. Sem alteração textual independente, a entrada conflitante continua abortando antes de qualquer escrita. O placeholder do hash não é um hash válido e deve ser substituído pelo SHA-256 recalculado do manifesto aprovado. Não use `USE_SQLITE=1` para esta operação: o settings atual fixa o nome em `BASE_DIR/db.sqlite3`; redirecione `connections.databases["default"]["NAME"]` dentro do processo QA, depois de criar e verificar a cópia isolada. Feche todas as conexões antes de remover os arquivos temporários.

## Rede de segurança

Já existem testes de manifesto obrigatório, bloqueio de manifesto stale, preservação de referências, separação entre artigo final e metadados editoriais, extração de publicação/vigência, invalidação de embeddings e dry-run idempotente:

```powershell
& "$env:TEMP\jurix-implementation-qa-20261002\venv\Scripts\python.exe" -m pytest -q src/tests/test_colophon_repair_plan.py src/tests/test_legal_parser.py
```

O manifesto e o backup foram descartados junto com a cópia QA; o hash exato do manifesto aprovado de sete entradas ficou registrado acima. Nenhum arquivo de corpus foi adicionado ao repositório. A nova cópia deve ser gerada para cada sessão de revisão, pois conteúdo/hash podem mudar.
