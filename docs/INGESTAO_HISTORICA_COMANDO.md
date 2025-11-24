# ⚠️ COMANDO OBRIGATÓRIO: Ingestão Histórica de Normas

## 🚨 PROBLEMA CRÍTICO IDENTIFICADO

O sistema RAG está **falhando em responder consultas reais** porque a base de conhecimento atual contém apenas **10 normas recentes** da API SAPL. 

**Sintomas:**
- Chatbot não consegue responder sobre "zoneamento urbano"
- Chatbot não encontra informações sobre IPTU, licenças de construção, etc.
- Apenas perguntas sobre as 10 normas mais recentes funcionam

**Causa Raiz:**
A API SAPL retorna apenas as 10 normas mais recentes por padrão, ignorando paginação. A solução implementada (filtro por ano) permite buscar o histórico completo.

## 📋 SOLUÇÃO: Ingestão Histórica Completa

Execute o seguinte comando para ingerir **TODAS as normas desde 2000 até 2025**:

```bash
docker-compose exec web python manage.py ingest_sapl --ano-inicio 2000 --ano-fim 2025 --auto-download
```

### ⏱️ Tempo Estimado
- **Ingestão de metadados:** 5-15 minutos (depende do número de normas)
- **Download de PDFs:** Variável (pode levar horas dependendo da quantidade)
- **Recomendação:** Execute em modo assíncrono para não travar o terminal

### 🔍 Monitoramento

**Verificar progresso da ingestão:**
```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma; print(f'Total de normas no banco: {Norma.objects.count()}')"
```

**Verificar status dos downloads:**
```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma; downloaded = Norma.objects.filter(pdf_path__isnull=False).exclude(pdf_path='').count(); total = Norma.objects.count(); print(f'PDFs baixados: {downloaded}/{total} ({downloaded/total*100:.1f}%' if total > 0 else '0%')"
```

### ⚡ Modo Assíncrono (Recomendado)

Se preferir executar em background via Celery:

```bash
docker-compose exec web python manage.py ingest_sapl --ano-inicio 2000 --ano-fim 2025 --auto-download --async
```

**Verificar tasks do Celery:**
```bash
docker-compose logs -f worker
```

## 📊 Após a Ingestão

Após concluir a ingestão histórica, você precisará executar:

1. **Processar PDFs (OCR):**
   ```bash
   docker-compose exec web python manage.py bulk_ocr --limit 1000
   ```

2. **Segmentar textos:**
   ```bash
   docker-compose exec web python manage.py bulk_segmentation --limit 1000
   ```

3. **Gerar embeddings:**
   ```bash
   docker-compose exec web python manage.py bulk_embed --limit 10000
   ```

4. **Validar RAG:**
   Teste no chatbot: "Como funciona o zoneamento urbano em Natal?"

## ✅ Validação Final

Quando a ingestão estiver completa, valide que o RAG funciona:

```bash
curl "http://localhost:8000/api/v1/search/answer/?question=Como+funciona+o+zoneamento+urbano+em+Natal"
```

Deve retornar uma resposta com fontes relevantes, não mais "não encontrei informações".

