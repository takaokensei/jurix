import pytest

from src.clients.sapl.sapl_client import SaplAPIClient
from src.clients.sapl.sapl_types import classify_sapl_type


def test_explicit_known_label_is_normalized_and_raw_catalog_values_remain_available():
    result = classify_sapl_type({"id": 77, "descricao": "LEI COMPLEMENTAR"})

    assert result["public_label"] == "Lei Complementar"
    assert result["raw_code"] == "77"
    assert result["raw_label"] == "LEI COMPLEMENTAR"
    assert result["known"] is True


def test_unknown_numeric_sapl_type_is_not_relabelled_as_ordinary_law():
    result = classify_sapl_type({"id": 991, "descricao": ""})

    assert result["public_label"] == "Tipo não identificado"
    assert result["known"] is False


def test_numeric_type_one_is_not_assumed_to_mean_law_without_catalog_label():
    result = classify_sapl_type({"id": 1, "descricao": ""})

    assert result["raw_code"] == "1"
    assert result["type_key"] is None
    assert result["public_label"] == "Tipo não identificado"
    assert result["known"] is False


def test_unknown_text_type_is_preserved_losslessly():
    result = classify_sapl_type("Ato normativo futuro")

    assert result["public_label"] == "Ato normativo futuro"
    assert result["known"] is False


@pytest.mark.parametrize(
    ("catalog_label", "type_key", "public_label", "series"),
    [
        (
            "LEI ORGÂNICA DO MUNICÍPIO",
            "lei_organica_municipio",
            "Lei Orgânica do Município",
            None,
        ),
        (
            "Lei de Diretrizes Orçamentárias",
            "lei_diretrizes_orcamentarias",
            "Lei de Diretrizes Orçamentárias",
            None,
        ),
        (
            "EMENDA À LEI ORGÂNICA DO MUNICÍPIO",
            "emenda_lei_organica",
            "Emenda à Lei Orgânica do Município",
            None,
        ),
        (
            "DECRETO LEGISLATIVO",
            "decreto_legislativo",
            "Decreto Legislativo",
            None,
        ),
        ("REGIMENTO INTERNO", "regimento_interno", "Regimento Interno", None),
        ("LEI ORDINÁRIA", "lei", "Lei", "municipal_lo"),
        ("LEI COMPLEMENTAR", "lei_complementar", "Lei Complementar", "municipal_lc"),
        ("LEI PROMULGADA", "lei_promulgada", "Lei Promulgada", "municipal_lp"),
        ("RESOLUÇÃO", "resolucao", "Resolução", None),
    ],
)
def test_observed_catalog_labels_are_typed_without_inventing_identity_series(
    catalog_label, type_key, public_label, series
):
    result = classify_sapl_type({"id": 999, "descricao": catalog_label})

    assert result["raw_code"] == "999"
    assert result["raw_label"] == catalog_label
    assert result["type_key"] == type_key
    assert result["public_label"] == public_label
    assert result["series"] == series
    assert result["known"] is True


@pytest.mark.parametrize(
    ("catalog_id", "catalog_label", "type_key"),
    [
        (5, "DECRETO LEGISLATIVO", "decreto_legislativo"),
        (6, "EMENDA À LEI ORGÂNICA DO MUNICÍPIO", "emenda_lei_organica"),
        (2, "LEI COMPLEMENTAR", "lei_complementar"),
        (7, "Lei de Diretrizes Orçamentárias", "lei_diretrizes_orcamentarias"),
        (1, "LEI ORDINÁRIA", "lei"),
        (10, "LEI ORGÂNICA DO MUNICÍPIO", "lei_organica_municipio"),
        (9, "LEI PROMULGADA", "lei_promulgada"),
        (11, "REGIMENTO INTERNO", "regimento_interno"),
        (3, "RESOLUÇÃO", "resolucao"),
    ],
)
def test_observed_natal_catalog_codes_are_preserved_as_installation_local_ids(
    catalog_id, catalog_label, type_key
):
    result = classify_sapl_type({"id": catalog_id, "descricao": catalog_label})

    assert result["raw_code"] == str(catalog_id)
    assert result["raw_label"] == catalog_label
    assert result["type_key"] == type_key
    assert result["known"] is True


def test_unknown_catalog_code_has_no_type_key_or_series():
    result = classify_sapl_type({"id": 812, "descricao": "TIPO NÃO OBSERVADO"})

    assert result["type_key"] is None
    assert result["series"] is None
    assert result["public_label"] == "TIPO NÃO OBSERVADO"
    assert result["known"] is False


def test_pagination_url_must_remain_inside_configured_sapl_api():
    client = SaplAPIClient(base_url="https://sapl.test/api")
    assert client.validate_pagination_url("https://sapl.test/api/norma/?offset=50").endswith("offset=50")
    with pytest.raises(ValueError, match="escaped"):
        client.validate_pagination_url("https://attacker.test/api/norma/")
    client.close()
