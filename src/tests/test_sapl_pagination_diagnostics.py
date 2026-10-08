import pytest

from src.clients.sapl.sapl_client import SaplAPIClient


def test_fetch_normas_uses_current_api_endpoint(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    assert "/norma/normajuridica/" in client.NORMA_ENDPOINT


def test_public_url_is_not_the_api_route(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    assert client.get_public_norma_url(9386).endswith("/norma/9386")


def test_natal_nested_pagination_is_normalized_with_real_total(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    page = client._normalize_pagination_payload(
        {
            "count": 1,
            "results": [{"id": 9393}, {"id": 9391}],
            "pagination": {
                "links": {
                    "next": "http://sapl.natal.rn.leg.br/api/norma/normajuridica/?page=2",
                    "previous": None,
                },
                "page": 1,
                "next_page": 2,
                "previous_page": None,
                "start_index": 1,
                "end_index": 2,
                "total_entries": 9353,
                "total_pages": 4677,
            },
        }
    )

    assert page["count"] == 9353
    assert page["next"].startswith("http://")
    assert page["_jurix_pagination"] == {
        "page": 1,
        "total_pages": 4677,
        "total_entries": 9353,
        "start_index": 1,
        "end_index": 2,
    }
    assert client.validate_pagination_url(page["next"]) == (
        "https://sapl.natal.rn.leg.br/api/norma/normajuridica/?page=2"
    )


def test_pagination_normalizer_rejects_inconsistent_nested_page(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    with pytest.raises(ValueError, match="conflicts"):
        client._normalize_pagination_payload(
            {
                "results": [{"id": 1}],
                "pagination": {
                    "links": {"next": None, "previous": None},
                    "page": 1,
                    "next_page": None,
                    "previous_page": None,
                    "start_index": 1,
                    "end_index": 2,
                    "total_entries": 2,
                    "total_pages": 1,
                },
            }
        )


def test_pagination_url_upgrade_does_not_allow_foreign_host_or_path(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    with pytest.raises(ValueError, match="escaped"):
        client.validate_pagination_url(
            "http://attacker.example/api/norma/normajuridica/?page=2"
        )
    with pytest.raises(ValueError, match="escaped"):
        client.validate_pagination_url(
            "http://sapl.natal.rn.leg.br.evil.example/api/norma/normajuridica/?page=2"
        )
