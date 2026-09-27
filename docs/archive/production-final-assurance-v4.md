# Production Final Assurance v4

## Objetivo

Este documento fecha o contrato entre CI, staging e promoção. Ele não afirma correção jurídica automática; a qualidade jurídica depende de corpus revisado e baseline estável.

## RAG

O caminho de produção é: retrieval → contexto → geração → grounding estrito → policy → fallback seguro → cache somente após aceitação. O streaming mantém `RAG_STREAM_PROVISIONAL_OUTPUT=false` por padrão, evitando que uma resposta ainda não validada seja tratada pelo navegador como resposta final.

Uma resposta é rejeitada por claim sem suporte, número incompatível, negação incompatível, citação incompatível, excesso de certeza, baixa pontuação estrita, diversidade exigida não atendida, limite de tamanho ou ausência de contrato estrito.

## pgvector

Antes da promoção: `python manage.py verify_vector_index` e `python manage.py verify_vector_query_plan`. O segundo comando deve demonstrar acesso indexado. Seq scan em corpus de produção é bloqueador até a causa ser resolvida.

## Storage

Produção distribuída deve usar S3/MinIO. Single-host pode usar volume persistente somente quando explicitamente permitido pela configuração. Auditagem de storage deve ocorrer antes e depois de operações de retenção/migração.

## Ingestão

Downloads SAPL respeitam byte limit e timeout. OCR respeita páginas, pixels e timeout. Documentos fora do limite são marcados para revisão e não devem consumir recursos indefinidamente.

## Staging

Executar health live/ready, pesquisa, RAG, streaming, anexo, histórico, restart web/worker/redis, falha de Ollama e falha de SAPL. O staging deve usar dados/segredos separados.

## Rollback

Antes da promoção: backup PostgreSQL verificado, volume/bucket de anexos confirmado, imagem identificada por digest, migrations compatíveis e procedimento de rollback ensaiado.

## Observabilidade

Monitorar p95 da API e RAG, erros Ollama, idade das filas Celery, rejeições de grounding, falhas SAPL, inconsistências de storage e utilização de PostgreSQL/Redis.

## Ingestion architecture

`src/apps/ingestion/tasks.py` continua como fachada de compatibilidade das tasks públicas. O gate de contrato impede remoção acidental durante a divisão futura em módulos menores. A separação estrutural completa deve ser acompanhada por testes de task-level antes de remover qualquer implementação duplicada.

## Limites

Nada neste contrato prova correção de interpretação jurídica, atualização de legislação externa ao corpus, disponibilidade de dependências externas ou segurança da infraestrutura fora do repositório.

## Checklist

- [ ] CI verde
- [ ] migrations check
- [ ] pytest completo
- [ ] testes browser/frontend
- [ ] benchmark de contrato RAG
- [ ] corpus jurídico revisado para release jurídica
- [ ] índice vetorial verificado
- [ ] plano vetorial verificado
- [ ] storage audit
- [ ] staging smoke
- [ ] backup verificado
- [ ] rollback ensaiado
