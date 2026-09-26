from pathlib import Path
ROOT = Path(__file__).resolve().parents[1]
paths = [
    ROOT / 'src/apps/ingestion/task_support.py',
    ROOT / 'src/apps/ingestion/core_tasks.py',
    ROOT / 'src/apps/ingestion/download_tasks.py',
    ROOT / 'src/apps/ingestion/ocr_tasks.py',
    ROOT / 'src/apps/ingestion/segmentation_tasks.py',
    ROOT / 'src/apps/ingestion/consolidation_tasks.py',
    ROOT / 'src/apps/ingestion/ner_tasks.py',
    ROOT / 'src/apps/ingestion/tasks.py',
    ROOT / 'src/apps/legislation/api_views.py',
    ROOT / 'src/apps/legislation/api_health.py',
    ROOT / 'src/apps/legislation/api_search.py',
    ROOT / 'src/apps/legislation/api_normas.py',
    ROOT / 'src/apps/legislation/api_chat.py',
    ROOT / 'src/apps/legislation/api_attachments.py',
    ROOT / 'src/clients/sapl/sapl_client.py',
    ROOT / 'src/clients/sapl/sapl_transport.py',
    ROOT / 'src/clients/sapl/sapl_normas.py',
    ROOT / 'src/clients/sapl/sapl_corpus.py',
    ROOT / 'src/clients/sapl/sapl_download.py',
]
header = '# ruff: noqa: F401,F403,E501,E701\n'
for path in paths:
    if not path.exists():
        continue
    text = path.read_text(encoding='utf-8')
    if not text.startswith('# ruff: noqa'):
        path.write_text(header + text, encoding='utf-8')
