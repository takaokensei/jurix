from src.processing.normative_query import classify_normative_query


def test_whole_norma_language_uses_overview_strategy():
    plan = classify_normative_query("O que prevê a Lei nº 8.206/2026?")

    assert plan.kind == "norma_overview"
    assert plan.reference.number == "8206"
    assert plan.reference.year == 2026


def test_explicit_article_takes_precedence_over_whole_norma_wording():
    plan = classify_normative_query("O que prevê o art. 8º da Lei nº 8.206/2026?")

    assert plan.kind == "provision"
    assert plan.reference.article == "8"


def test_bare_norma_reference_does_not_assume_user_wants_an_overview():
    assert classify_normative_query("Lei nº 8.206/2026").kind == "general"


def test_ambiguous_multiple_normas_do_not_force_whole_norma_retrieval():
    assert (
        classify_normative_query("O que prevê a Lei nº 8.206/2026 e a Lei nº 8.205/2026?").kind
        == "general"
    )


def test_abbreviated_complementary_law_overview_uses_broad_retrieval():
    plan = classify_normative_query("Quais são os principais eixos da LC nº 120/2010?")

    assert plan.kind == "norma_overview"
    assert plan.reference.identity == ("lei_complementar", "120", 2010)


def test_abbreviated_law_article_still_uses_provision_retrieval():
    plan = classify_normative_query("O que prevê o Art. 17 da LC nº 120/2010?")

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "120", 2010)
    assert plan.reference.article == "17"
