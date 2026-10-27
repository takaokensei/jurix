# Adoção da revisão assistida por IA para avanço do piloto

## Decisão do responsável pelo projeto

Em 18/10/2026, após receber a revisão documental dos casos A–D, o usuário
autorizou considerar seus resultados como base consolidada para avançar o
plano. Esta decisão passa a permitir o avanço técnico do piloto R-04/R-05 com
consolidação assistida por IA nos recortes documentalmente sustentados.

A autorização é de adoção para desenvolvimento e experimentação do projeto.
A autoria da análise permanece IA; não houve revisão jurídica humana,
adjudicação independente, estudo com procuradores ou certificação institucional.
Esta decisão não declara esses procedimentos realizados.

O roadmap original e o protocolo científico permanecem preservados. Este
adendo substitui a exigência de aguardar revisão humana como condição para
avançar o desenvolvimento do piloto nos recortes abaixo. Não altera o aceite
da avaliação científica R-07 nem resolve divergências entre documentos.

## Base documental congelada

Pacote externo desta sessão:

- Diretório: `L:/temp/jurix-document-review-20261018/`.
- Relatório: `REVISAO_DOCUMENTAL_JURIX.md`.
- SHA-256 do relatório:
  `3fe1a49bca30c4f76ede71bf75842c580a06aeea8849b1f87f4ab79c2d70722e`.
- Minuta: `review-draft.json`.
- SHA-256 da minuta:
  `667d20e090ffdb9808ff2adebe6e02f614c5326091b14f659a87449e25198db9`.
- Inventário e recortes: `package-v2/sources.json` e
  `package-v2/spans.json`.
- Validação técnica executada: 20 hashes de PDF, 11 hashes de texto congelado,
  23 recortes de base e 18 recortes de eventos conferidos por
  `quote == text[start:end]`.

O pacote é local, não um recurso instalado com o repositório. Uma futura
importação deve verificar arquivos/hashes e resolver documentos por identidade
e conteúdo, sem presumir que os UUIDs do QA existam em outro banco. O pacote
inicial `package/` e a minuta original permanecem preservados; o uso posterior
recebe decisão/versionamento próprio.

## Recortes adotados para a consolidação assistida do piloto

### A — CTM, Art. 20, e LC 271/2025

Adotar o cotejo entre o corpo do Art. 20 nas três compilações municipais
conferidas e o texto substitutivo da LC 271/2025, Art. 1º. A publicação
observada no DOM de 16/12/2025 integra a evidência, preservando a informação
divergente de 17/12 no colofão da reprodução SAPL.

O escopo adotado é esse dispositivo e seu ato modificador. Não se declara que
o CTM inteiro foi consolidado ou que todas as mudanças posteriores até
18/10/2026 foram examinadas. Não converter uma data de publicação observada
em prova de todos os efeitos tributários.

### B — LC 258/2024, revogação parcial e transição

Adotar a identificação textual dos vínculos do Art. 260, incisos III, IV, V e
VI, com os documentos-alvo correspondentes no pacote. O inciso V atinge
somente o Art. 21 da LP 275/2009, não a lei inteira. Preservar o conteúdo
histórico dos dispositivos e os Arts. 259, 262 e 266 como parte da análise
temporal pertinente.

Os incisos I, II e VII ficam com alvo tipado não resolvido por divergências
documentais. Eles continuam visíveis e não recebem uma identidade inventada.
A data calculada a partir da vacância fica vinculada ao fundamento e ao
escopo verificado; o resultado não decide automaticamente processos reais.

### D — LC 208/2022, Art. 18, § 2º, e LC 261/2025, Art. 118

Adotar o cotejo textual entre os dois dispositivos conferidos. A chave
canônica nula do registro QA é uma pendência técnica de reconciliação; não
constitui, por si só, prova de que se trata de outra lei.

A adoção do cotejo não aprova silenciosamente a associação cadastral nem
confirma a data de efeitos: a publicação da LC 261 no DOM e a cobertura de
atos posteriores não foram conferidas integralmente no pacote.

## Divergência que permanece aberta

O caso C, LC 55/2004, Art. 34, contém divergência entre a numeração do ato
modificador e a compilação de 2019. A decisão de adoção não autoriza
renumerar o texto ou apresentar uma redação única como documentalmente
resolvida. A comparação e o conflito podem integrar o piloto enquanto a
redação em cada data permanece não reconstruída.

Os demais segmentos da LC 271 foram mapeados na minuta, mas não receberam
todos os cotejos antes/depois. Não ampliar o escopo adotado para esses
segmentos, para a LC 141 ou para todo o acervo por associação.

## Representação e condições de implementação

1. Identificar a base usada no piloto como **consolidação assistida por IA**,
   com escopo, versões, fontes, hashes e decisão do responsável rastreáveis.
2. Distinguir aceitação para o piloto de revisão humana e de completude
   temporal. Um resultado pode estar adotado para uso experimental sem que
   todos os intervalos temporais estejam reconstruídos.
3. Não preencher autoria humana, adjudicação, estado de gold ou conclusão
   de estudo com participantes para representar esta autorização.
4. Não mudar globalmente o status de todos os documentos para `consolidated`
   nem aceitar uma extração inteira quando a conferência se limitou a alguns
   dispositivos. Não reclassificar uma compilação como publicação original.
5. Se o contrato atual só admite aprovação humana, implementar proveniência
   explícita para a adoção por IA. Não reutilizar uma conta sintética como
   autor jurídico humano nem enfraquecer o contrato científico para fazer o
   dado passar.
6. Manter o trabalho no QA isolado. Esta decisão não ordena promoção no banco
   de produto, commit, push, merge, troca de branch ou operação destrutiva.
7. Preservar ambiguidades materiais em cada representação: chat, comparação,
   grafo e exportação. Ausência de alterações encontradas não equivale a
   prova de vigência universal.

## Efeito sobre o próximo trabalho

R-04/R-05 podem avançar com A, B e D como percursos de consolidação assistida
nos escopos definidos, sem voltar a pedir autorização apenas pela ausência de
revisor humano. Os contratos de proveniência e as pendências documentais são
parte da entrega, não motivo para bloquear todo o desenvolvimento.

A próxima implementação deve fazer esses percursos compartilharem um
registro de caso versionado entre comparação, grafo, chat e exportação,
testando também os negativos de identidade, escopo e data. O caso C permanece
um caso real de conflito, útil para testar a apresentação e a abstenção.

R-07 continua sem adjudicação independente ou estudo de campo concluídos.
As pendências técnicas já registradas de R-03/R-08 também não são encerradas
por esta decisão.

Este registro formaliza a adoção. Nesta etapa não foram alterados status,
extrações, vínculos, eventos ou revisões no banco; a integração operacional
no produto ainda requer a implementação dos contratos acima.
