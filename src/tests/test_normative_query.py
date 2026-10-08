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


def test_natural_question_about_themes_treated_by_a_norm_is_an_overview():
    plan = classify_normative_query(
        "Quais são os principais temas tratados na Lei Complementar nº 120/2010? "
        "Faça uma síntese com base no PDF e indique se a cobertura é parcial."
    )

    assert plan.kind == "norma_overview"
    assert plan.reference.identity == ("lei_complementar", "120", 2010)


def test_abbreviated_law_article_still_uses_provision_retrieval():
    plan = classify_normative_query("O que prevê o Art. 17 da LC nº 120/2010?")

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "120", 2010)
    assert plan.reference.article == "17"


def test_plural_article_targets_do_not_turn_a_specific_question_into_a_whole_law_overview():
    plan = classify_normative_query(
        "Explique a diferença entre as regras dos arts. 17 e 18 da Lei Complementar nº 120/2010."
    )

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "120", 2010)
    assert plan.article_targets == ("17", "18")


def test_relation_intent_detects_norma_as_subject_of_amendment_question():
    plan = classify_normative_query(
        "A Lei nº 9002/2021 altera algum dispositivo da Lei nº 9001/2020?"
    )

    assert plan.relation_intent == "modification"


def test_relation_intent_detects_question_comparing_amendment_and_reference():
    plan = classify_normative_query(
        "Qual é a relação normativa entre a Lei nº 9002/2021 e a Lei nº 9001/2020? "
        "Diferencie alteração confirmada de referência."
    )

    assert plan.relation_intent == "mixed"


def test_relation_intent_keeps_explicit_reference_separate_from_modification():
    plan = classify_normative_query(
        "A Lei nº 9002/2021 faz referência à Lei nº 9001/2020?"
    )

    assert plan.relation_intent == "reference"


def test_relation_intent_detects_whether_provisions_were_changed_or_revoked():
    plan = classify_normative_query(
        "Na Lei Complementar nº 267/2025, quais dispositivos tratam de cargos, "
        "vencimentos e progressão? O acervo registra alterações ou revogações "
        "posteriores desses dispositivos?"
    )

    assert plan.kind == "general"
    assert plan.reference.identity == ("lei_complementar", "267", 2025)
    assert plan.relation_intent == "modification"


def test_relation_intent_detects_explicit_article_with_change_question():
    plan = classify_normative_query(
        "O art. 18 da Lei Complementar nº 120/2010 foi alterado ou revogado?"
    )

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "120", 2010)
    assert plan.relation_intent == "modification"
