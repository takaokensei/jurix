# Limites arquiteturais v2

## API

A camada HTTP deve validar entrada, autenticação/autorização, rate limiting e
serialização. Regras de RAG e acesso a storage devem permanecer em serviços.

## RAG

`RAGService` orquestra retrieval, geração e política de resposta. Implementações
novas de retrieval devem ser isoladas em módulos próprios para reduzir a pressão
sobre o arquivo legado.

## Ingestão

Cada etapa deve ter contrato explícito de entrada e saída, idempotência e erro
recuperável. OCR, embedding e consolidação são workloads distintos e não devem
ficar acoplados ao request HTTP.

## Storage

Aplicação usa chaves lógicas, não paths físicos. Limpeza é responsabilidade de
comando operacional separado do auditor.

## Database

Índices de performance devem ser verificáveis por comando e pelo CI de release.
Nenhuma otimização baseada em “parece rápido” deve ser aceita sem medição.
