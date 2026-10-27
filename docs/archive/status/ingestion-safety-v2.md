# Segurança da ingestão SAPL v2

## Download

O cliente deve limitar:

- timeout de conexão;
- timeout de leitura;
- tamanho total do corpo;
- redirecionamentos;
- tipos MIME aceitos;
- espaço temporário usado.

## PDF

Antes do OCR:

1. abrir o documento;
2. verificar número de páginas;
3. rejeitar documentos acima do limite;
4. renderizar em DPI compatível com o limite de pixels;
5. controlar tempo total do job;
6. atualizar estado transacionalmente.

## Idempotência

Uma tarefa repetida deve poder detectar um resultado já persistido ou reutilizar
um identificador de fonte sem duplicar dados silenciosamente.

## Falhas

Falha operacional deve preservar:

- identificador da norma;
- etapa que falhou;
- timestamp;
- mensagem sanitizada;
- contador de retries.

Não deve apagar dados anteriores válidos como efeito colateral de uma tentativa
parcial.

## Filas

OCR pesado não deve competir com tarefas rápidas de interação. Em deployments
maiores, use filas dedicadas com concorrência limitada.

## Retenção

PDFs temporários devem ser removidos quando a tarefa terminar, inclusive em
falhas. O cleanup deve ser idempotente e tolerar arquivos já ausentes.
