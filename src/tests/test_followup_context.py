from src.apps.legislation.api_search import _grounded_source_context, _resolve_article_followup


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


def test_proposed_wording_followup_inherits_one_explicit_matter_reference():
    result = _resolve_article_followup(
        "Qual é a redação nova proposta para o art. 59?",
        "O Art. 59 da Lei Complementar nº 258/2024 é afetado pelo Projeto de Lei "
        "Complementar nº 12/2025?",
    )
    assert result.endswith(
        "(contexto da matéria legislativa: Projeto de Lei Complementar nº 12/2025)"
    )


def test_proposed_wording_followup_does_not_choose_between_multiple_matters():
    question = "Qual é o texto proposto?"
    history = "Compare o PLC 12/2025 com o PLC 13/2025."
    assert _resolve_article_followup(question, history) == question


def test_followup_about_a_later_proposal_inherits_one_norm_and_device():
    result = _resolve_article_followup(
        "E existe alguma proposta posterior para alterar esse dispositivo?",
        "O que prevê o art. 59 da Lei Complementar nº 258/2024?",
    )

    assert result.endswith(
        "(contexto normativo: Lei Complementar nº 258/2024; "
        "dispositivo de referência: Art. 59º)"
    )


def test_followup_about_a_later_proposal_does_not_inherit_ambiguous_norms():
    question = "E existe alguma proposta posterior para alterar esse dispositivo?"
    history = "Compare o Art. 59 da LC 258/2024 com o Art. 4º da Lei 9000/2025."

    assert _resolve_article_followup(question, history) == question


def test_yearless_or_multi_norm_prior_reference_is_not_used_as_context():
    assert _resolve_article_followup("E o art. 7º?", "A Lei 8206 talvez seja aplicável.") == (
        "E o art. 7º?"
    )
    assert (
        _resolve_article_followup("E o art. 7º?", "Compare a Lei 8206/2026 com a Lei 8207/2026.")
        == "E o art. 7º?"
    )


def test_short_elliptical_followup_inherits_nearest_unambiguous_norm():
    result = _resolve_article_followup(
        "E qual artigo trata do vencimento básico?",
        "O que prevê o art. 19 da Lei Complementar nº 120/2010?\n"
        "Pergunta anterior sobre a Lei nº 7.138/2021.",
    )
    assert result == (
        "E qual artigo trata do vencimento básico? "
        "(contexto normativo: Lei Complementar nº 120/2010)"
    )


def test_bare_wh_followup_inherits_nearest_unambiguous_norm():
    result = _resolve_article_followup(
        "Qual é o piso do vencimento básico?",
        "O que prevê a Lei Complementar nº 120/2010?",
    )
    assert result == (
        "Qual é o piso do vencimento básico? "
        "(contexto normativo: Lei Complementar nº 120/2010)"
    )


def test_followup_referring_to_prior_evidence_inherits_its_unambiguous_norm():
    question = (
        "Com esses trechos, posso concluir que o processo deve necessariamente ser "
        "analisado pela lei antiga?"
    )
    result = _resolve_article_followup(
        question,
        "Em um caso hipotético, pedido de licenciamento sob a Lei Complementar nº 258/2024; "
        "considere os Arts. 262 e 266.",
    )

    assert result == question + " (contexto normativo: Lei Complementar nº 258/2024)"


def test_followup_referring_to_prior_evidence_does_not_choose_between_norms():
    question = "Diante desses dispositivos, qual lei se aplica?"
    history = "Compare a LC 258/2024 com a LC 55/2004 neste processo."

    assert _resolve_article_followup(question, history) == question


def test_effective_date_followup_inherits_nearest_unambiguous_norm():
    result = _resolve_article_followup(
        "E quando a lei passou a vigorar?",
        "O que dispõe o Art. 262 da Lei Complementar nº 258/2024?",
    )
    assert result == (
        "E quando a lei passou a vigorar? "
        "(contexto normativo: Lei Complementar nº 258/2024)"
    )

    result = _resolve_article_followup(
        "Em que data entrou em vigor?",
        "O que dispõe a Lei Complementar nº 258/2024?",
    )
    assert result == (
        "Em que data entrou em vigor? "
        "(contexto normativo: Lei Complementar nº 258/2024)"
    )


def test_demonstrative_law_followup_inherits_the_law_from_the_previous_turn():
    result = _resolve_article_followup(
        "E essa lei teve alterações posteriores? Diga o que os PDFs e o SAPL consultados comprovam.",
        "Lei nº 6859/2018, Art. 2º\n"
        "O que dispõe o Art. 2º da Lei nº 6.859/2018?",
    )

    assert result.endswith("(contexto normativo: Lei nº 6859/2018)")


def test_bare_wh_followup_does_not_inherit_ambiguous_norms():
    question = "Qual é o piso do vencimento básico?"
    history = "Compare a Lei Complementar nº 120/2010 com a Lei nº 7138/2021."
    assert _resolve_article_followup(question, history) == question


def test_explanatory_followup_keeps_the_norm_named_in_the_prior_turn():
    result = _resolve_article_followup(
        "Com base no trecho citado, explique em linguagem simples o que significa a estrutura de cargos.",
        "O que prevê o art. 19 da Lei Complementar nº 120/2010?",
    )
    assert result.endswith(
        "(contexto normativo: Lei Complementar nº 120/2010; dispositivo de referência: Art. 19º)"
    )
    assert "Decreto" not in result


def test_followup_about_value_mentioned_in_prior_article_inherits_device_scope():
    result = _resolve_article_followup(
        "E qual é o valor mínimo mencionado?",
        "O que prevê o art. 18 da Lei Complementar nº 120/2010?",
    )
    assert result.endswith(
        "(contexto normativo: Lei Complementar nº 120/2010; dispositivo de referência: Art. 18º)"
    )


def test_followup_inherits_article_from_latest_grounded_source_hint():
    result = _resolve_article_followup(
        "E qual é o valor mencionado?",
        "Decreto nº 7.795/2005, Art. 1º\n"
        "O que estabelece o Decreto nº 7.795/2005 sobre o crédito suplementar?",
    )
    assert result.endswith(
        "(contexto normativo: Decreto nº 7795/2005; dispositivo de referência: Art. 1º)"
    )


def test_municipal_decree_followup_inherits_the_exact_document_identity():
    result = _resolve_article_followup(
        "E o artigo 2?",
        "O que prevê o Art. 1º do Decreto municipal nº 7.795/2005?",
    )
    assert result == (
        "E o artigo 2? "
        "(contexto normativo: Decreto nº 7795/2005)"
    )


def test_appendix_followup_inherits_the_nearest_unambiguous_norm_without_article_scope():
    result = _resolve_article_followup(
        "E o que consta no Adendo I?",
        "O que estabelece o art. 1º do Decreto municipal nº 7.795/2005?",
    )

    assert result == (
        "E o que consta no Adendo I? "
        "(contexto normativo: Decreto nº 7795/2005)"
    )
    assert "dispositivo de referência" not in result


def test_grounded_source_context_keeps_one_article_but_not_an_arbitrary_multi_article():
    single = _grounded_source_context([
        {
            "norma_ref": "Decreto nº 7.795/2005",
            "dispositivo_ref": "Art. 1º",
        }
    ])
    multiple = _grounded_source_context([
        {"norma_ref": "Lei Complementar nº 120/2010", "dispositivo_ref": "Art. 17"},
        {"norma_ref": "Lei Complementar nº 120/2010", "dispositivo_ref": "Art. 18"},
    ])
    ambiguous = _grounded_source_context([
        {"norma_ref": "Lei nº 9001/2020", "dispositivo_ref": "Art. 1º"},
        {"norma_ref": "Lei nº 9002/2021", "dispositivo_ref": "Art. 2º"},
    ])

    assert single == ["Decreto nº 7795/2005, Art. 1º"]
    assert multiple == ["Lei Complementar nº 120/2010"]
    assert ambiguous == []


def test_unreferenced_followup_does_not_inherit_an_article_number():
    result = _resolve_article_followup(
        "E qual é o valor mínimo legal?",
        "O que prevê o art. 18 da Lei Complementar nº 120/2010?",
    )
    assert result.endswith("(contexto normativo: Lei Complementar nº 120/2010)")
    assert "dispositivo de referência" not in result


def test_explanatory_followup_does_not_inherit_an_ambiguous_prior_reference():
    result = _resolve_article_followup(
        "Com base no trecho citado, explique isso.",
        "Compare a Lei nº 8206/2026 com a Lei nº 8207/2026.",
    )
    assert result == "Com base no trecho citado, explique isso."


def test_elliptical_followup_does_not_guess_across_ambiguous_nearest_turn():
    result = _resolve_article_followup(
        "E qual norma se aplica?",
        "Compare a Lei nº 8206/2026 com a Lei nº 8207/2026.\n"
        "O que prevê a Lei nº 8206/2026?",
    )
    assert result == "E qual norma se aplica?"


def test_elliptical_followup_without_prior_norm_stays_unchanged():
    assert (
        _resolve_article_followup("E qual artigo trata disso?", "Qual é a regra geral?")
        == "E qual artigo trata disso?"
    )


def test_elliptical_followup_can_retain_norm_scope_after_several_short_turns():
    history = "\n".join(
        ["E qual artigo fala disso?"] * 8
        + ["O que prevê o art. 19 da Lei Complementar nº 120/2010?"]
    )
    result = _resolve_article_followup("E qual artigo trata do vencimento básico?", history)
    assert result.endswith("contexto normativo: Lei Complementar nº 120/2010)")


def test_followup_referring_to_two_prior_devices_inherits_only_that_same_norm_and_device_set():
    result = _resolve_article_followup(
        "Qual dos dois dispositivos trata do salário mínimo?",
        "Na Lei Complementar nº 120/2010, explique os Arts. 17 e 18.",
    )
    assert result == (
        "Qual dos dois dispositivos trata do salário mínimo? "
        "(contexto normativo: Lei Complementar nº 120/2010; "
        "dispositivos de referência: Arts. 17 e 18)"
    )


def test_followup_to_multiple_articles_does_not_inherit_device_set_for_whole_norm_question():
    result = _resolve_article_followup(
        "Qual é a vigência da norma?",
        "Na Lei Complementar nº 120/2010, explique os Arts. 17 e 18.",
    )
    assert result == (
        "Qual é a vigência da norma? "
        "(contexto normativo: Lei Complementar nº 120/2010)"
    )
