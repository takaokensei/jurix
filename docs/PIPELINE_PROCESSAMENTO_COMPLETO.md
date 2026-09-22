# 🚀 Pipeline de Processamento Completo - 360 Normas

## 📋 COMANDOS OBRIGATÓRIOS

Execute a sequência abaixo **na ordem apresentada** para processar todas as 360 normas através do pipeline completo de PLN:

### 1️⃣ OCR (Extração de Texto dos PDFs)

```bash
docker-compose exec web python manage.py bulk_ocr --all --sync
```

**O que faz:**
- Processa todos os PDFs baixados com Tesseract OCR
- Extrai texto estruturado e armazena em `texto_original`
- Atualiza status das normas para `ocr_completed`

**Tempo estimado:** 30-60 minutos (dependendo do número de páginas)

---

### 2️⃣ Segmentação (Estrutura Hierárquica de Dispositivos)

```bash
docker-compose exec web python manage.py bulk_segmentation --all --sync
```

**O que faz:**
- Segmenta o texto em dispositivos hierárquicos (Artigos, Parágrafos, Incisos, Alíneas)
- Cria instâncias de `Dispositivo` com relações pai-filho
- Atualiza status das normas para `segmented`

**Tempo estimado:** 5-15 minutos

---

### 3️⃣ NER/Extraction (Identificação de Eventos de Alteração)

```bash
docker-compose exec web python manage.py bulk_extraction --all --sync
```

**O que faz:**
- Identifica eventos de alteração (ADICIONA, REVOGA, ALTERA, REFERENCIA)
- Cria instâncias de `EventoAlteracao` vinculadas aos dispositivos
- Atualiza status das normas para `extracted`

**Tempo estimado:** 10-20 minutos

---

### 4️⃣ Consolidação (Aplicação de Alterações)

```bash
docker-compose exec web python manage.py bulk_consolidation --all --sync
```

**O que faz:**
- Aplica os eventos de alteração identificados
- Gera texto consolidado para cada norma
- Atualiza status das normas para `consolidated`

**Tempo estimado:** 15-30 minutos

---

### 5️⃣ Embeddings (Indexação pgvector para RAG)

```bash
docker-compose exec web python manage.py bulk_embed --all --batch-size 16
```

**O que faz:**
- Gera embeddings vetoriais (768d) em lotes usando o endpoint `/api/embed` do Ollama
- Indexa no pgvector para busca semântica
- Habilita o RAG (Retrieval-Augmented Generation)

**Tempo estimado:** 60-120 minutos (dependendo da quantidade de dispositivos)

---

## 📊 Monitoramento do Progresso

### Verificar status das normas:

```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma; from django.db.models import Count; status_counts = Norma.objects.values('status').annotate(count=Count('id')).order_by('status'); print('Status das normas:'); [print(f'  {s[\"status\"]}: {s[\"count\"]}') for s in status_counts]"
```

### Verificar total de dispositivos criados:

```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Dispositivo; total = Dispositivo.objects.count(); with_embed = Dispositivo.objects.filter(embedding__isnull=False).count(); print(f'Total dispositivos: {total}'); print(f'Com embeddings: {with_embed} ({with_embed/total*100:.1f}%)' if total > 0 else '0%')"
```

### Verificar logs em tempo real:

```bash
docker-compose logs -f web
```

---

## ⚠️ IMPORTANTE

- **Execute os comandos na ordem apresentada** - cada etapa depende da anterior
- **Use `--sync`** para processamento síncrono (mais lento, mas permite monitoramento)
- **Tempo total estimado:** 2-4 horas para processar 360 normas completamente
- **Recomendação:** Execute em um terminal separado e monitore o progresso

---

## ✅ Validação Final

Após concluir todos os passos, valide que o RAG está funcionando:

```bash
curl "http://localhost:8000/api/v1/search/answer/?question=Como+funciona+o+zoneamento+urbano+em+Natal"
```

Deve retornar uma resposta com fontes relevantes e scores de similaridade normalizados (0-100%).

