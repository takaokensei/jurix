# 🔧 Solução: Completar Processamento de 356 Normas

## 📊 Situação Atual

- **Total de normas:** 356
- **Normas com PDFs:** 10 (2.8%)
- **Normas sem PDFs:** 346 (97.2%)
- **Dispositivos indexados:** 264 (apenas das 10 normas com PDF)

## 🎯 Objetivo

Processar todas as 356 normas através do pipeline completo para ter uma base de conhecimento RAG funcional.

## ✅ Sequência de Comandos OBRIGATÓRIA

### Passo 1: Download de PDFs (CRÍTICO)

```bash
# Baixar PDFs de todas as normas que não têm PDF
docker-compose exec web python manage.py download_pdfs --all --sync
```

**Tempo estimado:** 2-4 horas (dependendo da velocidade de download)

**Monitoramento:**
```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma; with_pdf = Norma.objects.filter(pdf_path__isnull=False).exclude(pdf_path='').count(); total = Norma.objects.count(); print(f'PDFs baixados: {with_pdf}/{total} ({with_pdf/total*100:.1f}%)')"
```

---

### Passo 2: OCR (Extração de Texto)

```bash
docker-compose exec web python manage.py bulk_ocr --all --sync
```

**Tempo estimado:** 1-2 horas

---

### Passo 3: Segmentação

```bash
docker-compose exec web python manage.py bulk_segmentation --all --sync
```

**Tempo estimado:** 15-30 minutos

---

### Passo 4: NER/Extraction

```bash
docker-compose exec web python manage.py bulk_extraction --all --sync
```

**Tempo estimado:** 20-40 minutos

---

### Passo 5: Consolidação

```bash
docker-compose exec web python manage.py bulk_consolidation --all --sync
```

**Tempo estimado:** 30-60 minutos

---

### Passo 6: Embeddings (RAG)

```bash
docker-compose exec web python manage.py bulk_embed --all --sync
```

**Tempo estimado:** 3-6 horas (dependendo da quantidade de dispositivos)

---

## 📊 Validação Final

```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma, Dispositivo; normas = Norma.objects.count(); disp = Dispositivo.objects.count(); disp_embed = Dispositivo.objects.filter(embedding__isnull=False).count(); print(f'✅ Normas: {normas}'); print(f'✅ Dispositivos: {disp}'); print(f'✅ Com embeddings: {disp_embed} ({disp_embed/disp*100:.1f}%)' if disp > 0 else '0%')"
```

**Expectativa:** 5.000-10.000+ dispositivos indexados

---

## ⚠️ IMPORTANTE

1. **Execute na ordem apresentada** - cada etapa depende da anterior
2. **Use `--sync`** para monitorar o progresso em tempo real
3. **Tempo total estimado:** 7-14 horas para processar todas as 356 normas
4. **Recomendação:** Execute em um terminal separado e monitore os logs

---

## 🐛 Correção Aplicada

✅ **Relevância 0% corrigida:** O score agora mostra pelo menos 1 casa decimal para valores < 1%, evitando que scores pequenos apareçam como 0%.

