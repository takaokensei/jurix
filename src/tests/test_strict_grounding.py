"""Regression tests for deterministic legal-answer grounding policy."""

from __future__ import annotations

from django.test import override_settings

from src.processing.strict_grounding import evaluate_strict_grounding


def source(text: str, norma: str = "Lei 1234/2025", identifier: str = "Art. 1") -> dict:
    return {
        "text": text,
        "norma_ref": norma,
        "identifier": identifier,
        "dispositivo_id": identifier,
    }


@override_settings(RAG_STRICT_MIN_LEXICAL_OVERLAP=0.55)
def test_strict_grounding_accepts_cited_numeric_claim():
    report = evaluate_strict_grounding(
        "A Lei 1234/2025 exige 3 documentos.",
        [source("A Lei 1234/2025 exige 3 documentos.")],
    )
    assert report["grounded"] is True
    assert report["score"] == 1.0


@override_settings(RAG_STRICT_MIN_LEXICAL_OVERLAP=0.55)
def test_strict_grounding_rejects_new_number():
    report = evaluate_strict_grounding(
        "A Lei 1234/2025 exige 9 documentos.",
        [source("A Lei 1234/2025 exige 3 documentos.")],
    )
    assert report["grounded"] is False
    assert report["failed_claims"]


def test_strict_grounding_rejects_negation_mismatch():
    report = evaluate_strict_grounding(
        "A lei não exige autorização.",
        [source("A lei exige autorização.")],
    )
    assert report["grounded"] is False


def test_strict_grounding_rejects_unknown_citation():
    report = evaluate_strict_grounding(
        "A Lei 9999/2025 exige cadastro.",
        [source("A Lei 1234/2025 exige cadastro.")],
    )
    assert report["grounded"] is False


def test_strict_grounding_can_require_two_sources():
    report = evaluate_strict_grounding(
        "A Lei 1234/2025 exige cadastro. O Decreto 88/2025 define o prazo.",
        [
            source("A Lei 1234/2025 exige cadastro.", "Lei 1234/2025", "Art. 1"),
            source("O Decreto 88/2025 define o prazo.", "Decreto 88/2025", "Art. 2"),
        ],
        require_source_diversity=True,
    )
    assert report["grounded"] is True
    assert report["matched_source_count"] == 2


def test_strict_grounding_reports_exact_failure_reason_shape():
    report = evaluate_strict_grounding(
        "A regra é sempre aplicável.",
        [source("A regra pode ser aplicável em situações específicas.")],
    )
    claim = report["claims"][0]
    assert claim["supported"] is False
    assert "matches" in claim
    assert "citation_refs" in claim
