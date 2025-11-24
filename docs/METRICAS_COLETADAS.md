# 📊 Métricas Coletadas - Sistema Jurix

## 📈 Métricas Gerais do Sistema

### Dados Processados
- **Total de Normas:** 356
- **Normas Consolidadas:** 356 (100%)
- **Normas com PDFs:** 356 (100%)
- **Período Coberto:** 1990-2025
- **Total de Dispositivos:** 4.916
- **Dispositivos com Embeddings:** 4.916 (100%)

### Pipeline de Processamento

#### 1. Ingestão (API SAPL)
- **Taxa de Sucesso:** 100% (356/356 normas)
- **Método:** Filtro por intervalo de anos (1990-2025)
- **Tempo Total de Download:** ~9 minutos (346 PDFs novos)

#### 2. Download de PDFs
- **PDFs Baixados:** 346 (em uma única execução)
- **Taxa de Sucesso:** 100% (0 falhas)
- **Tempo Médio por PDF:** ~1.5s

#### 3. OCR (Extração de Texto)
- **Normas Processadas:** 356
- **Taxa de Sucesso:** 100%
- **Tempo Médio:** ~2-5s por PDF (depende do número de páginas)

#### 4. Segmentação
- **Dispositivos Criados:** 4.916
- **Estrutura Hierárquica:** Artigos → Parágrafos → Incisos → Alíneas → Itens
- **Taxa de Sucesso:** 100% (todas as normas segmentadas)

#### 5. NER/Extraction
- **Eventos de Alteração:** [A ser contabilizado]
- **Referências Cruzadas:** [A ser contabilizado]

#### 6. Consolidação
- **Normas Consolidadas:** 356 (100%)
- **Status:** Todas as normas marcadas como `consolidated`

#### 7. Embeddings (RAG)
- **Dispositivos Indexados:** 4.916 (100%)
- **Dimensão dos Embeddings:** 768 (modelo nomic-embed-text)
- **Tempo de Geração:** ~0.04-0.10s por dispositivo
- **Tempo Total:** ~4-5 minutos para 4.652 dispositivos novos

### Performance de Busca Semântica

- **Latência Média (com cache):** ~50-200ms
- **Latência Média (sem cache):** ~500-1000ms (estimado)
- **Speedup com Cache:** 50-90% de redução
- **Top-K por Query:** 5 dispositivos (configurável)

### Qualidade do Sistema

#### Chatbot RAG
- **Modelo LLM:** llama3 (via Ollama)
- **Modelo de Embedding:** nomic-embed-text (768d)
- **Tempo de Resposta:** ~2-5s por query
- **Fontes Consultadas:** 5 por resposta (Top-K=5)

#### Testes Automatizados
- **Total de Testes:** 14 testes
- **Cobertura:** RAG Service, normalização de scores
- **Status:** Todos passando

### Infraestrutura

- **Stack:** Django 5.0, PostgreSQL 16 + pgvector, Redis, Celery
- **IA/NLP:** Ollama (local), Tesseract OCR
- **Deployment:** Docker Compose
- **CI/CD:** GitHub Actions configurado

---

## 📝 Notas

- Métricas marcadas como "[A ser contabilizado]" requerem queries específicas no banco de dados
- Tempos de processamento podem variar dependendo do hardware e carga do sistema
- Métricas de qualidade (precisão, recall) requerem validação manual com amostra estatística

