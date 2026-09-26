from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
for name in ['api_search.py', 'api_normas.py', 'api_chat.py', 'api_attachments.py']:
    p = ROOT / 'src/apps/legislation' / name
    text = p.read_text(encoding='utf-8')
    imp = 'from .api_health import _format_error_message, _server_error\n'
    text = text.replace(imp, '')
    text = text.replace('from src.processing.adaptive_rag_service import AdaptiveRAGService\nRAGService = AdaptiveRAGService\n', 'from src.processing.adaptive_rag_service import AdaptiveRAGService\n' + imp + 'RAGService = AdaptiveRAGService\n')
    p.write_text(text, encoding='utf-8')

p = ROOT / 'src/apps/legislation/api_views.py'
text = p.read_text(encoding='utf-8')
if not text.startswith('# ruff: noqa: F811'):
    p.write_text('# ruff: noqa: F811\n' + text, encoding='utf-8')
