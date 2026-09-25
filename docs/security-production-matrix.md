# Matriz de segurança de produção

| Superfície | Controle implementado | Verificação exigida |
|---|---|---|
| Upload PDF/DOCX | limites, assinatura e isolamento | testes de tamanho, ZIP e processo |
| Storage key | rejeição de `..` e paths absolutos | teste de traversal |
| Sessão | hash em metadados | teste de isolamento entre sessões |
| CSRF | política explícita por endpoint | teste browser/API |
| Rate limit | configuração por proxy | smoke atrás de proxy real |
| Ollama | allowlist de modelos | teste de modelo não autorizado |
| Prompt injection | contexto demarcado + grounding | corpus adversarial |
| Secrets | checks de deploy | `manage.py check --deploy` |
| PostgreSQL | password obrigatória | compose de produção |
| Redis | cache compartilhado | readiness |
| S3 | credentials completas | auditoria de objetos |
| SSE | fechamento do generator | teste de disconnect |
| XSS | sanitização do front | suíte JS |
| Headers | CSP/HSTS/X-Content-Type | scanner de staging |

## Isolamento de dados

Usuários autenticados só podem consultar e mutar sessões, mensagens e anexos
associados ao próprio usuário/sessão. Qualquer endpoint que aceite um `id` deve
validar a propriedade antes de acessar o objeto.

## Prompt injection

Documentos anexados e texto recuperado são dados, não instruções. O prompt deve
tratar conteúdo externo como não confiável e a camada de grounding deve impedir
que a simples presença de uma instrução em um documento gere autorização para
executar ações.

## Segredos

Nenhum valor de produção deve aparecer em README, Compose ou logs. Exemplos de
ambiente devem usar placeholders e o gate de produção deve falhar quando um
segredo conhecido de desenvolvimento estiver ativo.
