from django.test import override_settings

from src.processing.strict_grounding import evaluate_strict_grounding

CASES = [
    ("O prazo é 10 dias.", "O prazo é 10 dias.", True),
    ("O prazo é 15 dias.", "O prazo é 10 dias.", False),
    ("É proibida a conduta.", "É permitida a conduta.", False),
    ("É permitida a conduta.", "É permitida a conduta somente em caso específico.", False),
    ("A Lei 10/2025 exige cadastro.", "A Lei 10/2025 exige cadastro.", True),
    ("A Lei 11/2025 exige cadastro.", "A Lei 10/2025 exige cadastro.", False),
]


@override_settings(RAG_STRICT_MIN_LEXICAL_OVERLAP=0.55)
def test_adversarial_claim_matrix():
    for claim, evidence, expected in CASES:
        report = evaluate_strict_grounding(
            claim, [{"text": evidence, "norma_ref": "", "identifier": "", "id": 1}]
        )
        assert report["grounded"] is expected, claim
