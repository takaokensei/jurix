from types import SimpleNamespace

from src.processing.grounding_service import evaluate_grounding, extract_claims


def test_grounding_maps_claim_to_the_specific_device():
    answer = "O prazo para recurso é de quinze dias, conforme a Lei 123/2020."
    sources = [
        {
            "dispositivo_id": 1532,
            "norma": "Lei 123/2020",
            "identifier": "Art. 5º",
            "text": "O prazo para recurso será de quinze dias.",
        },
        {
            "dispositivo_id": 1533,
            "norma": "Lei 999/2021",
            "identifier": "Art. 9º",
            "text": "O prazo para resposta será de trinta dias.",
        },
    ]

    result = evaluate_grounding(answer, sources)

    assert result["grounded"] is True
    assert result["claims"][0]["supported"] is True
    assert result["claims"][0]["evidence"][0]["dispositivo_id"] == 1532


def test_grounding_rejects_wrong_number_word_even_with_the_same_norm():
    answer = "O prazo para recurso é de trinta dias, conforme a Lei 123/2020."
    sources = [
        {
            "dispositivo_id": 1532,
            "norma": "Lei 123/2020",
            "identifier": "Art. 5º",
            "text": "O prazo para recurso será de quinze dias.",
        }
    ]

    result = evaluate_grounding(answer, sources)

    assert result["grounded"] is False
    assert "trinta" in result["failed_claims"][0]


def test_claim_extraction_is_deterministic():
    claims = extract_claims("Primeira afirmação. Segunda afirmação!")
    assert [item.text for item in claims] == [
        "Primeira afirmação.",
        "Segunda afirmação!",
    ]


def test_reference_only_markdown_line_is_not_a_factual_claim():
    claims = extract_claims(
        "**Lei nº 8206/2026, Art. 7º**\n\n"
        "O art. 7º condiciona a despesa à disponibilidade orçamentária."
    )

    assert len(claims) == 1
    assert "condiciona a despesa" in claims[0].text


def test_bold_legal_fact_remains_a_claim_and_must_be_grounded():
    answer = "**Art. 7º autoriza despesa sem limite.**"
    sources = [
        {
            "dispositivo_id": 7,
            "norma": "Lei 8206/2026",
            "identifier": "Art. 7º",
            "text": "A despesa fica condicionada à disponibilidade orçamentária.",
        }
    ]

    result = evaluate_grounding(answer, sources)

    assert len(result["claims"]) == 1
    assert result["grounded"] is False


def test_grounding_service_composes_only_verified_article_family_sources():
    norma = SimpleNamespace(id=1, numero="1234", ano=2025, tipo="Lei")
    article = SimpleNamespace(
        id=30,
        tipo="artigo",
        numero="3º",
        norma_id=1,
        norma=norma,
        dispositivo_pai=None,
        dispositivo_pai_id=None,
        texto="O programa será executado pelo Município.",
    )
    sources = [
        {
            "dispositivo": article,
            "dispositivo_id": 30,
            "citation_id": "jurix:norma:1:dispositivo:30",
            "norma_ref": "Lei 1234/2025",
            "identifier": "Art. 3º",
            "evidence_text": article.texto,
        }
    ]
    for device_id, text in (
        (31, "Promover formação continuada para os agentes comunitários."),
        (32, "Ofertar acompanhamento psicossocial aos servidores."),
        (33, "Realizar reconhecimento anual dos profissionais."),
    ):
        device = SimpleNamespace(
            id=device_id,
            tipo="inciso",
            numero="I",
            norma_id=1,
            norma=norma,
            dispositivo_pai=article,
            dispositivo_pai_id=article.id,
            texto=text,
        )
        sources.append(
            {
                "dispositivo": device,
                "dispositivo_id": device_id,
                "citation_id": f"jurix:norma:1:dispositivo:{device_id}",
                "norma_ref": "Lei 1234/2025",
                "identifier": f"Art. 3º, inciso {device_id - 30}",
                "evidence_text": text,
            }
        )

    result = evaluate_grounding(
        "O programa prevê formação continuada, acompanhamento psicossocial e reconhecimento anual.",
        sources,
    )

    assert result["grounded"] is True
    aggregate = next(
        evidence
        for evidence in result["claims"][0]["evidence"]
        if len(evidence["dispositivo_ids"]) > 1
    )
    assert aggregate["dispositivo_ids"] == (30, 31, 32, 33)
    assert aggregate["citation_ids"] == (
        "jurix:norma:1:dispositivo:30",
        "jurix:norma:1:dispositivo:31",
        "jurix:norma:1:dispositivo:32",
        "jurix:norma:1:dispositivo:33",
    )
