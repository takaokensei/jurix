"""Regression tests for deterministic legal-answer grounding policy."""

from __future__ import annotations

from types import SimpleNamespace

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


def test_strict_grounding_rejects_both_polarity_mismatch_directions():
    assert not evaluate_strict_grounding(
        "A lei exige autorização.", [source("A lei não exige autorização.")]
    )["grounded"]
    assert not evaluate_strict_grounding(
        "A lei não exige autorização.", [source("A lei exige autorização.")]
    )["grounded"]
    assert evaluate_strict_grounding(
        "A lei não exige autorização.", [source("A lei não exige autorização.")]
    )["grounded"]


def test_strict_grounding_rejects_removed_conditions_and_strengthened_modality():
    assert not evaluate_strict_grounding(
        "O município concede apoio financeiro.",
        [source("O município pode conceder apoio financeiro se houver dotação.")],
    )["grounded"]
    assert not evaluate_strict_grounding(
        "O município deve conceder apoio financeiro.",
        [source("O município pode conceder apoio financeiro.")],
    )["grounded"]


def test_strict_grounding_ignores_reference_line_but_rejects_unsupported_bold_fact():
    report = evaluate_strict_grounding(
        "**Lei nº 8206/2026, Art. 7º**\n\n"
        "**Art. 7º autoriza despesa sem limite.**",
        [
            source(
                "A despesa fica condicionada à disponibilidade orçamentária.",
                "Lei 8206/2026",
                "Art. 7º",
            )
        ],
    )

    assert report["grounded"] is False
    assert len(report["claims"]) == 1
    assert "autoriza despesa sem limite" in report["failed_claims"][0]


def test_strict_grounding_binds_quantities_to_their_units_and_anchors():
    evidence = source("O prazo é de 10 dias e a multa é de 20 reais.")
    assert not evaluate_strict_grounding(
        "O prazo é de 20 dias e a multa é de 10 reais.", [evidence]
    )["grounded"]
    assert evaluate_strict_grounding("O prazo é de 10 dias e a multa é de 20 reais.", [evidence])[
        "grounded"
    ]


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
    assert claim["rejected_matches"]
    assert set(claim["rejected_matches"][0]) == {
        "evidence_index",
        "lexical_overlap",
        "lexical_ok",
        "numeric_ok",
        "unmatched_numbers",
        "negation_ok",
        "citation_ok",
        "certainty_ok",
    }
    assert "citation_refs" in claim


def _family_source(device_id, text, kind, article, norma_id=1, *, truncated=False):
    norma = SimpleNamespace(id=norma_id, numero="1234", ano=2025, tipo="Lei")
    dispositivo = SimpleNamespace(
        id=device_id,
        tipo=kind,
        numero="3º" if kind == "artigo" else str(device_id),
        ordem=device_id,
        norma_id=norma_id,
        norma=norma,
        dispositivo_pai=article,
        dispositivo_pai_id=getattr(article, "id", None),
        texto=text,
    )
    return {
        "dispositivo": dispositivo,
        "dispositivo_id": device_id,
        "citation_id": f"jurix:norma:{norma_id}:dispositivo:{device_id}",
        "norma_ref": "Lei 1234/2025",
        "identifier": "Art. 3º" if kind != "artigo" else "Art. 3º",
        "evidence_text": text,
        "snippet_truncated": truncated,
    }


@override_settings(RAG_STRICT_MIN_LEXICAL_OVERLAP=0.55)
def test_strict_grounding_aggregates_same_article_caput_and_direct_incisos():
    norma = SimpleNamespace(id=1, numero="1234", ano=2025, tipo="Lei")
    article = SimpleNamespace(
        id=30,
        tipo="artigo",
        numero="3º",
        norma_id=1,
        norma=norma,
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="O programa será executado pelo Município.",
    )
    sources = [
        _family_source(30, article.texto, "artigo", None),
        _family_source(31, "Promover formação continuada para os agentes comunitários.", "inciso", article),
        _family_source(32, "Ofertar acompanhamento psicossocial aos servidores.", "inciso", article),
        _family_source(33, "Realizar reconhecimento anual dos profissionais.", "inciso", article),
    ]

    report = evaluate_strict_grounding(
        "O programa prevê formação continuada, acompanhamento psicossocial e reconhecimento anual.",
        sources,
    )

    assert report["grounded"] is True
    aggregate = next(match for match in report["claims"][0]["matches"] if match.get("dispositivo_ids"))
    assert aggregate["dispositivo_ids"] == [30, 31, 32, 33]
    assert aggregate["citation_ids"] == [
        "jurix:norma:1:dispositivo:30",
        "jurix:norma:1:dispositivo:31",
        "jurix:norma:1:dispositivo:32",
        "jurix:norma:1:dispositivo:33",
    ]


def test_strict_grounding_never_composes_across_articles_or_normas():
    norma = SimpleNamespace(id=1, numero="1234", ano=2025, tipo="Lei")
    article_3 = SimpleNamespace(
        id=30,
        tipo="artigo",
        numero="3º",
        norma_id=1,
        norma=norma,
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="O programa será executado pelo Município.",
    )
    article_4 = SimpleNamespace(
        id=40,
        tipo="artigo",
        numero="4º",
        norma_id=1,
        norma=norma,
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="Ações de formação.",
    )
    other_norma_article = SimpleNamespace(
        id=50,
        tipo="artigo",
        numero="3º",
        norma_id=2,
        norma=SimpleNamespace(id=2, numero="9999", ano=2025, tipo="Lei"),
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="Ações de reconhecimento.",
    )
    sources = [
        _family_source(30, article_3.texto, "artigo", None),
        _family_source(41, "Promover formação continuada.", "inciso", article_4),
        _family_source(50, other_norma_article.texto, "artigo", None, norma_id=2),
        _family_source(51, "Realizar reconhecimento anual.", "inciso", other_norma_article, norma_id=2),
    ]

    report = evaluate_strict_grounding(
        "O programa promove formação continuada e reconhecimento anual.", sources
    )

    assert not any(
        len(match.get("dispositivo_ids", [])) > 1
        for claim in report["claims"]
        for match in claim["matches"]
    )


def test_truncated_device_is_not_used_to_create_composite_evidence():
    norma = SimpleNamespace(id=1, numero="1234", ano=2025, tipo="Lei")
    article = SimpleNamespace(
        id=30,
        tipo="artigo",
        numero="3º",
        norma_id=1,
        norma=norma,
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="O programa será executado pelo Município.",
    )
    sources = [
        _family_source(30, article.texto, "artigo", None),
        _family_source(31, "Promover formação continuada para os agentes", "inciso", article, truncated=True),
        _family_source(32, "Ofertar acompanhamento psicossocial aos servidores.", "inciso", article),
    ]

    report = evaluate_strict_grounding(
        "O programa prevê formação continuada e acompanhamento psicossocial.", sources
    )

    assert not any(
        len(match.get("dispositivo_ids", [])) > 1
        for claim in report["claims"]
        for match in claim["matches"]
    )


@override_settings(RAG_STRICT_MIN_LEXICAL_OVERLAP=0.45)
def test_whole_norm_overview_answer_with_supported_deadline_and_citation_is_grounded():
    from src.processing.rag_generation import validate_generated_answer

    norma = SimpleNamespace(id=1, numero="9001", ano=2020, tipo="Lei")
    article = SimpleNamespace(
        id=5,
        tipo="artigo",
        numero="5º",
        norma_id=1,
        norma=norma,
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="Art. 5º O prazo é de dez dias.",
    )
    evidence = {
        **_family_source(5, article.texto, "artigo", None),
        "dispositivo": article,
        "dispositivo_id": 5,
        # The evidence comes from the structured model (9001), while the LLM
        # may apply the conventional thousands separator (9.001).
        "norma_ref": "Lei nº 9001/2020",
        "identifier": "Art. 5º",
        "full_text": article.texto,
        # Context evidence excludes the external citation marker; its index is
        # validated against the source list, not against legal text.
        "evidence_text": "Lei nº 9001/2020, Art. 5º: Art. 5º O prazo é de dez dias.",
        "citation_index": 1,
        "citation_id": "jurix:norma:1:dispositivo:5",
    }

    result = validate_generated_answer(
        "A Lei nº 9.001/2020 prevê que o prazo é de dez dias, como estabelece o Art. 5º da referida lei [[1]].",
        [evidence],
    )

    assert result["grounded"] is True
    assert result["source_only"] is True
