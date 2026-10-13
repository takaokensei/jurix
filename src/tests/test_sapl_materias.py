from __future__ import annotations

import pytest

from src.clients.sapl.sapl_client import SaplAPIClient


class FakeSaplMateriaClient(SaplAPIClient):
    def __init__(self, pages: dict[str, dict], first_pages: dict[str, dict]):
        self.base_url = "https://sapl.example.test/api"
        self.pages = pages
        self.first_pages = first_pages
        self.requests = []

    def _make_request(self, endpoint, params=None):
        self.requests.append((endpoint, params))
        return self.first_pages[endpoint]

    def _make_request_url(self, url):
        self.requests.append(("next", url))
        return self.pages[url]

    def validate_pagination_url(self, url):
        if not url.startswith("https://sapl.example.test/api/"):
            raise ValueError("unsafe url")
        return url


def _page(results, *, count=None, next_url=None):
    payload = {"results": results, "count": len(results) if count is None else count}
    if next_url:
        payload["next"] = next_url
    return payload


def test_fetches_exact_matter_by_installation_type_and_preserves_empty_outcome_fields():
    type_next = "https://sapl.example.test/api/materia/tipomaterialegislativa/?page=2"
    type_page1 = _page([{"id": 11, "descricao": "Emenda Aditiva"}], count=2, next_url=type_next)
    type_page2 = _page([{"id": 15, "descricao": "Emenda Supressiva"}], count=2)
    matter = {
        "id": 54885,
        "tipo": 15,
        "numero": 1,
        "ano": 2026,
        "em_tramitacao": False,
        "data_publicacao": None,
        "resultado": "",
        "anexadas": [],
        "ementa": "Suprime o art. 3º do PLC para preservar o art. 18 da LC 120/2010.",
    }
    client = FakeSaplMateriaClient(
        pages={type_next: type_page2},
        first_pages={
            "/materia/tipomaterialegislativa/": type_page1,
            "/materia/materialegislativa/": _page([matter]),
        },
    )

    result = client.fetch_materias_by_reference("Emenda Supressiva", "01", "2026")

    assert len(result) == 1
    assert result[0]["_jurix_materia_id"] == 54885
    assert result[0]["data_publicacao"] is None
    assert result[0]["resultado"] == ""
    assert result[0]["em_tramitacao"] is False
    assert client.requests[0] == (
        "/materia/tipomaterialegislativa/",
        {"limit": 100},
    )
    assert client.requests[-1] == (
        "/materia/materialegislativa/",
        {"limit": 100, "tipo": 15, "numero": 1, "ano": 2026},
    )


def test_fetch_matter_returns_empty_for_unknown_or_ambiguous_type():
    client = FakeSaplMateriaClient(
        pages={},
        first_pages={
            "/materia/tipomaterialegislativa/": _page(
                [
                    {"id": 4, "descricao": "Projeto de Lei Complementar"},
                    {"id": 9, "descricao": "Emenda Modificativa"},
                    {"id": 16, "descricao": "Projeto de Lei Complementar"},
                ]
            )
        },
    )

    assert client.fetch_materias_by_reference("Decreto", 9, 2026) == []
    assert client.fetch_materias_by_reference("Projeto de Lei Complementar", 9, 2026) == []


@pytest.mark.parametrize(
    ("tipo", "numero", "ano"),
    [("", 1, 2026), ("PLC", 0, 2026), ("PLC", 1, -1), ("PLC", True, 2026)],
)
def test_fetch_matter_rejects_invalid_reference(tipo, numero, ano):
    client = FakeSaplMateriaClient(pages={}, first_pages={})
    with pytest.raises(ValueError):
        client.fetch_materias_by_reference(tipo, numero, ano)


def test_public_materia_url_uses_configured_origin_and_validated_id():
    client = FakeSaplMateriaClient(pages={}, first_pages={})
    assert client.get_public_materia_url(54885) == "https://sapl.example.test/materia/54885"
    with pytest.raises(ValueError):
        client.get_public_materia_url("54885/../../admin")


def test_public_ementa_search_is_bounded_and_uses_configured_sapl_origin():
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "headers": {"id": "ID"},
                "results": [
                    {
                        "id": "48759",
                        "numero": "12",
                        "ano": "2025",
                        "tipo__descricao": "Projeto de Lei Complementar",
                        "ementa": "Altera o art. 59 da Lei Complementar nº 258/2024.",
                    }
                ],
            }

    class Session:
        calls = []

        def get(self, url, **kwargs):
            self.calls.append((url, kwargs))
            return Response()

    client = FakeSaplMateriaClient(pages={}, first_pages={})
    client.session = Session()
    client.timeout = 5
    client._request_count = 0
    rows = client.search_public_materias_by_ementa(" Art. 59  Lei Complementar 258 2024 ")

    assert rows[0]["id"] == "48759"
    url, kwargs = client.session.calls[0]
    assert url == "https://sapl.example.test/materia/pesquisar-materia"
    assert kwargs["params"] == {
        "format": "json",
        "ementa": "Art. 59 Lei Complementar 258 2024",
    }
    assert kwargs["allow_redirects"] is False
    assert kwargs["timeout"] == client.timeout


def test_public_ementa_search_rejects_broad_queries_and_redirect_results():
    client = FakeSaplMateriaClient(pages={}, first_pages={})
    with pytest.raises(ValueError, match="fora do limite"):
        client.search_public_materias_by_ementa("LC 258")

    class RedirectResponse:
        def raise_for_status(self):
            raise RuntimeError("unexpected redirect")

    class Session:
        def get(self, *_args, **_kwargs):
            return RedirectResponse()

    client.session = Session()
    client._request_count = 0
    client.timeout = 5
    with pytest.raises(RuntimeError, match="redirect"):
        client.search_public_materias_by_ementa("Art. 59 Lei Complementar 258 2024")


def test_fetch_materia_by_id_requires_exact_returned_id():
    class DetailClient(FakeSaplMateriaClient):
        def _make_request(self, endpoint, params=None):
            return {"id": 48759, "ementa": "PLC"}

    client = DetailClient(pages={}, first_pages={})
    assert client.fetch_materia_by_id(48759)["id"] == 48759
    with pytest.raises(ValueError, match="não corresponde"):
        client.fetch_materia_by_id(48760)


def test_matter_pagination_rejects_truncation_and_repeated_links():
    next_url = "https://sapl.example.test/api/materia/tipomaterialegislativa/?page=2"
    page = _page([{"id": 1, "descricao": "PLC"}], count=2, next_url=next_url)
    client = FakeSaplMateriaClient(
        pages={next_url: page},
        first_pages={"/materia/tipomaterialegislativa/": page},
    )

    with pytest.raises(ValueError, match="repetiu URL"):
        client._fetch_all_matter_pages(
            "/materia/tipomaterialegislativa/", params={}, max_pages=3
        )

    with pytest.raises(ValueError, match="limite de páginas"):
        client._fetch_all_matter_pages(
            "/materia/tipomaterialegislativa/", params={}, max_pages=1
        )


def test_batch_lookup_fetches_catalog_once_and_resolves_multiple_exact_references():
    responses = {
        "/materia/tipomaterialegislativa/": _page(
            [
                {"id": 4, "descricao": "Projeto de Lei Complementar"},
                {"id": 15, "descricao": "Emenda Supressiva"},
            ]
        ),
        "matter-9": _page([{"id": 54742, "tipo": 4, "numero": 9, "ano": 2026}]),
        "matter-1": _page([{"id": 54885, "tipo": 15, "numero": 1, "ano": 2026}]),
    }

    class BatchClient(FakeSaplMateriaClient):
        def _make_request(self, endpoint, params=None):
            self.requests.append((endpoint, params))
            if endpoint == "/materia/tipomaterialegislativa/":
                return responses[endpoint]
            return responses["matter-9" if params["tipo"] == 4 else "matter-1"]

    client = BatchClient(pages={}, first_pages={})
    result = client.fetch_materias_by_references(
        [
            {"tipo": "Projeto de Lei Complementar", "numero": 9, "ano": 2026},
            {"tipo": "Emenda Supressiva", "numero": 1, "ano": 2026},
        ]
    )

    assert len(client.requests) == 3
    assert result[("projeto de lei complementar", 9, 2026)][0]["_jurix_materia_id"] == 54742
    assert result[("emenda supressiva", 1, 2026)][0]["_jurix_materia_id"] == 54885


def test_batch_lookup_rejects_more_than_three_references():
    client = FakeSaplMateriaClient(pages={}, first_pages={})
    refs = [{"tipo": "PLC", "numero": n, "ano": 2026} for n in range(1, 5)]
    with pytest.raises(ValueError, match="três referências"):
        client.fetch_materias_by_references(refs)
