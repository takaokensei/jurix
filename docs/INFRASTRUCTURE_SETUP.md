# 🔧 Instruções de Infraestrutura - Ollama Setup

## ⚠️ PROBLEMA IDENTIFICADO

O Chatbot está retornando erro `404 Client Error: Not Found` porque o modelo de embedding `nomic-embed-text` não está instalado no servidor Ollama do host.

## 📋 SOLUÇÃO: Passo a Passo

### Passo 1: Parar os Containers Docker

```bash
docker-compose down
```

### Passo 2: Baixar o Modelo de Embedding

Execute no terminal do **Windows (PowerShell ou CMD)** ou **WSL**:

```bash
ollama pull nomic-embed-text
```

**Tempo estimado:** 2-5 minutos (dependendo da conexão de internet)

**Verificação:**
```bash
ollama list
```

Você deve ver `nomic-embed-text` na lista de modelos instalados.

### Passo 3: Verificar Configuração Ollama

Certifique-se de que o Ollama está exposto à rede:

**Via GUI:**
1. Abra o Ollama (ícone na bandeja do sistema)
2. Vá em **Settings**
3. Ative **"Expose Ollama to the network"**

**Via Terminal (Windows):**
```powershell
$env:OLLAMA_HOST="0.0.0.0"
ollama serve
```

**Via Terminal (WSL/Linux):**
```bash
export OLLAMA_HOST=0.0.0.0
ollama serve
```

### Passo 4: Testar Conectividade

No terminal do Windows:

```bash
curl http://localhost:11434/api/tags
```

Deve retornar JSON com a lista de modelos, incluindo `nomic-embed-text`.

### Passo 5: Reiniciar os Containers

```bash
docker-compose up -d --build
```

### Passo 6: Aguardar Inicialização

Aguarde ~30 segundos para que todos os serviços subam completamente:

```bash
docker-compose logs -f web
```

Pressione `Ctrl+C` quando ver a mensagem de que o servidor está rodando.

### Passo 7: Verificar Health Check

No container Docker:

```bash
docker-compose exec web python manage.py shell -c "from src.llm_engine.ollama_service import OllamaService; s = OllamaService(); print('Ollama Health:', s.check_health())"
```

Deve retornar: `Ollama Health: True`

### Passo 8: Gerar Embeddings (Primeira Execução)

```bash
docker-compose exec web python manage.py bulk_embed --sync --limit 50
```

**Nota:** Este comando pode levar vários minutos, dependendo do número de dispositivos e velocidade do Ollama.

**Comando alternativo (batch processing otimizado):**
```bash
docker-compose exec web python manage.py bulk_embed_batch --batch-size 10 --limit 50
```

## 🔍 Troubleshooting

### Erro: "Connection refused" ao tentar acessar Ollama

**Solução:**
1. Verifique se o Ollama está rodando: `ollama list`
2. Verifique se está exposto à rede (veja Passo 3)
3. Teste localmente: `curl http://localhost:11434/api/version`
4. Se funcionar localmente mas não no Docker, verifique firewall do Windows

### Erro: "404 Not Found" para nomic-embed-text

**Solução:**
1. Verifique se o modelo foi baixado: `ollama list`
2. Se não estiver listado, execute: `ollama pull nomic-embed-text`
3. Aguarde o download completo (pode levar alguns minutos)

### Erro: "Timeout" ao gerar embeddings

**Solução:**
1. Verifique a performance do Ollama: `ollama ps`
2. Se necessário, use um modelo menor ou aumente o timeout
3. Use batch processing para melhor performance

## 📊 Modelos Recomendados

Para o sistema Jurix funcionar completamente, você precisa:

1. **`nomic-embed-text`** (OBRIGATÓRIO) - Para geração de embeddings
   - Tamanho: ~274 MB
   - Uso: Busca semântica, RAG

2. **`llama3`** (OBRIGATÓRIO) - Para geração de texto e RAG Q&A
   - Tamanho: ~4.7 GB
   - Uso: Chatbot, respostas geradas

**Baixar ambos:**
```bash
ollama pull nomic-embed-text
ollama pull llama3
```

## ✅ Validação Final

Execute este comando para validar que tudo está funcionando:

```bash
docker-compose exec web python -c "
from src.llm_engine.ollama_service import OllamaService
from src.processing.rag_service import RAGService

ollama = OllamaService()
rag = RAGService()

print('✅ Ollama Health:', ollama.check_health())
print('✅ Models available:', len(ollama.list_models()))
print('✅ RAG Service initialized')
"
```

**Resultado esperado:**
```
✅ Ollama Health: True
✅ Models available: 2
✅ RAG Service initialized
```

