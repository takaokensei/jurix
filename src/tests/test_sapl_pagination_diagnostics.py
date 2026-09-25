from src.clients.sapl.sapl_client import SaplAPIClient


def test_fetch_normas_uses_current_api_endpoint(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    assert "/norma/normajuridica/" in client.NORMA_ENDPOINT


def test_public_url_is_not_the_api_route(settings):
    settings.SAPL_BASE_URL = "https://sapl.natal.rn.leg.br/api"
    client = SaplAPIClient()
    assert client.get_public_norma_url(9386).endswith("/norma/9386/")
