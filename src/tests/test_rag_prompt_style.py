from src.processing.rag_prompt import PROMPT_TEMPLATE, build_prompt


def test_prompt_requests_natural_prose_structured_citations_and_no_generated_links():
    prompt = build_prompt(
        "[[1]] Lei nº 8.206/2026, Art. 1º: institui o programa.", "O que prevê a lei?"
    )

    assert "Comece diretamente pela conclusão" in prompt
    assert "Não crie uma seção para cada artigo" in prompt
    assert "Em respostas curtas, com até três afirmações relacionadas, não use títulos" in prompt
    assert "limitação da evidência junto da explicação relevante" in prompt
    assert "os trechos consultados não permitem confirmá-lo" in prompt
    assert "lacuna de recuperação em afirmação sobre a norma inteira" in prompt
    assert "marcador correspondente" in prompt
    assert "não crie URLs" in prompt
    assert "[[1]] Lei nº 8.206/2026" in prompt
    assert "EXEMPLO CORRETO:" not in PROMPT_TEMPLATE
