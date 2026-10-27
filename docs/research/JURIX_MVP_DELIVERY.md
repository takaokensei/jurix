# Jurix MVP — execução e evidências de entrega

## Estado em 27/10/2026

**Em implementação. O MVP completo ainda não passou G-01–G-12.**
Referência imutável: `JURIX_MVP_CLOSURE_PLAN_2026-10-27.reviewed.md`, SHA-256
`eb0d1973d1d9856ac4cc68bb847c589a458aab99f5ff0d9bda96d05b67a8b586`.
Checkout: `L:\Jurix`, branch `main`, HEAD `1ac3ab75`, incluindo alterações anteriores.
Não foram feitos commit, push, merge ou troca de branch nesta execução.

## Inicialização atual

Na raiz do checkout, executar:

```powershell
pwsh -NoProfile -File scripts/start_pgm_mvp.ps1 -Port 8294
pwsh -NoProfile -File scripts/status_pgm_mvp.ps1 -Port 8294
```

URL: <http://127.0.0.1:8294/assistente/>.
O launcher utiliza somente o Compose QA existente, project `jurix-normative-qa`,
com DB `55432`, Redis `16380` e volume comum `audit_qa_root` do web/worker.
A identidade inclui HEAD e digest dos arquivos de runtime, inclusive código
não rastreado. Porta com build incompatível é recusada sem encerrar o processo.
Foram executadas duas inicializações compatíveis e um caso real de recusa de
build antiga. Apenas os web/worker QA iniciados nesta execução foram depois
recriados para carregar as alterações; serviços de produto não foram alterados.
O launcher verifica migrations sem aplicá-las. O QA já tinha `legislation.0031`.

O modelo configurado observado é `llama3` (`llama3:latest` instalado), contexto
de recuperação de 8.000 caracteres; Ollama `0.15.4`. Isto é identificação da
configuração, não medição de inferência/TTFT ou aprovação de G-10.

## Progresso por pacote

- **M-01: implementação e runtime verificados.** Endpoint QA de identidade,
  digest de build, launcher/status, quatro serviços saudáveis e modelo identificado.
  Não substituir isso por uma alegação de prontidão de todos os demais gates.
- **M-02: fontes materializadas e verificadas.** Corpus operacional separado do
  Gold, 20 normas e 23 PDFs, reutilização de extrações e novas extrações candidatas
  apenas onde faltavam. Todos os 23 PDFs retornaram HTTP 200 anonimamente no QA;
  cada corpo recebido corresponde ao SHA-256 esperado. Novas edições do DOM
  continuam candidatas. Estado de revisão/aceitação/vínculo dos documentos
  preexistentes foi comparado antes/depois e preservado.
- **M-02, readiness complementada pela M-05/M-06:** fontes, cláusulas, alvos e
  datas foram associados aos eventos. A revogação parcial com data foi ensaiada
  em D−1/D/D+1, separadamente da mera integridade dos arquivos.
- **M-03: base de resolução implementada e testada.** Aliases do manifesto,
  identidade tipada, edição por referência, seguimento e ambiguidade localizada.
  “Compilação” foi incluída no caminho documental existente. O roteamento do
  chat para todo esse corpus operacional pertence à M-08 e segue pendente.
- **M-04: catálogo e pesquisa integrados.** As 20 normas estão no catálogo
  comum, paginadas, com filtros e abertura de PDF/índice de artigos do piloto.
  Busca `258/2024` → LC 258 → Art. 260 → PDF página 60 foi usada no navegador real.
  A pesquisa comum também encontra a identidade e abre a mesma ficha, sem
  similaridade fictícia. Sidebar e demo apontam à coleção operacional genérica.
  Persistência do escopo por conversa depende da M-08; todas as larguras seguem M-11.
- **M-05: eventos documentais implementados.** Nove relações das quatro adoções
  IA existentes foram novamente verificadas contra hash, extração e offsets;
  três referências literais não resolvidas da LC 258 continuam sem alvo atribuído.
  A compilação alternativa da LC 55 é evidência do conflito, não uma correção
  automática da numeração. Trechos com omissões não substituem um alvo integral.
- **M-06: projeção experimental implementada e ensaiada.** Substituição integral,
  acréscimo e revogação por alvo estrutural; ordenação por efeito, conflito material,
  fronteira da compilação, descendentes, veto, não repristinação por inferência e
  identidade determinística estão cobertos por testes. LP 275, Art. 21: texto
  mantido em 26/03/2025 e revogado no escopo em 27–28/03/2025; Art. 20 intacto.
  CTM/LC 271: cotejo textual disponível. LC 208/261: cotejo com data desconhecida.
  LC 55, Art. 34: conflito explícito, sem redação definitiva escolhida.
- **M-07: ficha comum implementada.** As 20 normas abrem pela identidade, com
  abas, comparação, eventos, grafo, evidências e exportação JSON/Markdown.
  Comparação/grafo/fontes compartilham `casefile_id` e revisão; links exportados
  resolvem PDFs por SHA-256, sem localhost/UUID como identidade portátil.
  As três cadeias foram abertas no navegador. A leitura por teclado completa,
  todas as larguras e integração dessa ficha com o chat ainda não estão certificadas.
- **M-08–M-12: pendentes.** Chat integrado ao novo corpus/dossiê, streaming desse
  percurso, benchmark 28×3, aceitação completa e restore independente não foram
  concluídos. Não considerar a melhoria da ficha como conclusão do MVP.

## Corpus operacional

Revisão ativa observada:
`2ac9edb525e58228c18824cbce16e33955ba7993f8299a84116a409cb5da20f7`.
Seleção: `benchmarks/corpus/municipal_natal/pilot-source-selection.v1.json`.
Não contém perguntas, respostas esperadas ou rótulos `expected_*`.

O builder gera manifesto/sidecars imutáveis com texto integral da extração,
hash, mapa de páginas, identidade/edição e dispositivos candidatos. Reutiliza
o parser e o detector de atos existentes; não promove segmentações ao banco.
Um PDF com vários atos é delimitado por epígrafes; anexo de outro ato não pode
ocultar uma lei posterior no mesmo Diário. Foram corrigidos zeros à esquerda e
número antigo `1.894/69`, preservando o ano comprovado na epígrafe completa.
O texto de colofão não deve ser incorporado ao último dispositivo.

Dois downloads DOM retornaram HTTP 403. Os PDFs foram recuperados do pacote QA
local previamente existente, com igualdade de hash verificada, sem substituir
arquivos originais. Seis blobs faltavam no volume Docker comum e foram copiados
após verificação; 23/23 hashes desse volume foram então conferidos.

Preparação host e relatórios operacionais ficam no SATA em
`L:\Jurix\data\mvp-temp\closure-20261027` e `L:\Jurix\data\mvp-runtime`.
O root de testes é separado: `L:\Jurix\data\mvp-temp\tests-20261027`.
O corpus do web/worker está no volume QA existente, não em uma nova cópia de
banco. A distribuição entre host/volume ainda será encapsulada e restaurada
pelos comandos finais da M-12; não considerar esta preparação um instalador pronto.

## Verificações executadas

- Baseline inicial build/Compose: **5 passed**.
- Build/runtime e corpus/guards: **12 passed**, depois **68 passed** nos grupos
  correspondentes; os totais se sobrepõem, não somar como testes distintos.
- Regressão de acesso documental/guards/gazette/build: **102 passed**.
- Parser de referências + RAG documental + corpus: **252 passed**.
- Workspace e catálogo, com root QA de testes isolado: **117 passed, 1 skipped**.
- Última regressão focal de catálogo/documentos/build: **14 passed**.
- Projeção revisada + acesso + adaptadores piloto: **54 passed**, com dois
  warnings de testes antigos ao sobrescrever configuração DATABASES.
- Regressão posterior de workspace/catálogo/adaptadores: **137 passed, 1 skipped**.
- Último grupo, após os guards de omissões/acréscimo e conservação do rótulo do
  parágrafo: **53 passed**. Estes totais se sobrepõem aos anteriores.
- JavaScript do grafo/abas: **11 passed, 1 skipped**; o skip é o teste browser
  opcional desse comando. O smoke real IAB foi realizado separadamente.
- Runtime HTTP: 20 fichas comparadas com o serviço puro, exportações Markdown e
  JSON e 23 PDFs (SHA-256 do corpo recebido) passaram. Registro inicial em
  `evidence/mvp-projection-runtime-20261027.json`; ele identifica sua build,
  anterior ao ajuste de rótulo estrutural e foco no parágrafo da LC 208.
  A repetição posterior passou em `evidence/mvp-projection-runtime-20261027.v2.json`,
  conferindo a build `f6194f53…`, as 20 fichas e os limites D−1/D/D+1 com o código atual.
- Validador do conjunto IA congelado: passou com 20 normas, 41 recortes, 13 eventos
  e 28 perguntas; não constitui validação jurídica/humana independente. A `.venv`
  não tinha `jsonschema`; o comando foi repetido com `uv run --no-project --with
  jsonschema`, cache no SATA, sem alterar dependências do repositório.
- Testes adicionais cobrem publicação concorrente, interrupção antes da ativação,
  detecção de adulteração, blob ausente/divergente, caminho fora do root, colisão
  de espécie normativa, exclusão de rótulos Gold e isolamento QA/produção.
- Ruff nos módulos novos/alterados desta execução: passou.
- `git diff --check`: passou; warning CRLF preexistente no log de auditoria antigo.

Uma execução do teste legado de catálogo falhou ao usar o root operacional com
o manifesto real ativado. A causa era contaminação do ambiente de teste por dados
do piloto; foi repetida no root de testes separado. Nenhuma expectativa de
ausência de normas consolidadas foi enfraquecida para esconder o problema.

O navegador real confirmou o catálogo, pesquisa, índice experimental e abertura
do PDF em `#page=60`. Capturas:

- `screenshots/mvp-closure-20261027/lc258-art260.png`.
- `screenshots/mvp-closure-20261027/lc258-art260-pdf-page60.png`.
- `screenshots/mvp-closure-20261027/pilot-repeal-evidence.png`.
- `screenshots/mvp-closure-20261027/pilot-partial-repeal-result.png`.
- `screenshots/mvp-closure-20261027/pilot-ctm-comparison.png`.
- `screenshots/mvp-closure-20261027/pilot-lc208-comparison.png`.
- `screenshots/mvp-closure-20261027/pilot-lc258-graph.png` (página completa).

Isto é smoke focal desktop. Não equivale à M-11, auditoria WCAG, uso por
procuradores, benchmark das respostas nem demonstração de vigência consolidada.

Na última sessão IAB, clicar na própria aresta abriu o mesmo painel da lista;
o link por hash redirecionou ao PDF com `#page=60`. Entretanto, a superfície do
visualizador nativo ficou cinza, inclusive após recarregar com a janela visível.
HTTP 200, Content-Type PDF e SHA-256 do corpo passaram; os logs do navegador não
mostraram erro. A causa não foi estabelecida e a leitura visual desse novo
percurso **não está aprovada**. Evidência do estado em
`screenshots/mvp-closure-20261027/pilot-graph-source-pdf-blank.png`.
Investigar na M-11; não interpretar a verificação HTTP como prova visual.

## Ampliações estreitas de arquivos e próximos passos

`scripts/pgm_mvp_runtime.py` concentra a implementação comum dos dois launchers.
Identidade também exigiu settings, endpoint de health e detalhe técnico do topbar.
`pilot_catalog.py` evita adicionar a lógica de corpus à view monolítica.
`gazette_act_candidates.py` recebeu o reparo de identidade exigido pelos PDFs reais.
`document_views.py` usa associação por hash ao manifesto ativo para disponibilizar
somente fontes do piloto no QA e mostrar o índice experimental sem aceitar/revisar
o documento. Testes negativos preservam o bloqueio fora do perfil QA.

Continuar pela M-08 e ligar o assistente ao corpus operacional e ao dossiê já
disponíveis, sem usar respostas Gold na geração. Preservar conflitos da LC 55,
alvos não resolvidos da LC 258 e a divergência Diário/colofão da LC 271. O início
experimental usa publicação e cláusula próprias; não atribui automaticamente
efeitos fiscais/especiais. A LC 258 usa o Art. 266 e a edição do DOM de 27/12/2024,
com cálculo experimental de início em 27/03/2025; data da sessão não foi usada.

`pilot_views.py` e os dois parciais de ficha/índice isolam a adaptação QA para não
adicionar novas regras específicas de leis à view monolítica. O exportador
Markdown reutiliza `evidence_export.py`; o grafo reutiliza seu renderer existente.
Foram mantidos `_reviewed_base()` e os demais guards do percurso revisado.
M-08–M-12 e G-01–G-12 continuam exigindo suas verificações próprias.
