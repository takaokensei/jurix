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
