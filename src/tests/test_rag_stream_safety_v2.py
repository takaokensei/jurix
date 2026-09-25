from unittest.mock import Mock, patch

from django.test import SimpleTestCase, override_settings

from src.processing.rag_service import RAGService


class RAGStreamingSafetyTests(SimpleTestCase):
    @override_settings(RAG_STREAM_PROVISIONAL_OUTPUT=False)
    def test_streaming_does_not_expose_provisional_chunks(self):
        service = RAGService(use_cache=False)
        source = {
            "text": "A Lei 1234/2025 exige 3 documentos.",
            "norma_ref": "Lei 1234/2025",
            "identifier": "Art. 1",
            "dispositivo_id": 1,
        }
        fake = Mock()
        fake.stream_text.return_value = iter(["A Lei 1234/2025 exige 3 documentos."])
        service.ollama = fake
        with patch.object(service, "get_relevant_context", return_value=("ctx", [source])):
            with patch.object(service, "_answer_uses_only_sources", return_value=True):
                with patch.object(
                    service,
                    "_ground_answer",
                    return_value={
                        "grounded": True,
                        "strict": True,
                        "score": 1.0,
                        "claims": [],
                        "failed_claims": [],
                        "source_diversity_ok": True,
                    },
                ):
                    events = list(service.stream_answer_question("qual o prazo?"))
        chunks = [event for event in events if event.get("event") == "chunk"]
        assert chunks
        assert all(event.get("provisional") is False for event in chunks)
