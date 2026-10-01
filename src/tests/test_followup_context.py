from src.apps.legislation.api_search import _resolve_article_followup


def test_article_followup_keeps_user_intent_and_inherits_latest_unambiguous_norm():
    result = _resolve_article_followup(
        "E o artigo 7, quem financia as atividades?",
        "O que prevê o art. 8º da Lei nº 8206/2026?\nA resposta cita outra norma Lei 12/2020.",
    )
    assert result.startswith("E o artigo 7, quem financia as atividades?")
    assert "Lei nº 8206/2026" in result


def test_followup_with_explicit_new_norm_does_not_inherit_prior_norm():
    result = _resolve_article_followup(
        "E o art. 7º da Lei 9000/2025?", "Pergunta anterior sobre Lei 8206/2026"
    )
    assert result == "E o art. 7º da Lei 9000/2025?"


def test_yearless_or_multi_norm_prior_reference_is_not_used_as_context():
    assert _resolve_article_followup("E o art. 7º?", "A Lei 8206 talvez seja aplicável.") == (
        "E o art. 7º?"
    )
    assert (
        _resolve_article_followup("E o art. 7º?", "Compare a Lei 8206/2026 com a Lei 8207/2026.")
        == "E o art. 7º?"
    )
