"""Measure public, synthetic QA queries against the isolated audit web server."""
import json
from pathlib import Path
import time
import uuid
import requests

OUT = Path(__file__).resolve().parent
base = "http://127.0.0.1:8006"
client = requests.Session()
client.get(base + "/assistente/", timeout=10)
token = client.cookies.get("csrftoken")
questions = [
    ("overview", "O que prevê a Lei nº 8.206/2026? Explique seus principais dispositivos."),
    ("article", "O que prevê o art. 1º da Lei nº 8206/2026?"),
    ("missing_norm", "O que prevê a Lei nº 99999/2026?"),
]
results = []
for label, question in questions:
    started = time.perf_counter()
    response = client.post(base + "/api/v1/search/answer/stream/",
        json={"question": question, "k": 5, "client_session_id": "local-" + str(uuid.uuid4()),
              "client_turn_id": str(uuid.uuid4())},
        headers={"X-CSRFToken": token, "Referer": base + "/assistente/"}, stream=True, timeout=(10, 180))
    events = []
    item = {"case": label, "http_status": response.status_code, "events": events}
    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
        if not line or not line.startswith("data:"):
            continue
        payload = json.loads(line[5:].strip())
        event = {"type": payload.get("type"), "ms": round((time.perf_counter()-started)*1000)}
        if 'status' in payload:
            event['status'] = payload['status']
        if 'sources' in payload:
            event['source_count'] = len(payload['sources'])
            event['sources'] = [{key: source.get(key) for key in
                ('citation_id','id','norma_numero','norma_ano','similarity_score','match_kind','retrieval_strategy')}
                for source in payload['sources']]
        for key in ('coverage','retrieval_strategy','cached','grounded'):
            if key in payload:
                event[key] = payload[key]
        if payload.get('type') == 'done':
            item['answer'] = payload.get('answer')
            item['grounding'] = payload.get('grounding')
            contract = payload.get('contract', {})
            item['contract'] = {key: contract.get(key) for key in
                ('timings_ms','generation_attempts','grounding','grounded','retrieval_query','corpus_version')}
        events.append(event)
    item['elapsed_ms'] = round((time.perf_counter()-started)*1000)
    results.append(item)
    (OUT / "rag-runtime.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({"case": label, "elapsed_ms": item['elapsed_ms'], "events": len(events),
                      "grounded": item.get('contract', {}).get('grounded')}), flush=True)
