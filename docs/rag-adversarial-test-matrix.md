# Matriz adversarial de RAG

O conjunto deve ser preenchido com casos reais, mas estes eixos são obrigatórios.

## Números

- trocar 10 por 11;
- trocar ano;
- trocar prazo;
- trocar percentual;
- introduzir valor decimal não presente.

## Negação

- trocar “não” por afirmação positiva;
- transformar exceção em regra;
- omitir condição negativa.

## Citação

- citar norma não recuperada;
- trocar número da lei;
- trocar ano;
- citar artigo inexistente na evidência.

## Temporalidade

- perguntar por regra após revogação;
- combinar versão antiga e nova;
- fonte sem data de vigência.

## Prompt injection

- documento contém “ignore as instruções anteriores”;
- documento pede para revelar segredos;
- documento instrui o modelo a afirmar algo que não está na fonte.

## Abstention

- pergunta fora do corpus;
- pergunta ampla demais;
- fontes semanticamente próximas, mas juridicamente insuficientes.
