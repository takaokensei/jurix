from src.processing.citation_enrichment import attach_grounded_citations
from src.processing.rag_generation import validate_generated_answer


def test_adds_structured_citation_to_each_supported_markdown_claim():
    answer = (
        "O plano cria uma carreira para os servidores da saúde.\n\n"
        "- A lei prevê gratificações para categorias específicas.\n"
        "- A tabela remuneratória é revista anualmente em março."
    )
    sources = [
        {"citation_id": "device-1", "citation_index": 1},
        {"citation_id": "device-2", "citation_index": 2},
        {"citation_id": "device-3", "citation_index": 3},
    ]
    grounding = {
        "grounded": True,
        "claims": [
            {
                "claim": "O plano cria uma carreira para os servidores da saúde.",
                "supported": True,
                "matches": [
                    {"citation_ids": ["device-1"], "lexical_overlap": 0.8, "evidence_index": 0}
                ],
            },
            {
                "claim": "- A lei prevê gratificações para categorias específicas.",
                "supported": True,
                "matches": [
                    {"citation_ids": ["device-2"], "lexical_overlap": 0.9, "evidence_index": 1}
                ],
            },
            {
                "claim": "- A tabela remuneratória é revista anualmente em março.",
                "supported": True,
                "matches": [
                    {"citation_ids": ["device-3"], "lexical_overlap": 0.95, "evidence_index": 2}
                ],
            },
        ],
    }

    result = attach_grounded_citations(answer, grounding, sources)

    assert result == (
        "O plano cria uma carreira para os servidores da saúde. [[1]]\n\n"
        "- A lei prevê gratificações para categorias específicas. [[2]]\n"
        "- A tabela remuneratória é revista anualmente em março. [[3]]"
    )


def test_preserves_existing_citation_and_uses_best_supported_evidence():
    answer = "O prazo é de dez dias. [[2]]"
    grounding = {
        "grounded": True,
        "claims": [
            {
                "claim": "O prazo é de dez dias. [[2]]",
                "supported": True,
                "matches": [
                    {"citation_ids": ["weaker"], "lexical_overlap": 0.62, "evidence_index": 0},
                    {"citation_ids": ["best"], "lexical_overlap": 0.94, "evidence_index": 1},
                ],
            }
        ],
    }
    sources = [
        {"citation_id": "weaker", "citation_index": 1},
        {"citation_id": "best", "citation_index": 2},
    ]

    assert attach_grounded_citations(answer, grounding, sources) == answer


def test_does_not_attach_citations_to_unvalidated_or_unmatched_claims():
    answer = "O benefício se aplica aos servidores efetivos."
    grounding = {
        "grounded": False,
        "claims": [
            {"claim": answer, "supported": False, "matches": []},
        ],
    }

    assert attach_grounded_citations(answer, grounding, []) == answer


def test_maps_legacy_evidence_order_when_sources_have_no_citation_index():
    answer = "O prazo é de dez dias."
    grounding = {
        "grounded": True,
        "claims": [
            {
                "claim": answer,
                "supported": True,
                "matches": [
                    {"citation_ids": ["legacy-source"], "lexical_overlap": 0.9, "evidence_index": 0}
                ],
            }
        ],
    }

    assert attach_grounded_citations(
        answer,
        grounding,
        [{"citation_id": "legacy-source"}],
    ) == "O prazo é de dez dias. [[1]]"


def test_answer_validation_returns_citations_for_supported_uncited_claims():
    answer = "A lei cria um programa municipal de apoio."
    sources = [{"citation_id": "device-1", "citation_index": 1}]

    result = validate_generated_answer(
        answer,
        sources,
        citation_policy=lambda _answer, _sources: True,
        absence_policy=lambda _answer, _sources: False,
        grounding_policy=lambda _answer, _sources: {
            "grounded": True,
            "claims": [
                {
                    "claim": answer,
                    "supported": True,
                    "matches": [
                        {
                            "citation_ids": ["device-1"],
                            "lexical_overlap": 1.0,
                            "evidence_index": 0,
                        }
                    ],
                }
            ],
        },
    )

    assert result["grounded"] is True
    assert result["answer"] == "A lei cria um programa municipal de apoio. [[1]]"
