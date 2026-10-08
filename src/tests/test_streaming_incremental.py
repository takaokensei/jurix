from unittest.mock import Mock, patch

from src.processing.rag_contract_helpers import contract, grounding_fallback
from src.processing.rag_service import RAGService


@patch("src.processing.rag_service.OllamaService")
def test_stream_reveals_only_grounded_answer_incrementally(mock_service):
    ollama = Mock()
    ollama.stream_text.return_value = iter(["pri", "mei", "ro"])
    mock_service.return_value = ollama

    service = RAGService(use_cache=False)
    service.get_relevant_context = Mock(
        return_value=(
            "contexto",
            [{"similarity_score": 0.9, "retrieval_score": 0.9}],
        )
    )
    service._ground_answer = staticmethod(
        lambda answer, results: {"grounded": True, "failed_claims": []}
    )

    events = list(service.stream_answer_question("pergunta", k=3, model="llama3"))
    statuses = [item["status"] for item in events if item.get("event") == "status"]
    assert statuses.index("generating") < statuses.index("grounding") < statuses.index("finalizing")
    chunk_events = [item for item in events if item.get("event") == "chunk"]
    source_index = next(i for i, item in enumerate(events) if item.get("event") == "sources")
    first_chunk_index = next(i for i, item in enumerate(events) if item.get("event") == "chunk")
    assert source_index < first_chunk_index
    assert [item["chunk"] for item in chunk_events] == ["primeiro"]
    assert all(item.get("provisional") is False for item in chunk_events)
    assert all("replace" not in item for item in chunk_events)
    grounding_index = next(i for i, item in enumerate(events) if item.get("status") == "grounding")
    # With no sentence boundary, the complete answer is released after final
    # validation and before the service emits its terminal grounding status.
    assert first_chunk_index < grounding_index
    assert events[-1]["event"] == "done"
    assert events[-1]["answer"] == "primeiro"
    assert events[-1]["timings_ms"]["retrieval"] >= 0
    assert events[-1]["timings_ms"]["generation"] >= 0
    assert events[-1]["generation_attempts"] == [
        {
            "attempt": 1,
            "duration_ms": events[-1]["generation_attempts"][0]["duration_ms"],
            "time_to_first_chunk_ms": events[-1]["generation_attempts"][0][
                "time_to_first_chunk_ms"
            ],
            "output_characters": len("primeiro"),
        }
    ]


def test_validated_answer_chunking_preserves_markdown_and_whitespace():
    answer = "A Lei 8.206/2026, Art. 1º, institui o programa.\n\nA norma entrou em vigor."
    chunks = list(RAGService._iter_answer_chunks(answer, max_chars=20))
    assert "".join(chunks) == answer
    assert len(chunks) > 1


def test_contract_reason_codes_distinguish_missing_generation_and_insufficient_evidence():
    base = {
        "answer": "Resposta segura.",
        "source_relevance": 0.0,
        "grounding": {"grounded": False, "claims": [], "failed_claims": []},
        "model": "llama3",
    }
    missing = contract(**base, sources=[], grounded=False)
    insufficient = contract(**base, sources=[{"id": 8}], grounded=False)
    generation = contract(
        **{
            **base,
            "grounding": {"grounded": False, "reason": "generation_empty", "claims": [], "failed_claims": []},
        },
        sources=[{"id": 8}],
        grounded=False,
    )

    assert "reason_code" not in missing
    assert insufficient["reason_code"] == "evidence_insufficient"
    assert generation["reason_code"] == "generation_failed"
    fallback = grounding_fallback().casefold()
    assert "delimitar a pergunta" in fallback
    assert "indique o número e o ano" not in fallback


def test_missing_norma_reason_skips_sync_and_stream_generation():
    from src.processing.rag_context_builder import EvidenceRows

    ollama = Mock()
    with patch("src.processing.rag_service.OllamaService", return_value=ollama):
        service = RAGService(use_cache=False)
    service.get_relevant_context = Mock(
        return_value=(
            "Nenhum contexto relevante encontrado.",
            EvidenceRows(
                reason_code="norm_not_in_corpus",
                coverage={"strategy": "whole_norma", "complete": False, "selected_devices": 0},
            ),
        )
    )

    sync = service.answer_question("O que prevê a Lei nº 99999/2026?", model="llama3")
    events = list(service.stream_answer_question("O que prevê a Lei nº 99999/2026?"))
    source_event = next(item for item in events if item.get("event") == "sources")
    done_event = events[-1]

    assert sync["reason_code"] == "norm_not_in_corpus"
    assert "Não localizei essa norma" in sync["answer"]
    assert sync["sources"] == []
    assert source_event["reason_code"] == "norm_not_in_corpus"
    assert source_event["sources"] == []
    assert done_event["reason_code"] == "norm_not_in_corpus"
    assert done_event["coverage"]["selected_devices"] == 0
    ollama.generate_text.assert_not_called()
    ollama.stream_text.assert_not_called()


def test_answer_endpoints_expose_missing_norm_reason_without_calling_llm(monkeypatch):
    import json

    from django.test import Client

    from src.apps.legislation import api_search, api_views
    from src.processing.adaptive_rag_service import AdaptiveRAGService
    from src.processing.rag_context_builder import EvidenceRows

    ollama = Mock()
    with patch("src.processing.rag_service.OllamaService", return_value=ollama):
        service = AdaptiveRAGService(use_cache=False)
    service.get_relevant_context = Mock(
        return_value=(
            "Nenhum contexto relevante encontrado.",
            EvidenceRows(reason_code="norm_not_in_corpus", coverage={"selected_devices": 0}),
        )
    )
    monkeypatch.setattr(api_search, "RAGService", lambda: service)
    monkeypatch.setattr(api_views, "RAGService", lambda: service)
    client = Client()
    question = "O que prevê a Lei nº 99999/2026?"

    sync = client.post(
        "/api/v1/search/answer/",
        data=json.dumps({"question": question}),
        content_type="application/json",
    )
    assert sync.status_code == 200
    sync_body = sync.json()
    assert sync_body["metadata"]["reason_code"] == "norm_not_in_corpus"
    assert sync_body["metadata"]["contract"]["reason_code"] == "norm_not_in_corpus"
    assert sync_body["sources"] == []
    assert "tipo da norma" in sync_body["answer"]
    assert "indique o número e o ano" not in sync_body["answer"].casefold()

    streamed = client.post(
        "/api/v1/search/answer/stream/",
        data=json.dumps({"question": question}),
        content_type="application/json",
    )
    assert streamed.status_code == 200
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in b"".join(streamed.streaming_content).decode().splitlines()
        if line.startswith("data: ")
    ]
    source_payload = next(item for item in payloads if item["type"] == "sources")
    done_payload = next(item for item in payloads if item["type"] == "done")
    assert source_payload["reason_code"] == "norm_not_in_corpus"
    assert source_payload["sources"] == []
    assert done_payload["reason_code"] == "norm_not_in_corpus"
    assert done_payload["contract"]["reason_code"] == "norm_not_in_corpus"
    assert "tipo da norma" in done_payload["answer"]
    assert "indique o número e o ano" not in done_payload["answer"].casefold()
    ollama.generate_text.assert_not_called()
    ollama.stream_text.assert_not_called()


def test_stream_contract_labels_grounding_refusal_and_keeps_sources_nonfinal(monkeypatch):
    import json

    from django.test import Client

    from src.apps.legislation import api_search, api_views
    from src.processing.rag_contract_helpers import grounding_fallback

    source = {
        "id": 8,
        "norma_ref": "Lei nº 8.206/2026",
        "dispositivo_ref": "Art. 1º",
        "texto": "Dispositivo recuperado sem apoio suficiente para a afirmação.",
    }

    class InsufficientService:
        def stream_answer_question(self, *_args, **_kwargs):
            yield {"event": "status", "status": "generating"}
            yield {"event": "sources", "sources": [source]}
            yield {"event": "status", "status": "insufficient_evidence"}
            yield {
                "event": "done",
                "answer": grounding_fallback(),
                "sources": [source],
                "grounded": False,
                "grounding": {"grounded": False, "claims": [], "failed_claims": ["claim"]},
            }

    monkeypatch.setattr(api_search, "RAGService", InsufficientService)
    monkeypatch.setattr(api_views, "RAGService", InsufficientService)
    response = Client(REMOTE_ADDR="192.0.2.81").post(
        "/api/v1/search/answer/stream/",
        data=json.dumps({"question": "O que estabelece a norma?"}),
        content_type="application/json",
    )
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in b"".join(response.streaming_content).decode().splitlines()
        if line.startswith("data: ")
    ]
    sources_event = next(item for item in payloads if item["type"] == "sources")
    done_event = next(item for item in payloads if item["type"] == "done")
    assert sources_event["sources"], f"retrieval metadata may arrive before final grounding: {payloads}"
    assert done_event["reason_code"] == "evidence_insufficient"
    assert done_event["contract"]["reason_code"] == "evidence_insufficient"
    assert done_event["contract"]["corpus_coverage"]["coverage_status"] == "unknown"
    assert done_event["contract"]["corpus_coverage"]["checked_until"] is None
    assert done_event["grounded"] is False
    assert done_event["contract"]["sources"] == []


def test_stream_completion_reconciles_drawer_to_grounded_citation_sources(monkeypatch):
    import json

    from django.test import Client

    from src.apps.legislation import api_search, api_views

    sources = [
        {
            "id": 18,
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 18",
            "texto": "O vencimento básico não poderá ser inferior ao salário mínimo.",
        },
        {
            "id": 33,
            "norma_ref": "Lei Complementar nº 120/2010",
            "dispositivo_ref": "Art. 33",
            "texto": "Revisão anual de valores remuneratórios.",
        },
        {
            "id": 4,
            "norma_ref": "Decreto nº 9.571/2011",
            "dispositivo_ref": "Art. 4º",
            "texto": "Dispositivo contextual recuperado, mas não citado.",
        },
    ]

    class GroundedService:
        def stream_answer_question(self, *_args, **_kwargs):
            yield {"event": "sources", "sources": sources}
            yield {"event": "chunk", "chunk": "O piso segue o mínimo [[1]]."}
            yield {
                "event": "done",
                "answer": "O piso segue o mínimo [[1]].",
                "grounded": True,
                "grounding": {
                    "grounded": True,
                    "claims": [{
                        "supported": True,
                        "matches": [{"citation_indexes": [1]}],
                    }],
                },
            }

    monkeypatch.setattr(api_search, "RAGService", GroundedService)
    monkeypatch.setattr(api_views, "RAGService", GroundedService)
    response = Client(REMOTE_ADDR="192.0.2.83").post(
        "/api/v1/search/answer/stream/",
        data=json.dumps({"question": "Qual é o piso do vencimento?"}),
        content_type="application/json",
    )
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in b"".join(response.streaming_content).decode().splitlines()
        if line.startswith("data: ")
    ]
    sources_event = next(item for item in payloads if item["type"] == "sources")
    done_event = next(item for item in payloads if item["type"] == "done")

    assert len(sources_event["sources"]) == 3  # Full retrieval set stays visible during streaming.
    assert [source["dispositivo_ref"] for source in done_event["sources"]] == ["Art. 18"]
    assert done_event["sources"][0]["citation_index"] == 1
    assert [source["article"] for source in done_event["contract"]["sources"]] == ["Art. 18"]


def test_nonstream_answer_contract_uses_the_same_cited_source_subset(monkeypatch):
    import json

    from django.test import Client

    from src.apps.legislation import api_search, api_views

    class GroundedService:
        def answer_question(self, **_kwargs):
            return {
                "answer": "O vencimento segue o mínimo [[2]].",
                "grounded": True,
                "grounding": {
                    "grounded": True,
                    "claims": [{
                        "supported": True,
                        "matches": [{"citation_indexes": [2]}],
                    }],
                },
                "sources": [
                    {"id": 18, "norma_ref": "LC 120", "dispositivo_ref": "Art. 18", "text": "piso"},
                    {"id": 33, "norma_ref": "LC 120", "dispositivo_ref": "Art. 33", "text": "reajuste"},
                ],
                "confidence": None,
                "model": "qa-model",
            }

    monkeypatch.setattr(api_search, "RAGService", GroundedService)
    monkeypatch.setattr(api_views, "RAGService", GroundedService)
    response = Client(REMOTE_ADDR="192.0.2.84").post(
        "/api/v1/search/answer/",
        data=json.dumps({"question": "Qual é o piso do vencimento?"}),
        content_type="application/json",
    )
    payload = json.loads(response.content)

    assert response.status_code == 200
    assert payload["grounded"] is True
    assert [source["dispositivo_ref"] for source in payload["sources"]] == ["Art. 33"]
    assert [source["article"] for source in payload["metadata"]["contract"]["sources"]] == ["Art. 33"]


def test_generation_exception_emits_safe_reason_code_without_unverified_answer(monkeypatch):
    import json

    from django.test import Client

    from src.apps.legislation import api_search, api_views

    class FailingService:
        def stream_answer_question(self, *_args, **_kwargs):
            yield {"event": "status", "status": "generating"}
            raise RuntimeError("private provider diagnostic")

    monkeypatch.setattr(api_search, "RAGService", FailingService)
    monkeypatch.setattr(api_views, "RAGService", FailingService)
    response = Client(REMOTE_ADDR="192.0.2.82").post(
        "/api/v1/search/answer/stream/",
        data=json.dumps({"question": "Consulte esta norma"}),
        content_type="application/json",
    )
    payloads = [
        json.loads(line.removeprefix("data: "))
        for line in b"".join(response.streaming_content).decode().splitlines()
        if line.startswith("data: ")
    ]
    failure = next((item for item in payloads if item["type"] == "error"), None)
    assert failure is not None, f"expected a safe SSE error after generation failed: {payloads}"
    assert failure["reason_code"] == "generation_failed"
    assert "tente novamente" in failure["error"].casefold()
    assert "private provider diagnostic" not in failure["error"]
    assert not any(item["type"] == "chunk" for item in payloads)
