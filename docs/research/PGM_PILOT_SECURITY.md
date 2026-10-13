# Segurança e privacidade — piloto Jurix/PGM

Status: nota técnica do checkout local em 08/10/2026. Não é política aprovada pela PGM, análise jurídica institucional, pentest ou autorização para produção.

## Fronteiras verificadas no código

- **Contas:** não há cadastro público; login aceita contas provisionadas e rejeita redirecionamento externo. Ações autenticadas usam sessão Django. Ver `src/apps/legislation/workspace_views.py` e `src/tests/test_workspace_auth.py`.
- **Conversas:** sessões persistidas pertencem a `ChatSession.user`; endpoints de detalhe filtram pela conta autenticada. Visitantes recebem lista vazia, e o cliente não recebe acesso a sessões persistidas de terceiros. Ver `src/apps/legislation/api_chat.py` e `src/tests/test_chat_sessions_api.py`. O histórico autenticado não tem política de expiração definida neste checkout.
- **Conferência de fundamentação:** a rota exige login. O texto enviado é processado na requisição e não é gravado como conversa; o cache do job guarda somente proprietário, estado e progresso, com TTL de 900 segundos. Status/cancelamento conferem o proprietário. Ver `src/apps/legislation/workspace_views.py` e `src/tests/test_foundation_check_workspace.py`. Isso não garante ausência em logs de infraestrutura, browser ou captura operacional fora do serviço.
- **Anexos:** vinculados a hash da sessão, com limite atual de 10 MiB por arquivo, cinco arquivos, extração isolada e TTL configurado por padrão em duas horas. O cleanup é acionado por requisições e há comando operacional separado; a expiração do registro, sozinha, não comprova remoção imediata do blob. Confirmar a agenda do comando e o backend de storage antes de piloto. Ver `src/apps/legislation/attachment_service.py`, `src/apps/operations/management/commands/prune_attachment_storage.py` e `config/settings.py`.
- **PDFs candidatos:** somente norma/documento aprovado sob condições documentais aceitas pode ser público. Candidatos ficam ocultos para visitantes; acesso de triagem depende de perfil staff, permissão Django ou da flag explícita de QA com `DEBUG`. Hash, tamanho, caminho confinado e cabeçalhos privados são verificados no serving. Ver `src/apps/legislation/document_views.py` e `src/tests/test_normative_document_access.py`.
- **Revisão:** registrar identidade, aceitar extração e revisar segmentação exigem conta ativa, staff e permissões específicas. POST usa CSRF e fingerprint para bloquear revisão obsoleta. O modelo atual é baseado em permissões Django globais, não em escopo por setor/unidade ou atribuição de caso.
- **Dossiês e versões de evidência:** são filtrados por proprietário e coleções próprias. Não compartilhar conta de revisor; não há fluxo de compartilhamento interinstitucional aprovado.
- **Provedores de IA:** a rota de resposta pública e o assistente podem enviar a pergunta e evidência recuperada ao provedor configurado no servidor. Uma chave/API cadastrada não constitui autorização para transmitir peças, dados pessoais ou conteúdo sigiloso. Uso de provedor externo com conteúdo PGM permanece desabilitado até política, avaliação de fornecedor e autorização organizacional.

## Política mínima proposta — requer aprovação institucional

1. Antes de qualquer piloto, definir controlador, finalidade, base legal, classes de informação permitidas, responsáveis por acesso, retenção, descarte, resposta a incidente e contato do encarregado. Não inserir processos, partes, pareceres internos ou peças reservadas neste ambiente.
2. Iniciar exclusivamente com legislação e documentos públicos autorizados. Conteúdo colado em `/conferir/` deve continuar efêmero por padrão; salvar um dossiê exige ação afirmativa e rótulo de classificação. Não adicionar retenção de texto sem decisão documentada.
3. Provisionar usuários nominalmente, aplicar mínimo privilégio, separar consulta/revisão/administração e revisar acessos. Até haver autorização, não criar contas PGM nem elevar permissões para demonstrar um fluxo.
4. Confirmar agenda e resultado do cleanup de anexos; duas horas é configuração técnica padrão, não prazo institucional aprovado. Definir também retenção de sessões, logs, backups, métricas e eventuais caches.
5. Restringir provedores de IA a execução local aprovada para dados autorizados. Não permitir endpoint/API externo para peças ou conteúdo sigiloso sem aprovação de segurança, privacidade, contrato e configuração de não treinamento/retenção compatível.
6. Antes de ativar produção: plano de migration revisado, backup e restore em cópia isolada, teste de permissões/IDOR/CSRF, worker/beat observáveis, TLS/cookies/hosts endurecidos, alertas, plano de rollback e aceite escrito do responsável operacional.

## Gaps que impedem declarar o piloto seguro para casos da PGM

- `manage.py check --deploy` foi executado no profile QA e falhou como gate de produção: `DEBUG=True`, chave de deployment inadequada e avisos para HSTS, HTTPS redirect e cookies seguros. Isso não inspeciona um deployment distinto; os detalhes e limites estão em `docs/research/NORMATIVE_IMPLEMENTATION_PROGRESS.md`.
- Não existe política institucional aprovada de retenção de histórico, anexos, logs ou backups; tampouco confirmação de que o job de limpeza roda na frequência pretendida.
- Não foi ensaiado restore de backup. Nenhum deployment, domínio, TLS, storage remoto ou contas PGM foram validados neste documento.
- Não houve pentest independente nem varredura de dependências pós-diff. Os testes automatizados são regressões de contrato, não prova de ausência de vulnerabilidades.
- Nenhum conteúdo de processo reservado foi usado. O QA de navegação usa PDFs legais reais pendentes de revisão; “público” não significa automaticamente licenciado para republicação ou autorizado para uso institucional.

## Testes automatizados associados

`src/tests/test_pgm_authorization.py` complementa os testes existentes para isolamento de sessões, proteção contra CSRF e negação de revisão sem privilégio. Os dados criados pertencem ao banco de teste QA e não alteram acervo, revisões ou contas reais.
