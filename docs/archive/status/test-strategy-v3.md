# Estratégia de testes v3

## Unitários

Cobrem funções determinísticas: parsing, grounding, policies, serialization,
limits e utilitários.

## Integração

Cobrem PostgreSQL/pgvector, Redis, Django ORM, migrations e storage.

## Contratos

Validam que scripts de release, manifests e configurações permanecem compatíveis
com o deployment.

## Adversariais

Cobrem prompt injection, citações inexistentes, números alterados, negação,
documentos grandes e sessões cruzadas.

## Browser

Cobre streaming, estados de erro, navegação por teclado, acessibilidade básica e
persistência da sessão.

## Performance

A performance não é garantida por número fixo de testes. Ela deve ser medida no
corpus e infraestrutura de staging, com p95/p99 registrados.
