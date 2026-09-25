"""
Corpus-versioned cache (audit P1.3).

Answers/searches used to survive for 12h/24h after a reindex or consolidation, and
the only "invalidation" (clear_cache) was never called and would have flushed the
whole Redis DB, which Celery shares as its broker.
"""

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
