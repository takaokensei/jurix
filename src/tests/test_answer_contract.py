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
        sources=[
            {
                "id": 12,
                "numero": "7º",
                "norma_id": 3,
                "citation_id": "jurix:norma:3:dispositivo:12",
                "citation_index": 1,
                "citation_label": "Lei nº 8.206/2026, Art. 7º",
                "dispositivo_ref": "Art. 7º",
                "sapl_url": "https://sapl.natal.rn.leg.br/norma/normajuridica/3/",
                "evidence_text": "Texto do art. 7º.",
            }
        ],
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
    assert dto["sources"][0]["citation_id"] == "jurix:norma:3:dispositivo:12"
    assert dto["sources"][0]["citation_index"] == 1
    assert dto["sources"][0]["official_url"].endswith("/3/")
    assert dto["sources"][0]["evidence_text"] == "Texto do art. 7º."
    assert "never-serialize" not in str(dto)
    assert "não persistir este conteúdo" not in str(dto)
    assert dto["timings_ms"] == {"retrieval": 15, "generation": 1200}
    assert dto["generation_attempts"] == [{"attempt": 1, "duration_ms": 1200}]


def test_answer_contract_uses_only_the_context_snippet_as_grounding_evidence():
    dto = build_answer_contract(
        question="O que prevê a norma?",
        retrieval_query="O que prevê a norma?",
        filters={},
        provider="ollama",
        model="llama3",
        sources=[
            {
                "id": 1,
                "full_text": "Conteúdo não enviado ao modelo " + ("x" * 2_000),
                "snippet": "Trecho efetivamente enviado ao modelo.",
                "evidence_text": "Trecho efetivamente enviado ao modelo.",
            }
        ],
        corpus_revision={"completeness": "unknown"},
    )

    assert dto["sources"][0]["evidence_text"] == "Trecho efetivamente enviado ao modelo."
    assert "Conteúdo não enviado" not in str(dto)


def test_answer_contract_preserves_structured_no_retrieval_reason():
    dto = build_answer_contract(
        question="O que prevê a Lei nº 99999/2026?",
        retrieval_query="O que prevê a Lei nº 99999/2026?",
        filters={},
        provider="ollama",
        model="llama3",
        reason_code="norm_not_in_corpus",
    )

    assert dto["reason_code"] == "norm_not_in_corpus"
    assert dto["sources"] == []
