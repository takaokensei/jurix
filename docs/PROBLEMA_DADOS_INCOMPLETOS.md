# ⚠️ PROBLEMA: Dados Incompletos no Pipeline

## 🚨 Situação Atual

- **Total de normas:** 356
- **Normas com PDFs baixados:** 10 (2.8%)
- **Normas com dispositivos criados:** 10
- **Dispositivos indexados:** 264

## 🔍 Causa Raiz

As normas foram marcadas com status `consolidated`, mas:

1. **346 normas não têm PDFs baixados** - O download automático não foi executado ou falhou
2. **Normas sem PDF não têm `texto_original`** - Apenas a ementa (92 chars) está disponível
3. **Sem `texto_original`, não há como criar dispositivos** - O parser precisa do texto completo

## ✅ Solução

### Passo 1: Verificar e Baixar PDFs

```bash
# Verificar quantas normas precisam de download
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma; without_pdf = Norma.objects.filter(pdf_path__isnull=True).exclude(pdf_path='').count(); print(f'Normas sem PDF: {without_pdf}')"

# Forçar download de PDFs pendentes
docker-compose exec web python manage.py download_pdfs --all
```

### Passo 2: Executar Pipeline Completo (na ordem)

```bash
# 1. OCR (só processa normas com PDF)
docker-compose exec web python manage.py bulk_ocr --all --sync

# 2. Segmentação (só processa normas com texto_original)
docker-compose exec web python manage.py bulk_segmentation --all --sync

# 3. NER/Extraction
docker-compose exec web python manage.py bulk_extraction --all --sync

# 4. Consolidação
docker-compose exec web python manage.py bulk_consolidation --all --sync

# 5. Embeddings
docker-compose exec web python manage.py bulk_embed --all --sync
```

### Passo 3: Validar Resultado

```bash
docker-compose exec web python manage.py shell -c "from src.apps.legislation.models import Norma, Dispositivo; normas = Norma.objects.count(); disp = Dispositivo.objects.count(); disp_embed = Dispositivo.objects.filter(embedding__isnull=False).count(); print(f'Normas: {normas}'); print(f'Dispositivos: {disp}'); print(f'Com embeddings: {disp_embed}')"
```

## 📊 Expectativa

Após o processamento completo:
- **Dispositivos esperados:** 5.000-10.000+ (dependendo do tamanho das normas)
- **Cobertura:** Normas com PDFs terão dispositivos indexados
- **RAG funcional:** Chatbot poderá responder sobre todas as normas processadas

## ⚠️ Nota Importante

O sistema só pode processar normas que têm PDFs baixados. Se uma norma não tem PDF disponível na API SAPL, ela não poderá ser processada pelo pipeline.

