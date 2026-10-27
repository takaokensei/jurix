# Correções da auditoria de setembro de 2026

## Recuperação e integridade (achados 1–15)

- Resultados lexicais e híbridos compartilham o contrato de scores consumido pelo RAG.
- Similaridade mínima é propagada e aplicada ao primeiro resultado também; escopo e status são independentes.
- Busca lexical usa termos determinísticos, filtros antes do limite e ordenação por cobertura de termos no banco.
- SQLite usa recuperação lexical sem depender de embeddings; fontes retornadas correspondem aos trechos incluídos no contexto.
- Reconciliação usa relações reais, separa número/ano e referências a artigos/normas, e exige correspondência de tipo.
- Reingestão preserva texto extraído. Mudanças na URL do documento invalidam embeddings e sinalizam reprocessamento.
- Ingestão bounded usa total_fetched; bulk valida parâmetros e limita a última página.

## Chat e histórico (achados 16–28)

- O adaptador anônimo devolve mensagens, ID e slug no mesmo contrato da interface autenticada.
- IDs locais são aceitos pelo estado, navegação e lista de sessões. Testes recriam a página com armazenamento anterior.
- Respostas parciais anônimas são salvas durante o recebimento. Fechamento do gerador salva o parcial autenticado.
- A identidade da sessão autenticada é emitida antes da geração. Falhas de gravação não emitem conclusão bem-sucedida.
- EOF prematuro, falhas do Ollama e erros SSE são tratados como interrupções. Não há segunda geração automática via batch.
- Finalização assíncrona é aguardada. Erros ficam junto à resposta afetada; mensagens anteriores permanecem visíveis.
- Scroll considera a posição anterior à mudança de altura. Citações procuram fontes dentro da própria resposta.
- Histórico remoto tem cursor assinado por sessão e botão para carregar mensagens anteriores.
- Falha de localStorage mantém uma cópia em memória e avisa que ela não sobreviverá à saída da página.
- O observador da lista suspende a observação durante suas próprias alterações, evitando ciclo infinito.

## Anexos e testes (achados 29–32)

- Parsing ocorre em processo separado, com timeout de 20 segundos, até 200 páginas PDF, 32 MiB de DOCX descompactado e 60 mil caracteres de saída.
- Em Linux/Unix, o processo também recebe limites de memória (512 MiB) e CPU (15 segundos). No Windows esses limites específicos de sistema operacional não são aplicados; timeout e limites de conteúdo continuam ativos.
- python-docx é dependência declarada.
- Limpeza de anexos expirados funciona sem retorno do usuário: tarefa Celery a cada 30 minutos, com TTL de duas horas.
- Testes cobrem contratos reais, interrupção, recarga, paginação, seleção de fontes e documentos. A suíte não deve realizar chamadas reais a Ollama/SAPL.

## Ativação e limites de validação

As imagens Docker precisam ser reconstruídas para instalar python-docx. O novo serviço `beat` do Compose precisa estar ativo para executar a limpeza periódica; mantenha somente um agendador beat por instalação. Também existe `python manage.py cleanup_chat_attachments` para execução operacional manual.

Não há migração de schema nova. A sincronização automática de novas normas não foi implementada.

Os testes JavaScript usam jsdom. Layout visual, interação real do navegador e desconexão de rede em produção ainda merecem validação operacional. Persistência no encerramento do gerador não protege contra encerramento abrupto do processo ou queda do banco.
