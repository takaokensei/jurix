"""Measure one anonymous local SSE request using public-law test content."""
import json
import time
from pathlib import Path
import requests

base = "http://127.0.0.1:8005"
session = requests.Session()
session.get(base + "/assistente/", timeout=10).raise_for_status()
question = "Explique as medidas da Lei nº 8204/2026 sobre imóveis abandonados e a regulamentação prevista, indicando os artigos."
t0 = time.perf_counter()
events = []
answer_size = 0
with session.post(base + "/api/v1/search/answer/stream/", json={"question": question, "k": 8}, headers={"X-CSRFToken": session.cookies.get("csrftoken", ""), "Referer": base + "/assistente/"}, stream=True, timeout=(5, 150)) as response:
    response.raise_for_status()
    name = "message"
    for line in response.iter_lines(chunk_size=1, decode_unicode=True):
        if line.startswith("event:"):
            name = line.split(":", 1)[1].strip()
        elif line.startswith("data:"):
            data = json.loads(line.split(":", 1)[1].strip())
            name = data.get("type", name)
            events.append({"event": name, "seconds": round(time.perf_counter() - t0, 3), "keys": sorted(data), "status": data.get("status"), "grounded": data.get("grounded")})
            if name == "done":
                answer_size = len(data.get("answer", ""))
result = {"question": question, "elapsed_seconds": round(time.perf_counter() - t0, 3), "answer_chars": answer_size, "events": events}
summary = {"elapsed_seconds": result["elapsed_seconds"], "answer_chars": answer_size, "chunk_count": sum(item["event"] == "chunk" for item in events), "first_chunk": next((item["seconds"] for item in events if item["event"] == "chunk"), None), "non_chunk_events": [item for item in events if item["event"] != "chunk"]}
print(json.dumps(summary, ensure_ascii=True, indent=2))
Path(__file__).with_name("stream-uncached-results.json").write_text(json.dumps(result, ensure_ascii=True, indent=2), encoding="utf-8")
