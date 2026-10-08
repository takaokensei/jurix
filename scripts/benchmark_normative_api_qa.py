#!/usr/bin/env python3
"""Measure the bounded relation API against synthetic rows in isolated QA only."""

from __future__ import annotations

import hashlib
import json
import os
import statistics
import sys
import time
import tracemalloc
from pathlib import Path
from urllib.parse import urlparse
from uuid import uuid4

EVENT_COUNTS = (1, 10, 40, 300, 1000)
WARM_REQUESTS = 20
MAX_RESPONSE_NODES = 40
MAX_RESPONSE_EDGES = 80


def _require_qa() -> None:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise RuntimeError("JURIX_QA_ONLY=1 is required")
    raw_root = os.environ.get("JURIX_QA_ROOT", "")
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "").resolve()
    root = Path(raw_root).resolve()
    if not temp.is_dir() or root == temp or not root.is_relative_to(temp):
        raise RuntimeError("JURIX_QA_ROOT must be isolated below the OS temporary directory")
    database = urlparse(os.environ.get("DATABASE_URL", ""))
    if (
        database.scheme != "postgresql"
        or database.hostname != "127.0.0.1"
        or database.port != 55432
        or database.username != "jurix_audit"
        or database.path != "/jurix_audit"
    ):
        raise RuntimeError("benchmark refuses a database outside the dedicated QA service")
    if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa":
        raise RuntimeError("isolated normative QA settings are required")


def run() -> dict:
    _require_qa()
    project_root = Path(__file__).resolve().parents[1]
    source_root = project_root / "src"
    for import_root in (source_root, project_root):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))
    import django

    django.setup()

    from django.conf import settings
    from django.contrib.auth import get_user_model
    from django.contrib.auth.models import Permission
    from django.core.cache import cache
    from django.db import connection, transaction
    from django.test import Client
    from django.test.utils import CaptureQueriesContext
    from django.utils import timezone

    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
    from src.apps.operations.models import CorpusRevision
    from src.processing.cache_service import CacheService

    expected_cache = "redis://127.0.0.1:16380/1"
    if settings.CACHES["default"].get("LOCATION") != expected_cache:
        raise RuntimeError("benchmark refuses a cache outside the dedicated QA Redis DB")

    run_id = uuid4().hex
    fixture_marker = f"Fixture sintética temporária de benchmark QA:{run_id}"
    today = timezone.localdate()
    cache_keys: list[str] = []
    corpus_before = None
    benchmark_username = f"graph-bench-{run_id}"
    report: dict = {
        "mode": "isolated_qa_django_test_client",
        "synthetic_only": True,
        "request_transport": "in_process_django_test_client_not_tcp_http",
        "event_counts": list(EVENT_COUNTS),
        "warm_requests_per_size": WARM_REQUESTS,
        "endpoint_limits": {"nodes": MAX_RESPONSE_NODES, "edges": MAX_RESPONSE_EDGES},
    }
    # Recover QA-only artifacts from an interrupted earlier invocation. The
    # marker and username prefix are exclusive to this benchmark.
    stale_normas = Norma.objects.filter(ementa__startswith="Fixture sintética temporária de benchmark QA:")
    stale_norma_count = stale_normas.count()
    user_model = get_user_model()
    stale_users = user_model.objects.filter(username__startswith="graph-bench-")
    stale_user_count = stale_users.count()
    if stale_norma_count or stale_user_count:
        with transaction.atomic():
            stale_normas.delete()
            stale_users.delete()
    report["prior_interrupted_fixture_cleanup"] = {
        "norms_removed": stale_norma_count,
        "users_removed": stale_user_count,
        "scope": "exact synthetic benchmark marker in isolated QA DB",
    }
    try:
        with transaction.atomic():
            preexisting_corpus = CorpusRevision.objects.filter(key="municipal").first()
            corpus_fields = (
                "revision", "digest", "norm_count", "device_count", "active_event_count",
                "schema_version", "segmentation_version", "completeness", "generated_at", "updated_at",
            )
            corpus_before = (
                {field: getattr(preexisting_corpus, field) for field in corpus_fields}
                if preexisting_corpus else None
            )
            report["corpus_revision_before_benchmark"] = {
                "present": preexisting_corpus is not None,
                "revision": preexisting_corpus.revision if preexisting_corpus else None,
                "digest_present": bool(preexisting_corpus and preexisting_corpus.digest),
                "updated_at": preexisting_corpus.updated_at.isoformat() if preexisting_corpus else None,
                "norm_count": preexisting_corpus.norm_count if preexisting_corpus else None,
                "device_count": preexisting_corpus.device_count if preexisting_corpus else None,
            }
            corpus, _created = CorpusRevision.objects.get_or_create(
                key="municipal",
                defaults={"revision": 1, "digest": hashlib.sha256(uuid4().bytes).hexdigest()},
            )
            if not corpus.digest:
                corpus.revision += 1
                corpus.digest = hashlib.sha256(uuid4().bytes).hexdigest()
                corpus.save(update_fields=("revision", "digest", "updated_at"))

            User = get_user_model()
            user = User.objects.create_user(
                username=benchmark_username, is_staff=True, is_active=True
            )
            permission = Permission.objects.get(
                content_type__app_label="legislation", codename="view_eventoalteracao"
            )
            user.user_permissions.add(permission)
            client = Client()
            client.force_login(user)
            query = f"?depth=1&as_of={today.isoformat()}&include_pending=true"
            principal = f"staff:{user.pk}"
            from src.apps.legislation import relations_api

            original_builder = relations_api.build_normative_graph
            results = []
            for event_count in EVENT_COUNTS:
                norma = Norma.objects.create(
                    tipo="Lei", numero=f"{uuid4().int % 90_000_000 + 10_000_000}",
                    ano=2098, ementa=fixture_marker,
                )
                device = Dispositivo.objects.create(
                    norma=norma, tipo="artigo", numero="1º",
                    texto="Dispositivo sintético para teste de limites do grafo.", ordem=1,
                )
                EventoAlteracao.objects.bulk_create([
                    EventoAlteracao(
                        dispositivo_fonte=device,
                        acao="REFERENCIA",
                        target_text=f"Referência sintética de benchmark {event_count}:{index}",
                        target_reference_json={"external_identity_key": f"qa-benchmark:{index % 39}"},
                        revision_fingerprint=uuid4().hex + uuid4().hex,
                    )
                    for index in range(event_count)
                ])
                corpus_digest = CacheService.get_corpus_revision_digest()
                if corpus_digest == "unavailable":
                    raise RuntimeError("durable QA corpus digest unavailable; cannot measure cache")
                route = f"/api/v1/normas/{norma.pk}/relations/{query}"
                cache_payload = {
                    "norma": norma.pk,
                    "depth": 1,
                    "as_of": today.isoformat(),
                    "actions": (),
                    "include_pending": True,
                    "principal": principal,
                    "policy": "normative-graph-v2",
                    "corpus": corpus_digest,
                }
                cache_key = "jurix:normative-graph:" + hashlib.sha256(
                    json.dumps(cache_payload, sort_keys=True).encode()
                ).hexdigest()
                cache_keys.append(cache_key)
                cache.delete(cache_key)

                cold_started = time.perf_counter()
                with CaptureQueriesContext(connection) as cold_queries:
                    cold = client.get(route)
                cold_ms = (time.perf_counter() - cold_started) * 1000
                cold_body = cold.json()
                if cold.status_code != 200:
                    raise RuntimeError(f"cold API request for {event_count} events returned HTTP {cold.status_code}")
                returned_edges = len(cold_body.get("edges", []))
                expected_edges = min(event_count, MAX_RESPONSE_EDGES)
                if returned_edges != expected_edges:
                    raise RuntimeError(f"expected {expected_edges} returned edges, received {returned_edges}")
                if len(cold_body.get("nodes", [])) > MAX_RESPONSE_NODES:
                    raise RuntimeError("API exceeded its node response bound")
                if returned_edges > MAX_RESPONSE_EDGES:
                    raise RuntimeError("API exceeded its edge response bound")
                if bool(cold_body.get("truncated")) != (event_count > MAX_RESPONSE_EDGES):
                    raise RuntimeError("API truncation flag did not match the synthetic input size")
                if cache.get(cache_key) is None:
                    raise RuntimeError(f"cold API request for {event_count} events missed QA cache population")

                build_calls = 0

                def count_builds(*args, **kwargs):
                    nonlocal build_calls
                    build_calls += 1
                    return original_builder(*args, **kwargs)

                samples: list[float] = []
                query_counts: list[int] = []
                tracemalloc.start()
                with __import__("unittest.mock", fromlist=["patch"]).patch.object(
                    relations_api, "build_normative_graph", side_effect=count_builds
                ):
                    for _ in range(WARM_REQUESTS):
                        started = time.perf_counter()
                        with CaptureQueriesContext(connection) as request_queries:
                            response = client.get(route)
                        samples.append((time.perf_counter() - started) * 1000)
                        query_counts.append(len(request_queries))
                        if response.status_code != 200 or response.json() != cold_body:
                            raise RuntimeError(f"warm response diverged for {event_count} input events")
                _, peak_bytes = tracemalloc.get_traced_memory()
                tracemalloc.stop()
                cache_hits = WARM_REQUESTS - build_calls
                if cache_hits != WARM_REQUESTS:
                    raise RuntimeError(f"only {cache_hits}/{WARM_REQUESTS} warmed requests used the graph cache")

                warm_p50 = statistics.median(samples)
                results.append({
                    "synthetic_event_rows": event_count,
                    "database_queries_cold_request": len(cold_queries),
                    "cold_latency_ms": round(cold_ms, 3),
                    "database_queries_warm_p50": statistics.median(query_counts),
                    "database_queries_warm_max": max(query_counts),
                    "warm_request_samples": len(samples),
                    "verified_cache_hits": cache_hits,
                    "cache_misses_during_warm_samples": build_calls,
                    "nodes_returned": len(cold_body["nodes"]),
                    "edges_returned": returned_edges,
                    "graph_truncated": cold_body["truncated"],
                    "warm_latency_p50_ms": round(warm_p50, 3),
                    "warm_latency_p95_ms": round(sorted(samples)[int((len(samples) - 1) * 0.95)], 3),
                    "warm_latency_min_ms": round(min(samples), 3),
                    "warm_latency_max_ms": round(max(samples), 3),
                    "peak_traced_bytes_during_warm_requests": peak_bytes,
                    "p50_target_ms": 300 if returned_edges == MAX_RESPONSE_EDGES else None,
                    "p50_target_met": warm_p50 < 300 if returned_edges == MAX_RESPONSE_EDGES else None,
                })
            report.update({
                "database_backend": connection.vendor,
                "results": results,
                "status": "measured_qa_target_met" if all(
                    row["p50_target_met"]
                    for row in results if row["p50_target_met"] is not None
                ) else "target_not_met_on_this_hardware",
                "notes": [
                    "Synthetic rows for 1/10/40/300/1000 input events are created inside transaction.atomic() and rolled back.",
                    "The API response remains capped at 40 nodes/80 edges; larger inputs must report truncation.",
                    "Latency is Django test-client/in-process, not loopback HTTP or production load.",
                    "Memory is Python tracemalloc peak for warm requests, not process RSS.",
                ],
            })
            transaction.set_rollback(True)
        for cache_key in cache_keys:
            cache.delete(cache_key)
        if Norma.objects.filter(ementa=fixture_marker).exists():
            raise RuntimeError("synthetic benchmark norm remained after transaction rollback")
        if user_model.objects.filter(username=benchmark_username).exists():
            raise RuntimeError("synthetic benchmark user remained after transaction rollback")
        corpus_after = CorpusRevision.objects.filter(key="municipal").first()
        if corpus_before is None:
            if corpus_after is not None:
                raise RuntimeError("synthetic corpus revision remained after transaction rollback")
        elif corpus_after is None or any(
            getattr(corpus_after, field) != value for field, value in corpus_before.items()
        ):
            raise RuntimeError("pre-existing corpus revision changed during benchmark")
        if any(cache.get(cache_key) is not None for cache_key in cache_keys):
            raise RuntimeError("synthetic benchmark cache keys remained after cleanup")
        report["fixture_rollback_verified"] = True
        report["temporary_user_rollback_verified"] = True
        report["corpus_revision_unchanged_verified"] = True
        report["cache_key_cleanup_verified"] = True
    finally:
        for cache_key in cache_keys:
            cache.delete(cache_key)
        if tracemalloc.is_tracing():
            tracemalloc.stop()

    return report


if __name__ == "__main__":
    try:
        result = run()
    except Exception as exc:
        print(json.dumps({"status": "benchmark_failed", "error_type": type(exc).__name__, "message": str(exc)}, indent=2), file=sys.stderr)
        raise SystemExit(1) from None
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result.get("status") == "measured_qa_target_met" else 1)
