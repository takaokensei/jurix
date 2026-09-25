from src.clients.sapl.sapl_client import SaplAPIClient


def test_fetch_all_normas_follows_next_links(monkeypatch):
    client = SaplAPIClient(base_url="https://example.test/api")
    pages = iter(
        [
            {
                "count": 2,
                "next": "https://example.test/api/norma/normajuridica/?offset=1",
                "results": [{"id": 1, "ano": 2026}],
            },
            {"count": 2, "next": None, "results": [{"id": 2, "ano": 2025}]},
        ]
    )
    monkeypatch.setattr(client, "fetch_normas_page", lambda **kwargs: next(pages))
    monkeypatch.setattr(client, "_make_request_url", lambda url: next(pages))
    try:
        result = client.fetch_all_normas(max_normas=2, page_size=50)
    finally:
        client.close()
    assert [item["id"] for item in result] == [1, 2]


def test_fetch_normas_for_corpus_deduplicates_year_and_type_partitions(monkeypatch):
    client = SaplAPIClient(base_url="https://example.test/api")
    calls = []

    def fake_page(**kwargs):
        calls.append(kwargs)
        if kwargs.get("tipo"):
            return {
                "count": 1,
                "next": None,
                "results": [
                    {
                        "id": 2,
                        "ano": kwargs["ano"],
                        "tipo": {"descricao": kwargs["tipo"]},
                    }
                ],
            }
        return {
            "count": 2,
            "next": None,
            "results": [
                {"id": 1, "ano": kwargs["ano"], "tipo": {"descricao": "LEI ORDINÁRIA"}},
                {"id": 2, "ano": kwargs["ano"], "tipo": {"descricao": "DECRETO"}},
            ],
        }

    monkeypatch.setattr(client, "fetch_normas_page", fake_page)
    try:
        result = client.fetch_normas_for_corpus(target=2, ano_inicio=2026, ano_fim=2026)
    finally:
        client.close()
    assert [item["id"] for item in result] == [1, 2]
    assert calls[0]["ano"] == 2026
