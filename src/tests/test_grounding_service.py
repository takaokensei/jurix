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
