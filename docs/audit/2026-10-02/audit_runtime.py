"""Audit-only request/event telemetry; never records credentials, prompts or SQL."""
import json
from pathlib import Path
import time
from django.db import connection

OUT = Path(__file__).resolve().parent / "http-events.jsonl"

def record(payload):
    with OUT.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(payload, default=str) + "\n")

class AuditTelemetryMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        started = time.perf_counter()
        before = len(connection.queries)
        response = self.get_response(request)
        record({"path": request.path, "method": request.method, "status": response.status_code,
                "response_header_ms": round((time.perf_counter()-started)*1000),
                "queries": len(connection.queries)-before,
                "query_ms": round(sum(float(q['time']) for q in connection.queries[before:])*1000)})
        if response.streaming and "text/event-stream" in response.get("Content-Type", ""):
            original = response.streaming_content
            def measured():
                for frame in original:
                    text = frame.decode("utf-8") if isinstance(frame, bytes) else frame
                    item = {"path": request.path, "elapsed_ms": round((time.perf_counter()-started)*1000)}
                    for line in text.splitlines():
                        if line.startswith("event:"):
                            item['event'] = line.partition(':')[2].strip()
                        if line.startswith("data:"):
                            try:
                                data = json.loads(line.partition(':')[2].strip())
                                for key in ('status','grounded','cached','coverage','retrieval_strategy','timings_ms','generation_attempts','grounding'):
                                    if key in data:
                                        item[key] = data[key]
                                if 'chunk' in data:
                                    item['chunk_chars'] = len(data['chunk'])
                                if 'sources' in data:
                                    item['source_count'] = len(data['sources'])
                            except (ValueError, TypeError):
                                pass
                    if 'event' in item:
                        record(item)
                    yield frame
            response.streaming_content = measured()
        return response
