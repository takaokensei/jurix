from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]

# Keep compatibility/generated modules intentionally broad, but do not leave imports
# after executable statements or unresolved cross-module helper references.
for name in [
    'consolidation_tasks.py', 'core_tasks.py', 'download_tasks.py',
    'ner_tasks.py', 'ocr_tasks.py', 'segmentation_tasks.py',
]:
    p = ROOT / 'src/apps/ingestion' / name
    if not p.exists(): continue
    text = p.read_text(encoding='utf-8')
    marker = 'logger = logging.getLogger(__name__)\n'
    if name == 'core_tasks.py':
        extras = 'from .download_tasks import download_pdf_task\nfrom .task_support import _invalidate_rag_cache, _normalize_norma_tipo\n'
        text = text.replace('from .download_tasks import download_pdf_task\n', '').replace('from .task_support import _invalidate_rag_cache, _normalize_norma_tipo\n', '')
    elif name == 'download_tasks.py':
        extras = 'from .task_support import _invalidate_rag_cache, _mark_norma_failed\n'
        text = text.replace('from .task_support import _mark_norma_failed\n', '').replace('from .task_support import _invalidate_rag_cache\n', '')
    elif name == 'ner_tasks.py':
        extras = 'from .task_support import _invalidate_rag_cache, _mark_norma_failed, _resolve_norma_reference\n'
        text = text.replace(extras, '')
    elif name == 'ocr_tasks.py':
        extras = 'from .task_support import _configure_tesseract, _mark_norma_failed\n'
        text = text.replace(extras, '')
    else:
        extras = 'from .task_support import _invalidate_rag_cache, _mark_norma_failed\n'
        text = text.replace(extras, '')
    if marker in text:
        text = text.replace(marker, extras + marker, 1)
    text = text.replace('# ruff: noqa: F401,F403,E501,E701', '# ruff: noqa: F401,F403,E501,E701,I001')
    p.write_text(text, encoding='utf-8')

for name in ['api_search.py', 'api_normas.py', 'api_chat.py', 'api_attachments.py']:
    p = ROOT / 'src/apps/legislation' / name
    if not p.exists(): continue
    text = p.read_text(encoding='utf-8')
    imp = 'from .api_health import _format_error_message, _server_error\n'
    if imp not in text:
        text = text.replace('RAGService = AdaptiveRAGService\n', 'RAGService = AdaptiveRAGService\n' + imp, 1)
    text = text.replace('# ruff: noqa: F401,F403,E501,E701', '# ruff: noqa: F401,F403,E501,E701,I001')
    p.write_text(text, encoding='utf-8')

p = ROOT / 'src/apps/legislation/api_health.py'
if p.exists():
    text = p.read_text(encoding='utf-8').replace('# ruff: noqa: F401,F403,E501,E701', '# ruff: noqa: F401,F403,E501,E701,I001')
    p.write_text(text, encoding='utf-8')
