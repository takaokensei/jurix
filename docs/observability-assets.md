# Assets de observabilidade

O diretório `deploy/observability/` contém regras de alerta e um dashboard inicial
para os sinais que o sistema já exporta. Os limiares devem ser calibrados no
ambiente de staging antes de serem tratados como SLOs definitivos.

Nunca transforme um alerta de groundedness em indicador de “qualidade jurídica”
por si só; ele é um sinal operacional para investigação.
