# Protocolo de adjudicação do gold jurídico municipal — Jurix/PGM

Este protocolo prepara a revisão humana do piloto científico P-020. Não contém
casos adjudicados, não declara documentos licenciados e não transforma saídas
do Jurix em referência correta. Até o cumprimento dos gates abaixo, os
experimentos são testes técnicos, não evidência de qualidade jurídica.

## Gate de entrada

Antes da anotação, a coordenação do estudo registra autorização institucional,
condição de uso por documento (`public_record_reviewed` ou `licensed`), IDs
pseudônimos dos revisores e responsável pela adjudicação, versão/hash do
protocolo e manifesto, método/seed e estratos da amostragem. A amostra científica
exige pelo menos 20 `norma_key` distintas e três `relation_chain_keys` reais;
documentos diferentes da mesma norma não contam como normas independentes.
Separar treino e teste por cadeia inteira. Acesso público ao SAPL não prova, por
si só, licença de redistribuição do PDF ou do pacote.

Se identidade, condição de uso, legibilidade ou versão documental forem
incertas, marcar a unidade como pendente/excluída e substituí-la apenas conforme
o método pré-registrado. Não escolher unidade mais fácil após observar o
resultado do Jurix.

## Pacote de entrada imutável

Congelar por unidade: chaves pseudônimas da norma/documento; jurisdição, espécie,
número e ano; URL oficial e ID SAPL quando disponíveis; origem e data de coleta;
SHA-256 do PDF e texto; papel (`original`, `republicacao`, `retificacao`,
`anexo` ou `indeterminado`); versão do extrator/texto e estado nativo/OCR;
páginas conferidas; condição de uso; estrato e razão de seleção.

Não sobrescrever pacote congelado. OCR corrigido ou nova edição gera novo hash e
exige revisão explícita das anotações dependentes. Não incluir peças processuais,
nomes de partes, dados pessoais ou documentos reservados. Publicar apenas os
trechos estritamente necessários e permitidos pela condição de uso.

## Anotação e adjudicação

Dois revisores anotam independentemente, sem ver predições do Jurix ou a
anotação um do outro. O responsável jurídico compara as fontes primárias e
resolve divergências. O executor técnico não adjudica fatos jurídicos nem
preenche alvo/data para fazer o teste passar.

1. **Identidade/edição:** conferir epígrafe no PDF contra catálogo oficial,
   espécie, número, ano e jurisdição; classificar original, republicação,
   retificação, anexo ou indeterminado. Filename e similaridade não provam
   identidade.
2. **Dispositivos:** conferir no PDF limites de artigo, parágrafo, inciso,
   alínea, item e anexo relevantes. Spans usam `[start,end)` no texto congelado
   e `quote == text[start:end]`. Marcar lacunas de OCR, tabelas e imagens; não
   completar texto ilegível silenciosamente.
3. **Relações:** rotular somente a ação sustentada pela fonte (`REVOGA`,
   `ALTERA`, `ADICIONA`, `SUBSTITUI`, `REGULAMENTA` ou `REFERENCIA`), dispositivo
   de origem, alvo tipado, escopo, citação literal e offsets. Menção temática
   não é alteração. Ambiguidade fica `unresolved`/`pending_review`; não inferir
   revogação tácita.
4. **Datas:** distinguir data do ato, publicação, vigência, eficácia específica,
   retificação e coleta. Cada data confirmada aponta a cláusula e fundamento.
   “Na data da publicação” requer data oficial comprovada. Assinatura, metadata
   importada e filename não substituem essa evidência; conflito fica
   `unknown`/`candidate`.
5. **Estado/cobertura:** registrar norma e dispositivo separadamente como
   `modified`, `revoked`, `unchanged_in_checked_scope`, `vetoed` ou
   `not_reconstructable`. Ausência só vale no escopo e intervalo de fontes
   efetivamente conferidos; nunca significa vigência universal. Registrar atos
   posteriores examinados e lacunas.
6. **Consulta do experimento:** congelar pergunta, intenção (dispositivo,
   norma, relação, tema ou história), data de referência, fontes/citações
   esperadas e se a resposta deve abster-se antes de executar qualquer braço.
   Gabarito inclui fontes primárias e limites, não somente uma resposta livre.

## Contratos do repositório

Unidades seguem `manifest.v2.schema.json`; anotações seguem
`annotation.v2.schema.json`. Registro humano exige `review_kind="human"`,
`status="adjudicated"`, ID pseudônimo e timestamp ISO 8601 com fuso. Hash do
texto, versão e extrator precisam coincidir com o pacote congelado. Cada span
possui ID e hierarquia; cada evento aponta para span, ação, alvo ou estado não
resolvido, escopo, data/estado e evidência hash-bound. Preservar anotações
independentes, divergências, exclusões e decisão; nunca sobrescrever a trilha.

Não marcar como humano caso gerado por teste, IA ou conta sintética. O campo de
revisão não autentica uma pessoa: a coordenação mantém autorização/identidade
fora do benchmark público.

## Avaliação pareada e publicação

Somente após congelar o gold, executar baseline, grafo e grafo-temporal nas
mesmas consultas, revisões de texto, modelo, parâmetros, orçamento de tokens,
hardware e estados de cache pré-especificados. Guardar predições separadas do
gold, vinculadas a `case_id`, braço, repetição, revisão do corpus e latências.
Nunca alterar o gold após observar as predições.

Métricas anteriores aos gates são exploratórias e devem ser rotuladas como
técnicas. Alegação científica exige ≥20 normas independentes adjudicadas, ≥3
cadeias adjudicadas, condição de uso resolvida, manifesto/hash de amostragem
correspondente, ausência de vazamento por cadeia e análise pareada do protocolo.
Publicar resultados negativos, exclusões, denominadores, incerteza e limites;
não generalizar para toda a legislação de Natal nem para processos da PGM.

Validar schemas, hashes, spans, identidade, revisão, cobertura e limiares com
`scripts/validate_municipal_corpus.py` e os avaliadores existentes. A validação
estrutural não prova correção jurídica: fonte primária e adjudicação de
especialista continuam obrigatórias.

## Estado deste gate

No momento da criação deste protocolo, não há manifesto PGM adjudicado com 20
normas/3 cadeias nem revisão independente por dois anotadores e um responsável
jurídico registrada. Não renomear amostras sintéticas como gold. P-020 e a
validade científica continuam pendentes até a conclusão humana e a validação do
manifesto de amostragem.
