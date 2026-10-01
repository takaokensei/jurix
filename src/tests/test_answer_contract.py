from src.processing.answer_contract import build_answer_contract


def test_answer_dto_has_stable_provenance_and_excludes_unapproved_filter_fields():
    dto = build_answer_contract(
        question="E o artigo 7?",
        retrieval_query="E o artigo 7? Contexto: Lei 8206/2026",
        filters={
            "mode": "hybrid",
            "max_sources": 4,
            "attachment_texts": ("não persistir este conteúdo",),
            "api_key": "never-serialize",
        },
        provider="ollama",
        model="llama3",
        sources=[{"id": 12, "numero": "7º", "evidence_text": "Texto do art. 7º."}],
        grounding={"grounded": True, "claims": [{"claim_id": "c1", "source_ids": [12]}]},
        grounded=True,
        corpus_revision={"revision": 5, "digest": "abc123", "completeness": "unknown"},
        request_id="req-test",
        timings_ms={"retrieval": 15, "generation": 1200},
        generation_attempts=[{"attempt": 1, "duration_ms": 1200}],
    )

    assert dto["schema_version"] == 1
    assert dto["request_id"] == "req-test"
    assert dto["corpus_revision"] == {
        "revision": 5,
        "digest": "abc123",
        "completeness": "unknown",
    }
    assert dto["question"] == "E o artigo 7?"
    assert dto["retrieval_query"].endswith("Lei 8206/2026")
    assert dto["filters"] == {"mode": "hybrid", "max_sources": 4}
    assert dto["source_count"] == 1
    assert dto["sources"][0]["device_id"] == 12
    assert "never-serialize" not in str(dto)
    assert "não persistir este conteúdo" not in str(dto)
    assert dto["timings_ms"] == {"retrieval": 15, "generation": 1200}
    assert dto["generation_attempts"] == [{"attempt": 1, "duration_ms": 1200}]
