#!/usr/bin/env python3
"""Collect paired RAG technical-smoke predictions in the isolated QA stack."""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import sys
import time
import uuid
from datetime import date
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import urlopen

ARMS = ("baseline", "graph", "graph_temporal")
MAX_CASES = 12
TOKEN_BUDGET = 2048
_CITATION_MARKER = re.compile(r"\[\[(\d{1,3})\]\]")
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def validate_cases(rows: list[dict], *, max_cases: int = MAX_CASES) -> list[dict]:
    if not rows or len(rows) > max_cases or len(rows) > MAX_CASES:
        raise ValueError(f"case count must be between 1 and {min(max_cases, MAX_CASES)}")
    seen = set()
    validated = []
    for index, row in enumerate(rows, 1):
        if not isinstance(row, dict) or not isinstance(row.get("case_id"), str):
            raise ValueError(f"case {index}: case_id is required")
        if not row["case_id"].strip() or row["case_id"] in seen:
            raise ValueError(f"case {index}: case_id must be nonempty and unique")
        seen.add(row["case_id"])
        if not isinstance(row.get("query"), str) or not row["query"].strip():
            raise ValueError(f"case {row['case_id']}: query is required")
        if row.get("human_evidence_review") is True:
            raise ValueError("technical collector refuses to mark cases as human-reviewed")
        if row.get("synthetic_qa_fixture") is not True:
            raise ValueError("technical collector requires explicitly synthetic QA fixtures")
        as_of = row.get("as_of")
        if as_of is not None:
            try:
                date.fromisoformat(as_of)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"case {row['case_id']}: as_of must be an ISO date") from exc
        validated.append({
            **row,
            "expected_source_ids": row.get("expected_source_ids", []),
            "expected_citation_ids": row.get("expected_citation_ids", []),
            "expected_versions": row.get("expected_versions", {}),
            "expected_abstain": row.get("expected_abstain", False),
            "relation_chain_keys": row.get("relation_chain_keys", []),
            "human_evidence_review": False,
        })
    return validated


def _read_cases(path: Path, *, max_cases: int) -> list[dict]:
    if not 1 <= max_cases <= MAX_CASES:
        raise ValueError(f"max-cases must be between 1 and {MAX_CASES}")
    rows = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise ValueError(f"{path.name}:{line_number}: invalid JSON") from exc
    if not rows:
        raise ValueError("case file is empty")
    return validate_cases(rows[:max_cases], max_cases=max_cases)


def _ensure_qa_runtime() -> tuple[object, str, str]:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise RuntimeError("collector requires JURIX_QA_ONLY=1")
    root = Path(os.environ.get("JURIX_QA_ROOT", "")).resolve()
    temp = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "").resolve()
    if not temp.is_dir() or not root.is_relative_to(temp) or root == temp:
        raise RuntimeError("collector QA root must be an isolated child of the system temp directory")

    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_normative_qa")
    import django

    django.setup()
    from django.conf import settings

    if os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa":
        raise RuntimeError("collector refuses non-QA Django settings")
    database = settings.DATABASES["default"]
    if (
        database.get("ENGINE") != "django.db.backends.postgresql"
        or database.get("HOST") != "127.0.0.1"
        or str(database.get("PORT")) != "55432"
        or database.get("NAME") != "jurix_audit"
    ):
        raise RuntimeError("collector refuses a database outside the dedicated QA fixture")
    cache_url = urlparse(settings.CACHES["default"].get("LOCATION", ""))
    if cache_url.hostname != "127.0.0.1" or cache_url.port != 16380:
        raise RuntimeError("collector refuses a cache outside the dedicated QA fixture")
    ollama_url = urlparse(settings.OLLAMA_BASE_URL)
    if ollama_url.hostname not in {"127.0.0.1", "localhost"} or ollama_url.port != 11434:
        raise RuntimeError("collector only supports the local Ollama instance")
    model = str(settings.OLLAMA_MODEL)
    with urlopen(f"{settings.OLLAMA_BASE_URL.rstrip('/')}/api/tags", timeout=8) as response:
        if response.status != 200:
            raise RuntimeError("local Ollama model inventory is unavailable")
        inventory = json.loads(response.read(2 * 1024 * 1024))
    available = {str(item.get("name", "")) for item in inventory.get("models", [])}
    if model not in available and f"{model}:latest" not in available:
        raise RuntimeError("configured QA model is not present in the local Ollama inventory")
    return settings, model, str(root)


def _make_options(base_options, namespace: str):
    from dataclasses import fields

    base_type = type(base_options)

    def fingerprint(self):
        return f"{super(experiment_type, self).fingerprint()};experiment={self._experiment_namespace}"

    experiment_type = type(
        "ExperimentRetrievalOptions",
        (base_type,),
        {"fingerprint": fingerprint, "__module__": __name__},
    )
    instance = object.__new__(experiment_type)
    for item in fields(base_options):
        object.__setattr__(instance, item.name, getattr(base_options, item.name))
    object.__setattr__(instance, "_experiment_namespace", namespace)
    return instance


def _cache_kwargs(cache_service, *, question, k, model, temperature, options, endpoint):
    from src.processing.cache_service import CacheService

    corpus_version = cache_service.get_corpus_version()
    corpus_revision = cache_service.get_corpus_revision_digest()
    generation_fingerprint = CacheService.generation_fingerprint(
        provider="ollama",
        model=model,
        endpoint=endpoint,
        temperature=temperature,
        max_tokens=TOKEN_BUDGET,
    )
    return {
        "question": question,
        "k": k,
        "model": model,
        "corpus_version": corpus_version,
        "retrieval_fingerprint": options.fingerprint(),
        "corpus_revision": corpus_revision,
        "generation_fingerprint": generation_fingerprint,
    }


def _delete_answer_cache(cache_service, kwargs: dict) -> None:
    from django.core.cache import cache

    question = kwargs["question"]
    cache_input = (
        f"{cache_service._corpus_token(kwargs['corpus_revision'])}:v{kwargs['corpus_version']}:{question}"
        f":k={kwargs['k']}:model={kwargs['model']}:retrieval={kwargs['retrieval_fingerprint']}"
        f":generation={kwargs['generation_fingerprint']}"
    )
    cache.delete(cache_service._generate_key(cache_service.ANSWER_PREFIX, cache_input))


def _delete_query_embedding_cache(cache_service, *, question: str, embedding_model: str) -> None:
    from django.core.cache import cache

    key = cache_service._generate_key(
        cache_service.EMBEDDING_PREFIX,
        f"{embedding_model}:{question.strip()}",
    )
    cache.delete(key)


def _probe_warm_cache(cache_service, *, kwargs_by_arm, question, embedding_model):
    """Return sanitized, arm-specific eligibility for a verified warm-cache repeat."""
    answer_hits = {
        arm: cache_service.get_answer(**kwargs) is not None
        for arm, kwargs in kwargs_by_arm.items()
    }
    embedding_cached = cache_service.get_embedding(question.strip(), embedding_model) is not None
    return {
        "answer_cache_hits_by_arm": answer_hits,
        "query_embedding_cached": embedding_cached,
        "eligible_arms": [arm for arm, hit in answer_hits.items() if hit],
        "fully_paired": all(answer_hits.values()),
    }


def _warm_cache_bypass_reason(case: dict) -> str | None:
    """Mirror the production retrieval cache policy before scheduling warm repeats."""
    if case.get("as_of"):
        return "temporal_retrieval_bypasses_answer_cache"
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    if AdaptiveRAGService._has_unambiguous_versioned_reference(case.get("query", "")):
        return "explicit_normative_reference_bypasses_answer_cache"
    return None


def _source_ids_and_versions(raw_sources: list[dict]) -> tuple[list[str], list[dict]]:
    from src.apps.legislation.serializers import serialize_dispositivo_source

    serialized = [serialize_dispositivo_source(source) for source in raw_sources]
    ids = []
    seen = set()
    for item in serialized:
        source_id = item.get("citation_id") or item.get("source_id")
        if source_id is not None and str(source_id) not in seen:
            seen.add(str(source_id))
            ids.append(str(source_id))
    return ids, serialized


def _retrieval_trace(raw_sources: list[dict]) -> dict:
    """Keep enough sanitized provenance to prove whether a graph arm added evidence."""
    strategies = sorted({
        str(row.get("retrieval_strategy"))
        for row in raw_sources
        if row.get("retrieval_strategy")
    })
    graph_evidence = []
    for row in raw_sources:
        relation = row.get("graph_relation")
        if not isinstance(relation, dict):
            continue
        graph_evidence.append({
            "citation_id": row.get("citation_id"),
            "event_id": relation.get("event_id"),
            "action": relation.get("action"),
            "role": relation.get("role"),
            "source_norma_id": relation.get("source_norma_id"),
            "target_norma_id": relation.get("target_norma_id"),
            "source_device_key": relation.get("source_device_key"),
            "target_device_key": relation.get("target_device_key"),
            "review_status": relation.get("review_status"),
            "effective_status": relation.get("effective_status"),
            "effective_on": relation.get("effective_on"),
            "resolution": relation.get("resolution"),
        })
    return {
        "retrieval_strategies": strategies,
        "graph_evidence": graph_evidence,
    }


def _prediction_for_run(
    *, case, arm, repeat, cache_state, options, settings, model, temperature,
    max_sources, corpus_revision, hardware,
):
    from src.processing.adaptive_rag_service import AdaptiveRAGService

    service = AdaptiveRAGService(use_cache=True)
    started = time.perf_counter()
    first_chunk_ms = None
    source_rows: list[dict] = []
    done = None
    for event in service.stream_answer_question(
        question=case["query"],
        k=max_sources,
        model=model,
        temperature=temperature,
        options=options,
    ):
        if event.get("event") == "sources":
            source_rows = event.get("sources") or []
        elif event.get("event") == "chunk" and first_chunk_ms is None:
            first_chunk_ms = round((time.perf_counter() - started) * 1000)
        elif event.get("event") == "done":
            done = event
    if done is None:
        raise RuntimeError(f"case {case['case_id']} arm {arm}: stream ended without done")

    retrieved_ids, serialized_sources = _source_ids_and_versions(source_rows)
    retrieval_trace = _retrieval_trace(source_rows)
    answer = str(done.get("answer") or "")
    cited_positions = {int(match.group(1)) for match in _CITATION_MARKER.finditer(answer)}
    citation_ids = []
    cited_versions = {}
    for position in sorted(cited_positions):
        if not 1 <= position <= len(serialized_sources):
            continue
        source = serialized_sources[position - 1]
        citation_id = source.get("citation_id") or source.get("source_id")
        if citation_id is None:
            continue
        citation_id = str(citation_id)
        citation_ids.append(citation_id)
        version = source.get("temporal_version") or {}
        version_hash = version.get("version_hash")
        if version_hash:
            cited_versions[citation_id] = str(version_hash)

    timings = done.get("timings_ms") or {}
    cache_hit = bool(done.get("cached"))
    if cache_state == "warm" and not cache_hit:
        raise RuntimeError(f"case {case['case_id']} arm {arm}: expected a verified answer-cache hit")
    if cache_state == "cold" and cache_hit:
        raise RuntimeError(f"case {case['case_id']} arm {arm}: cold run unexpectedly used a cached answer")
    return {
        "case_id": case["case_id"],
        "arm": arm,
        "repeat": repeat,
        "corpus_revision": corpus_revision,
        "model": model,
        "temperature": temperature,
        "token_budget": TOKEN_BUDGET,
        "hardware": hardware,
        "cache_state": cache_state,
        "retrieved_source_ids": retrieved_ids,
        **retrieval_trace,
        "cited_citation_ids": list(dict.fromkeys(citation_ids)),
        "expected_source_ids": case["expected_source_ids"],
        "expected_citation_ids": case["expected_citation_ids"],
        "expected_versions": case["expected_versions"],
        "cited_versions": cited_versions,
        "expected_abstain": case["expected_abstain"],
        "abstained": (done.get("grounded") is False)
        or done.get("reason_code") == "insufficient_evidence",
        "human_evidence_review": False,
        "ttft_ms": first_chunk_ms if first_chunk_ms is not None else round((time.perf_counter() - started) * 1000),
        "final_ms": int(timings.get("total_before_done") or round((time.perf_counter() - started) * 1000)),
        "retrieval_ms": timings.get("retrieval"),
        "cache_hit": cache_hit,
        "cache_scope": f"answer_cache_{cache_state}; query_embedding_state_in_summary; search_result_cache_unused; models_preloaded",
        "embedding_model": settings.OLLAMA_EMBEDDING_MODEL,
        "stratum": case.get("stratum", "unspecified"),
        "as_of": case.get("as_of"),
        "graph_enabled": arm != "baseline",
        "history_enabled": arm == "graph_temporal",
    }


def collect(cases: list[dict], *, output: Path, temperature: float, max_sources: int,
            include_warm: bool = True) -> dict:
    settings, model, qa_root_text = _ensure_qa_runtime()
    qa_root = Path(qa_root_text)
    output = output.resolve()
    if not output.is_relative_to(qa_root) or output == qa_root:
        raise RuntimeError("prediction output must stay inside JURIX_QA_ROOT")
    summary_path = output.with_suffix(output.suffix + ".summary.json")
    if output.exists() or summary_path.exists():
        raise FileExistsError("refusing to overwrite existing QA experiment evidence")
    output.parent.mkdir(parents=True, exist_ok=True)

    from django.test.utils import override_settings

    from src.llm_engine.ollama_service import OllamaService
    from src.processing.adaptive_retrieval import RetrievalOptions
    from src.processing.cache_service import CacheService
    from src.processing.corpus_identity import compute_corpus_identity, get_corpus_revision
    from src.processing.temporal_scope import TemporalScope

    durable = get_corpus_revision()
    if durable and durable.get("digest"):
        corpus_revision = f"r{durable['revision']}:{durable['digest']}"
        revision_state = durable.get("completeness", "unknown")
    else:
        digest, counts = compute_corpus_identity()
        corpus_revision = f"unversioned:{digest}"
        revision_state = f"computed_read_only:{counts.get('norm_count', 0)}_norms"

    hardware = f"{platform.system()}-{platform.release()};cpu_logical={os.cpu_count() or 'unknown'};gpu=not_recorded"
    run_id = uuid.uuid4().hex
    cache_service = CacheService()
    ollama = OllamaService(model=settings.OLLAMA_EMBEDDING_MODEL)
    if not ollama.generate_text(
        "Responda apenas com a palavra pronto.",
        model=model,
        temperature=0,
        max_tokens=8,
    ):
        raise RuntimeError("shared Ollama generation-model warmup failed")
    if not ollama.generate_embedding(
        "aquecimento compartilhado do modelo de embeddings do experimento QA",
        model=settings.OLLAMA_EMBEDDING_MODEL,
    ):
        raise RuntimeError("shared Ollama embedding-model warmup failed")
    all_rows = []
    warm_groups = 0
    warm_partial_groups = 0
    warm_partial_arms = {}
    cold_groups = 0
    warm_skipped = {}
    warm_cache_checks = {}

    for case in cases:
        case_arm_options = {}
        case_arm_kwargs = {}
        cold_rows = []
        for arm in ARMS:
            graph_enabled = arm != "baseline"
            history_enabled = arm == "graph_temporal"
            scope = TemporalScope(as_of=date.fromisoformat(case["as_of"])) if history_enabled and case.get("as_of") else TemporalScope()
            base_options = RetrievalOptions(
                mode="hybrid", norma_status="all", source_scope="all",
                max_sources=max_sources, temporal_scope=scope,
            )
            options = _make_options(base_options, f"{run_id}:{case['case_id']}:{arm}")
            kwargs = _cache_kwargs(
                cache_service,
                question=case["query"].strip(),
                k=max_sources,
                model=model,
                temperature=temperature,
                options=options,
                endpoint=settings.OLLAMA_BASE_URL,
            )
            case_arm_options[arm] = options
            case_arm_kwargs[arm] = kwargs
            _delete_answer_cache(cache_service, kwargs)
            _delete_query_embedding_cache(
                cache_service,
                question=case["query"],
                embedding_model=settings.OLLAMA_EMBEDDING_MODEL,
            )
            with override_settings(
                RAG_GRAPH_CONTEXT_ENABLED=graph_enabled,
                NORMATIVE_HISTORY_ENABLED=history_enabled,
            ):
                cold_rows.append(_prediction_for_run(
                    case=case, arm=arm, repeat=0, cache_state="cold", options=options,
                    settings=settings, model=model, temperature=temperature,
                    max_sources=max_sources, corpus_revision=corpus_revision, hardware=hardware,
                ))
        cold_groups += 1
        all_rows.extend(cold_rows)

        if not include_warm:
            continue
        bypass_reason = _warm_cache_bypass_reason(case)
        if bypass_reason:
            warm_skipped[case["case_id"]] = bypass_reason
            warm_cache_checks[case["case_id"]] = {
                "reason": bypass_reason,
                "eligible_arms": [],
                "fully_paired": False,
                "query_embedding_cached": None,
            }
            continue
        cache_check = _probe_warm_cache(
            cache_service,
            kwargs_by_arm=case_arm_kwargs,
            question=case["query"],
            embedding_model=settings.OLLAMA_EMBEDDING_MODEL,
        )
        warm_cache_checks[case["case_id"]] = cache_check
        eligible_arms = cache_check["eligible_arms"]
        if not eligible_arms:
            warm_skipped[case["case_id"]] = "no_answer_cache_hit_for_any_arm"
            continue

        warm_rows = []
        try:
            for arm in eligible_arms:
                with override_settings(
                    RAG_GRAPH_CONTEXT_ENABLED=arm != "baseline",
                    NORMATIVE_HISTORY_ENABLED=arm == "graph_temporal",
                ):
                    warm_rows.append(_prediction_for_run(
                        case=case, arm=arm, repeat=1, cache_state="warm",
                        options=case_arm_options[arm], settings=settings, model=model,
                        temperature=temperature, max_sources=max_sources,
                        corpus_revision=corpus_revision, hardware=hardware,
                    ))
        except RuntimeError:
            warm_skipped[case["case_id"]] = "answer-cache-hit-not-confirmed-for-eligible-arm"
            continue
        all_rows.extend(warm_rows)
        if cache_check["fully_paired"]:
            warm_groups += 1
        else:
            warm_partial_groups += 1
            warm_partial_arms[case["case_id"]] = eligible_arms

    serialized = "".join(json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in all_rows)
    output.write_text(serialized, encoding="utf-8", newline="\n")
    summary = {
        "status": "technical_smoke_only",
        "scientific_claim_allowed": False,
        "human_gold_present": False,
        "dataset_origin": "synthetic_qa_fixtures_only",
        "case_count": len(cases),
        "selected_case_ids": [case["case_id"] for case in cases],
        "cold_paired_groups": cold_groups,
        "warm_paired_groups": warm_groups,
        "warm_partial_groups": warm_partial_groups,
        "warm_partial_arms": warm_partial_arms,
        "prediction_rows": len(all_rows),
        "warm_skipped": warm_skipped,
        "warm_cache_checks": warm_cache_checks,
        "arms": list(ARMS),
        "model": model,
        "temperature": temperature,
        "token_budget": TOKEN_BUDGET,
        "max_sources": max_sources,
        "corpus_revision": corpus_revision,
        "corpus_revision_state": revision_state,
        "hardware": hardware,
        "cache_scope": "answer_cache_by_arm; query_embedding_state_reported; search_result_cache_unused; shared_model_warmup",
        "model_warmup": "generation_and_embedding_models_preloaded_once_before_all_arms",
        "predictions_path": str(output),
        "run_id": run_id,
    }
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--max-cases", type=int, default=MAX_CASES)
    parser.add_argument("--temperature", type=float, default=0.1)
    parser.add_argument("--max-sources", type=int, default=12)
    parser.add_argument("--no-warm-cache", action="store_true")
    args = parser.parse_args(argv)
    try:
        if not 0 <= args.temperature <= 1 or not 1 <= args.max_sources <= 48:
            raise ValueError("temperature or max-sources outside the supported QA range")
        cases = _read_cases(args.cases, max_cases=args.max_cases)
        result = collect(
            cases,
            output=args.output,
            temperature=args.temperature,
            max_sources=args.max_sources,
            include_warm=not args.no_warm_cache,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"RAG collection error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
