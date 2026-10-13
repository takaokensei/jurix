from src.processing.conversation_titles import build_conversation_title


def test_title_uses_a_topic_only_when_its_words_are_present_in_final_sources():
    title = build_conversation_title(
        "O que prevê a Lei nº 8205/2026 sobre o Dia da Educação Popular a ser celebrado em abril?",
        [
            {
                "norma_ref": "Lei nº 8205/2026",
                "full_text": "Fica instituído o Dia da Educação Popular.",
            }
        ],
    )

    assert title == "Educação Popular — Lei nº 8.205/2026"


def test_unsupported_topic_falls_back_to_norm_and_article_without_hallucination():
    title = build_conversation_title(
        "O que prevê o art. 8º da Lei nº 8206/2026 sobre animais abandonados?",
        [
            {
                "norma_ref": "Lei nº 8206/2026",
                "full_text": "Esta Lei entra em vigor na data de sua publicação.",
            }
        ],
    )

    assert title == "Art. 8º — Lei nº 8.206/2026"


def test_title_is_bounded_and_uses_only_a_few_evidence_words():
    title = build_conversation_title(
        "Fale sobre proteção animal, cadastro, serviços públicos e fiscalização no município.",
        [{"text": "Proteção animal e cadastro municipal."}],
    )

    assert title == "Proteção animal cadastro"
    assert len(title) <= 70


def test_title_has_neutral_fallback_when_there_is_no_supported_context():
    assert build_conversation_title("Pergunta genérica?", []) == "Pesquisa jurídica"


def test_title_keeps_formatted_law_reference_when_no_evidence_was_returned():
    assert (
        build_conversation_title("O que prevê a Lei nº 8.206/2026?", [])
        == "Lei nº 8.206/2026"
    )


def test_title_keeps_article_and_law_reference_without_inventing_a_topic():
    assert (
        build_conversation_title("O que prevê o Art. 7º da Lei nº 8.206/2026?", [])
        == "Art. 7º — Lei nº 8.206/2026"
    )


def test_title_distinguishes_a_legislative_proposal_from_a_promulgated_norm():
    title = build_conversation_title(
        "Qual é a redação proposta no art. 59 do PLC 12/2025?",
        [],
    )

    assert title == "Art. 59º — PLC nº 12/2025"


def test_title_recognizes_full_complementary_bill_name_without_calling_it_a_law():
    title = build_conversation_title(
        "O que diz o Art. 59 do Projeto de Lei Complementar nº 12/2025?",
        [],
    )

    assert title == "Art. 59º — PLC nº 12/2025"


def test_title_does_not_use_a_negative_answer_prefix_as_the_topic():
    title = build_conversation_title(
        "Não encontrei evidências suficientes. E o artigo 7 da Lei Complementar nº 120/2010?",
        [],
    )

    assert title == "Art. 7º — Lei Complementar nº 120/2010"


def test_title_ignores_instruction_words_that_also_appear_in_legal_evidence():
    sources = [
        {
            "norma_ref": "Lei Complementar nº 120/2010",
            "full_text": "Cada unidade deve observar as regras correspondentes desta Lei. Os artigos e dispositivos definem os temas principais.",
        }
    ]

    title = build_conversation_title(
        "Resuma os principais temas da Lei Complementar nº 120/2010 e vincule cada afirmação aos artigos correspondentes.",
        sources,
    )

    assert title == "Lei Complementar nº 120/2010"


def test_title_ignores_procedural_question_words_and_keeps_the_retrieved_topic():
    title = build_conversation_title(
        "Em linhas gerais, como a LC nº 258/2024 organiza o licenciamento de obras e "
        "quais três cautelas um procurador deve observar antes de aplicar esses excertos a um processo?",
        [
            {
                "norma_ref": "Lei Complementar nº 258/2024",
                "full_text": (
                    "O licenciamento de obras e esses procedimentos dependem da "
                    "documentação técnica pertinente."
                ),
            }
        ],
    )

    assert title == "Licenciamento obras — Lei Complementar nº 258/2024"
