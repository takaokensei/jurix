"""
Corpus-versioned cache (audit P1.3).

Answers/searches used to survive for 12h/24h after a reindex or consolidation, and
the only "invalidation" (clear_cache) was never called and would have flushed the
whole Redis DB, which Celery shares as its broker.
"""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from django.core.cache import cache

from src.processing.cache_service import CacheService


@pytest.fixture(autouse=True)
def locmem(settings):
    settings.CACHES = {
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "cache-svc",
        }
    }
    cache.clear()
    yield
    cache.clear()


@pytest.fixture
def svc():
    return CacheService()


ANSWER = {"answer": "resposta", "sources": [], "confidence": 0.9}


def test_answer_is_served_until_the_corpus_changes(svc):
    svc.set_answer("q?", k=5, model="m", answer_data=ANSWER)
    assert svc.get_answer("q?", k=5, model="m")["answer"] == "resposta"

    svc.bump_corpus_version()

    assert svc.get_answer("q?", k=5, model="m") is None


def test_cached_answer_preserves_structured_citation_and_overview_metadata(svc):
    device = SimpleNamespace(id=12, texto="Trecho jurídico", get_full_identifier=lambda: "Art. 1º")
    coverage = {"total_articles": 4, "selected_articles": 4, "complete": True}
    svc.set_answer(
        "q?",
        k=5,
        model="m",
        answer_data={
            "answer": "Resposta [[1]]",
            "sources": [{
                "dispositivo": device,
                "similarity_score": 0.0,
                "distance": 1.0,
                "citation_id": "jurix:norma:3:dispositivo:12",
                "citation_index": 1,
                "citation_label": "Lei nº 8.206/2026, Art. 1º",
                "retrieval_strategy": "whole_norma",
                "evidence_scope": "complete",
                "coverage": coverage,
            }],
        },
    )

    source = svc.get_answer("q?", k=5, model="m")["sources"][0]
    assert source["citation_id"] == "jurix:norma:3:dispositivo:12"
    assert source["citation_index"] == 1
    assert source["retrieval_strategy"] == "whole_norma"
    assert source["coverage"] == coverage


def test_search_results_are_invalidated_too(svc):
    result = {
        "dispositivo": SimpleNamespace(id=1),
        "similarity_score": 0.9,
        "distance": 0.1,
        "context": "ctx",
        "embedding_model": "m",
    }
    svc.set_search_results("q", k=3, filters={}, results=[result])
    assert svc.get_search_results("q", k=3, filters={}) is not None
    svc.bump_corpus_version()
    assert svc.get_search_results("q", k=3, filters={}) is None


def test_query_embeddings_survive_a_corpus_change(svc):
    """An embedding depends on the query and the model, never on the corpus."""
    svc.set_embedding("q", "nomic", [0.1, 0.2])
    svc.bump_corpus_version()
    assert svc.get_embedding("q", "nomic") == [0.1, 0.2]


def test_version_is_monotonic_and_starts_at_zero(svc):
    assert svc.get_corpus_version() == 0
    assert svc.bump_corpus_version() == 1
    assert svc.bump_corpus_version() == 2
    assert svc.get_corpus_version() == 2


def test_answer_generated_before_a_bump_is_never_served_after_it(svc):
    """A slow generation must not be stored under the NEW version."""
    version_at_start = svc.get_corpus_version()
    svc.bump_corpus_version()  # corpus changes mid-generation
    svc.set_answer("q?", k=5, model="m", answer_data=ANSWER, corpus_version=version_at_start)
    assert svc.get_answer("q?", k=5, model="m") is None  # not served as fresh
    assert svc.get_answer("q?", k=5, model="m", corpus_version=version_at_start) is not None


def test_durable_corpus_revision_prevents_cross_worker_stale_cache_hits(svc):
    with patch.object(svc, "get_corpus_revision_digest", return_value="r7:old-digest"):
        svc.set_answer("q?", k=5, model="m", answer_data=ANSWER)
    with patch.object(svc, "get_corpus_revision_digest", return_value="r8:new-digest"):
        assert svc.get_answer("q?", k=5, model="m") is None


def test_answer_cache_separates_generation_provider_endpoint_and_temperature(svc):
    common = {"model": "same-model", "temperature": 0.2}
    ollama = svc.generation_fingerprint(
        provider="ollama", endpoint="http://localhost:11434/", **common
    )
    other_endpoint = svc.generation_fingerprint(
        provider="compatible", endpoint="http://localhost:1234/v1", **common
    )
    other_temperature = svc.generation_fingerprint(
        provider="ollama",
        endpoint="http://localhost:11434",
        **{**common, "temperature": 0.8},
    )
    assert len({ollama, other_endpoint, other_temperature}) == 3

    svc.set_answer(
        "q?",
        k=5,
        model="same-model",
        answer_data=ANSWER,
        generation_fingerprint=ollama,
    )
    assert (
        svc.get_answer("q?", k=5, model="same-model", generation_fingerprint=other_endpoint) is None
    )


def test_generation_fingerprint_does_not_contain_credentials():
    fingerprint = CacheService.generation_fingerprint(
        provider="compatible",
        model="model-a",
        endpoint="https://user:very-secret@example.test/v1?api_key=also-secret",
        temperature=0.3,
    )
    assert "very-secret" not in fingerprint
    assert "also-secret" not in fingerprint
    assert len(fingerprint) == 64


def test_clear_cache_invalidates_answers_without_flushing_the_shared_db(svc):
    cache.set("celery-queue-marker", "must survive")
    svc.set_answer("q?", k=5, model="m", answer_data=ANSWER)

    assert svc.clear_cache() is True

    assert svc.get_answer("q?", k=5, model="m") is None
    assert cache.get("celery-queue-marker") == "must survive"


def test_clear_cache_with_unsupported_prefix_does_not_pretend_to_succeed(svc):
    assert svc.clear_cache(prefix="nonsense:") is False


def test_cache_outage_never_raises(svc):
    with patch("src.processing.cache_service.cache") as broken:
        broken.get.side_effect = ConnectionError("redis down")
        broken.add.side_effect = ConnectionError("redis down")
        assert svc.get_corpus_version() == 0
        assert svc.bump_corpus_version() is None
        assert svc.get_answer("q?", k=5, model="m") is None


@pytest.mark.parametrize(
    "payload",
    [
        ["not an object"],
        {"sources": []},
        {"answer": "ok", "sources": {}},
        {"answer": "ok", "sources": [], "grounding": []},
    ],
)
def test_malformed_cached_answer_is_discarded(svc, payload):
    cache.set(
        svc._generate_key(
            svc.ANSWER_PREFIX,
            "cache0:unavailable:v0:q?:k=5:model=m:retrieval=:generation=",
        ),
        json.dumps(payload),
    )

    assert svc.get_answer("q?", k=5, model="m") is None
