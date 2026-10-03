"""Audit-only inventory, dependency advisory capture and synthetic follow-up."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid

import requests

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
sys.path.insert(0, str(ROOT))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

def save(name, value):
    (OUT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')

if sys.argv[1] == 'inventory':
    import django
    django.setup()
    from django.urls import get_resolver, URLResolver
    from src.apps.legislation.models import Dispositivo
    routes = []
    def walk(items, prefix=''):
        for item in items:
            path = prefix + str(item.pattern)
            if isinstance(item, URLResolver):
                walk(item.url_patterns, path)
            else:
                routes.append({'route': path, 'name': item.name,
                               'view': item.lookup_str})
    walk(get_resolver().url_patterns)
    residual = [{'norma_id': d.norma_id, 'device_id': d.pk,
                 'identifier': d.get_full_identifier()}
                for d in Dispositivo.objects.select_related('norma', 'dispositivo_pai')
                if any(x in d.texto.lower() for x in ('sala das sessões', 'publicada no diário', 'autoria:'))]
    save('route-inventory.json', routes)
    save('colophon-residuals.json', residual)
    print(json.dumps({'routes': len(routes), 'residuals': residual}, ensure_ascii=False))
elif sys.argv[1] == 'dependencies':
    import importlib.metadata as metadata
    rows = []
    for package in ['requests', 'Pillow', 'PyMuPDF', 'Django']:
        version = metadata.version(package)
        payload = requests.get(f'https://pypi.org/pypi/{package}/{version}/json', timeout=30).json()
        rows.append({'package': package, 'installed': version,
                     'advisories': payload.get('vulnerabilities', [])})
    save('python-advisories.json', rows)
    result = subprocess.run(['npm.cmd', 'audit', '--json'], cwd=ROOT / 'tests/js',
                            capture_output=True, text=True, encoding='utf-8')
    save('npm-advisories.json', json.loads(result.stdout))
    print(json.dumps({'python': [{'package':r['package'], 'version':r['installed'],
                     'advisories':len(r['advisories'])} for r in rows], 'npm_exit':result.returncode}))
elif sys.argv[1] == 'followup':
    client = requests.Session()
    base = 'http://127.0.0.1:8006'
    client.get(base + '/assistente/', timeout=10)
    rows = []
    for label, q, previous in [('exact_article7', 'O que prevê o artigo 7 da Lei nº 8206/2026?', ''),
                               ('context_article7', 'E o artigo 7?', 'O que prevê o art. 1º da Lei nº 8206/2026?')]:
        start = time.perf_counter()
        response = client.post(base + '/api/v1/search/answer/stream/',
            json={'question':q, 'previous_question':previous, 'k':5,
                  'client_session_id':'local-'+str(uuid.uuid4()), 'client_turn_id':str(uuid.uuid4())},
            headers={'X-CSRFToken':client.cookies.get('csrftoken'), 'Referer':base+'/assistente/'},
            timeout=(10,180), stream=True)
        row = {'case':label, 'status':response.status_code, 'events':[]}
        for line in response.iter_lines(chunk_size=1, decode_unicode=True):
            if not line or not line.startswith('data:'):
                continue
            p = json.loads(line[5:])
            row['events'].append({'type':p.get('type'), 'ms':round((time.perf_counter()-start)*1000),
                                  'sources':[s.get('id') for s in p.get('sources',[])]})
            if p.get('type') == 'done':
                row['answer'] = p.get('answer')
                row['contract'] = p.get('contract')
        rows.append(row)
        save('followup-runtime.json', rows)
        print(json.dumps({'case':label,'elapsed_ms':round((time.perf_counter()-start)*1000)},ensure_ascii=False),flush=True)
elif sys.argv[1] == 'metrics':
    from urllib.parse import urlparse
    from collections import defaultdict
    pages = json.loads((OUT / 'browser-metrics.json').read_text(encoding='utf-8'))
    result = {}
    for row in pages:
        assets = []
        for url in dict.fromkeys(row['scripts'] + row['styles']):
            path = urlparse(url).path
            local = ROOT / 'src/apps/core/static' / path.removeprefix('/static/')
            if path.startswith('/static/') and local.is_file():
                assets.append({'path': str(local.relative_to(ROOT)), 'bytes': local.stat().st_size})
        result[row['route']] = {'raw_local_bytes':sum(x['bytes'] for x in assets), 'assets':assets}
    grouped = defaultdict(list)
    for line in (OUT / 'http-events.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if 'queries' in row:
            grouped[row['path']].append(row)
    summary = {path:{'samples':len(rows), 'min_queries':min(r['queries'] for r in rows),
                     'max_queries':max(r['queries'] for r in rows),
                     'min_header_ms':min(r['response_header_ms'] for r in rows),
                     'max_header_ms':max(r['response_header_ms'] for r in rows)}
               for path, rows in grouped.items()}
    save('asset-metrics.json', result)
    save('http-summary.json', summary)
    print(json.dumps({'assets':{k:v['raw_local_bytes'] for k,v in result.items()},'http':summary},ensure_ascii=False))
elif sys.argv[1] == 'context_boundary':
    import django
    django.setup()
    from types import SimpleNamespace
    from src.processing.rag_context_builder import build_relevant_context
    norma = SimpleNamespace(numero='8206', ano=2026, tipo='Lei', ementa='')
    device = SimpleNamespace(norma=norma, tipo='artigo', texto='conteúdo normativo ' * 2000,
                             get_full_identifier=lambda: 'Art. 1º')
    coverage = {'complete':True,'selected_devices':1,'selected_articles':1}
    source = {'dispositivo':device,'coverage':coverage}
    service = SimpleNamespace(semantic_search=lambda *a,**kw:[source])
    context, used = build_relevant_context(service, 'O que prevê a Lei nº 8206/2026?', max_tokens=2000)
    row = {'context_chars':len(context),'full_text_chars':len(device.texto),
           'evidence_chars':len(used[0]['evidence_text']),'coverage':used[0]['coverage'],
           'evidence_scope':used[0]['evidence_scope'],
           'truncated':len(used[0]['evidence_text'])<len(device.texto)}
    save('context-boundary.json',row)
    print(json.dumps(row))
elif sys.argv[1] == 'public_http':
    paths = ['/', '/normas/chatbot/', '/admin/login/', '/colecoes/999999/',
             '/api/v1/health/live/', '/api/v1/health/ready/', '/api/v1/health/',
             '/api/v1/normas/', '/api/v1/normas/3/', '/api/v1/normas/3/timeline/',
             '/api/v1/normas/3/conflicts/', '/api/v1/suggestions/',
             '/api/v1/search/semantic/?query=artigo+1+Lei+8206%2F2026&k=5',
             '/api/v1/chat/sessions/', '/api/v1/chat/sessions/999999/',
             '/api/v1/chat/sessions/slug/audit-missing/', '/api/v1/chat/attachments/']
    rows = []
    for path in paths:
        start = time.perf_counter()
        response = requests.get('http://127.0.0.1:8006' + path, timeout=35)
        rows.append({'path':path.split('?')[0], 'status':response.status_code,
                     'content_type':response.headers.get('Content-Type'),
                     'elapsed_ms':round((time.perf_counter()-start)*1000),
                     'redirected':bool(response.history)})
    save('public-http.json',rows)
    print(json.dumps(rows))
