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

    assert result["public_label"] == "991"
    assert result["known"] is False


def test_unknown_text_type_is_preserved_losslessly():
    result = classify_sapl_type("Ato normativo futuro")

    assert result["public_label"] == "Ato normativo futuro"
    assert result["known"] is False


def test_pagination_url_must_remain_inside_configured_sapl_api():
    client = SaplAPIClient(base_url="https://sapl.test/api")
    assert client.validate_pagination_url("https://sapl.test/api/norma/?offset=50").endswith("offset=50")
    with pytest.raises(ValueError, match="escaped"):
        client.validate_pagination_url("https://attacker.test/api/norma/")
    client.close()
