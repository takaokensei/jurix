from unittest.mock import Mock, patch

from django.test import override_settings

from src.processing.rag_service import RAGService


@override_settings(RAG_STREAM_PROVISIONAL_OUTPUT=True)
@patch("src.processing.rag_service.OllamaService")
def test_stream_forwards_ollama_chunks_incrementally(mock_service):
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
    chunks = [item["chunk"] for item in events if item.get("event") == "chunk"]
    assert chunks == ["pri", "mei", "ro"]
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
