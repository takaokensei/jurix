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


def test_unidentified_norm_discovery_preserves_an_explicit_article_target():
    plan = classify_normative_query(
        "Qual norma institui o Plano de Cargos e o que prevê o art. 18 sobre vencimento básico?"
    )

    assert plan.kind == "general"
    assert plan.article_targets == ("18",)


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


def test_general_question_about_how_a_norm_organizes_a_topic_uses_broad_topical_scope():
    plan = classify_normative_query(
        "Em linhas gerais, como a LC nº 258/2024 organiza o licenciamento de obras e "
        "quais três cautelas um procurador deve observar antes de aplicar esses excertos a um processo?"
    )

    assert plan.kind == "norma_overview"
    assert plan.broad_topical_scope is True
    assert plan.reference.identity == ("lei_complementar", "258", 2024)


def test_question_enumerating_procedures_in_a_named_norm_uses_broad_topical_scope():
    plan = classify_normative_query(
        "Quais etapas do licenciamento de obras a LC nº 258/2024 prevê? Faça uma síntese "
        "dos dispositivos pertinentes e diga quais documentos ou fatos do processo eu "
        "teria de conferir antes de orientar um caso concreto."
    )

    assert plan.kind == "norma_overview"
    assert plan.broad_topical_scope is True
    assert plan.reference.identity == ("lei_complementar", "258", 2024)


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


def test_mixed_plural_and_singular_article_mentions_keep_every_requested_device():
    plan = classify_normative_query(
        "Qual regra decorre dos Arts. 259 e 262 da Lei Complementar nº 258/2024? "
        "Cite também as revogações expressas do Art. 260."
    )

    assert plan.kind == "provision"
    assert plan.article_targets == ("259", "262", "260")


def test_qualified_article_in_plural_list_does_not_hide_following_article():
    plan = classify_normative_query(
        "O que estabelecem os arts. 260, inciso IV, e 262 da Lei Complementar nº 258/2024?"
    )

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "258", 2024)
    assert plan.article_targets == ("260", "262")


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


def test_relation_intent_detects_posterior_proposition_about_explicit_article():
    plan = classify_normative_query(
        "O texto do Art. 59 da LC nº 258/2024 é atual? Verifique se existe proposição "
        "posterior sobre esse artigo."
    )

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "258", 2024)
    assert plan.article_targets == ("59",)
    assert plan.relation_intent == "modification"


def test_relation_intent_detects_contextual_question_about_later_proposal():
    plan = classify_normative_query(
        "E existe alguma proposta posterior para alterar esse dispositivo? "
        "(contexto normativo: Lei Complementar nº 258/2024; "
        "dispositivo de referência: Art. 59º)"
    )

    assert plan.kind == "provision"
    assert plan.reference.identity == ("lei_complementar", "258", 2024)
    assert plan.article_targets == ("59",)
    assert plan.relation_intent == "modification"


def test_relation_intent_detects_plural_change_verbs_for_legislative_proposals():
    plan = classify_normative_query(
        "O PLC 9/2026 e a Emenda Supressiva 1/2026 alteraram ou revogaram "
        "o Art. 18 da Lei Complementar nº 120/2010?"
    )

    assert plan.kind == "provision"
    assert plan.relation_intent == "modification"
    assert plan.article_targets == ("18",)


def test_relation_intent_detects_whether_explicitly_named_article_is_currently_applicable():
    plan = classify_normative_query(
        "Posso tratar o Art. 21 da LC 55/2004 como vigente hoje, já que o Art. 260, IV, "
        "da LC 258/2024 revoga a LC 55/2004?"
    )

    assert plan.relation_intent == "modification"
    assert plan.article_targets == ("21", "260")
