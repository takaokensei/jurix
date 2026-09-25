from django.test import SimpleTestCase, override_settings

from src.processing.rag_assurance import assess_answer


class RAGAssuranceV4Tests(SimpleTestCase):
    def source(self, text):
        return {"text": text, "norma_ref": "Lei 1234/2025", "identifier": "Art. 1", "dispositivo_id": 1}

    def test_supported_answer_passes_final_contract(self):
        report = assess_answer("A Lei 1234/2025 exige 3 documentos.", [self.source("A Lei 1234/2025 exige 3 documentos.")])
        assert report["grounded"] is True
        assert report["policy"]["accepted"] is True

    @override_settings(RAG_REQUIRE_SOURCE_CITATIONS=True)
    def test_answer_without_legal_citation_is_rejected(self):
        report = assess_answer("A regra exige 3 documentos.", [self.source("A Lei 1234/2025 exige 3 documentos.")])
        assert report["grounded"] is False

    @override_settings(RAG_MAX_ANSWER_CHARS=10)
    def test_oversized_answer_is_rejected(self):
        report = assess_answer("0123456789X", [])
        assert report["grounded"] is False
        assert report["policy"]["accepted"] is False
