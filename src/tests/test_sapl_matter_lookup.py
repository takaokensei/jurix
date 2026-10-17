from datetime import datetime
from unittest.mock import patch

from django.test import override_settings
from django.utils import timezone

from src.processing.sapl_matter_lookup import (
    _extract_proposed_effect_clause,
    _extract_proposed_wording,
    lookup_explicit_matter_sources,
    lookup_related_matter_result,
    lookup_related_matter_sources,
    parse_explicit_matter_references,
)


def test_parser_only_accepts_explicit_typed_matter_references_and_deduplicates():
    refs = parse_explicit_matter_references(
        "Confira a Lei Complementar nº 120/2010, o PLC 9/2026 e a Emenda Supressiva nº 1/2026; "
        "também PLC 9/2026."
    )

    assert refs == [
        {"tipo": "Projeto de Lei Complementar", "numero": 9, "ano": 2026},
        {"tipo": "Emenda Supressiva", "numero": 1, "ano": 2026},
    ]


def test_lookup_is_disabled_without_qa_opt_in():
    with override_settings(SAPL_MATTER_LOOKUP_ENABLED=False), patch(
        "src.clients.sapl.sapl_client.SaplAPIClient"
    ) as client:
        assert lookup_explicit_matter_sources("PLC nº 9/2026") == []
        assert lookup_related_matter_result(
            "O que prevê o Art. 59 da LC 258/2024?", include_exact_article=True
        ).status == "disabled"
    client.assert_not_called()


def test_lookup_sends_only_typed_reference_and_keeps_empty_result_unknown():
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 5, "max_retries": 0}
            self.session = type("Session", (), {"close": lambda self: None})()

        def fetch_materias_by_references(self, references):
            assert references == [
                {"tipo": "Projeto de Lei Complementar", "numero": 9, "ano": 2026}
            ]
            return {
                ("projeto de lei complementar", 9, 2026): [
                    {
                        "_jurix_materia_id": 54742,
                        "ementa": "Dispõe sobre tema público.",
                        "em_tramitacao": False,
                        "resultado": "",
                        "data_publicacao": None,
                    }
                ]
            }

        def get_public_materia_url(self, matter_id):
            return f"https://sapl.example.test/materia/{matter_id}"

    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", FakeClient),
    ):
        rows = lookup_explicit_matter_sources("PLC 9/2026 sobre o tema X")

    assert rows[0]["citation_id"] == "sapl:materia:54742"
    assert rows[0]["source_kind"] == "sapl_legislative_matter"
    assert rows[0]["matter_status"] is False
    assert rows[0]["matter_result"] is None
    assert rows[0]["data_publicacao"] is None
    consulted_at = datetime.fromisoformat(rows[0]["consulted_at"])
    assert consulted_at.utcoffset() is not None
    expected_local_date = timezone.localtime(consulted_at).strftime("%d/%m/%Y")
    assert rows[0]["consulted_at_label"].startswith(expected_local_date)
    assert rows[0]["sapl_url"] == "https://sapl.example.test/materia/54742"
    assert "não é norma promulgada" in rows[0]["contribution"]


def test_explicit_wording_lookup_reads_only_same_origin_original_pdf_and_extracts_clause():
    pdf_url = "https://sapl.example.test/media/sapl/public/materialegislativa/2025/54742/original.pdf"

    class FakeClient:
        def __init__(self, **_kwargs):
            self.session = type("Session", (), {"close": lambda self: None})()

        def fetch_materias_by_references(self, _references):
            return {
                ("projeto de lei complementar", 9, 2026): [
                    {
                        "_jurix_materia_id": 54742,
                        "ementa": "Altera o art. 59 da LC 258/2024.",
                        "em_tramitacao": True,
                    }
                ]
            }

        def fetch_materia_by_id(self, matter_id):
            assert matter_id == 54742
            return {"id": 54742, "texto_original": pdf_url}

        def _validated_sapl_pdf_url(self, value):
            assert value == pdf_url
            return value

        def read_pdf_text(self, value, *, include_pages=False):
            assert value == pdf_url
            text = (
                "Projeto de Lei Complementar\nArt. 1º O art. 59 passa a vigorar com a seguinte redação:\n"
                "‘Art. 59. As inconformidades listadas no art. 51 serão tratadas como legalização.’\n"
                "Art. 2º Esta Lei entra em vigor."
            )
            if include_pages:
                return text, (
                    "Projeto de Lei Complementar\nArt. 1º O art. 59 passa a vigorar com a seguinte redação:",
                    "Página intermediária.",
                    "‘Art. 59. As inconformidades listadas no art. 51 serão tratadas como legalização.’",
                )
            return text

        def get_public_materia_url(self, matter_id):
            return f"https://sapl.example.test/materia/{matter_id}"

    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", FakeClient),
    ):
        rows = lookup_explicit_matter_sources(
            "Qual é a redação nova proposta pelo PLC 9/2026?"
        )

    assert len(rows) == 1
    assert rows[0]["_original_document"]["citation_id"] == "sapl:materia:54742:texto-original"
    assert rows[0]["_original_document"]["full_text"] == (
        "Art. 59. As inconformidades listadas no art. 51 serão tratadas como legalização."
    )
    assert rows[0]["_original_document"]["pdf_url"] == pdf_url
    assert rows[0]["_original_document"]["page"] == 3


def test_proposed_wording_extractor_requires_an_explicit_replacement_clause():
    assert _extract_proposed_wording(
        "Passa a vigorar com a seguinte redação: “Art. 59. Texto novo.”\n"
        "Art. 2º Esta Lei entra em vigor."
    ) == "Art. 59. Texto novo."
    assert _extract_proposed_wording("Art. 59. Texto genérico de uma exposição de motivos.") is None


def test_proposed_wording_stops_before_next_bill_article_and_pdf_boilerplate():
    extracted = _extract_proposed_wording(
        "Art. 1º O art. 59 passa a vigorar com a seguinte redação: "
        "‘Art. 59. As inconformidades listadas no art. 51, com existência comprovada "
        "na base cartográfica do ano de 2006, serão tratadas como legalização. ’ "
        "Art. 2º Esta Lei Complementar entra em vigor na data de sua publicação. "
        "Palácio Felipe Camarão, Natal, 12 de setembro de 2025. Assinado eletronicamente. "
        "https://www.natal.rn.gov.br"
    )

    assert extracted == (
        "Art. 59. As inconformidades listadas no art. 51, com existência comprovada "
        "na base cartográfica do ano de 2006, serão tratadas como legalização."
    )


def test_related_lookup_requires_one_explicit_article_and_modification_intent():
    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient") as client,
    ):
        assert lookup_related_matter_sources(
            "O que prevê a LC 258/2024?"
        ) == []
        assert lookup_related_matter_sources(
            "O que prevê o Art. 59 da LC nº 258/2024?"
        ) == []
        assert lookup_related_matter_sources(
            "O Art. 59 da LC 258/2024 foi alterado? E o Art. 60?"
        ) == []
        assert lookup_related_matter_result(
            "O que preveem os Arts. 59 e 60 da LC 258/2024?",
            include_exact_article=True,
        ).status == "not_applicable"
    client.assert_not_called()


def test_related_lookup_returns_only_verified_official_proposal_for_target_article():
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 5, "max_retries": 0}
            self.session = type("Session", (), {"close": lambda self: None})()
            self.searches = []

        def search_public_materias_by_ementa(self, expression):
            self.searches.append(expression)
            assert expression == "Art. 59 Lei Complementar 258 2024"
            return [
                {
                    "id": "48759",
                    "numero": "12",
                    "ano": "2025",
                    "tipo__descricao": "Projeto de Lei Complementar",
                    "ementa": "Altera o art. 59 da Lei Complementar nº 258, de 26 de dezembro de 2024.",
                },
                {
                    "id": "99999",
                    "tipo__descricao": "Parecer",
                    "ementa": "Altera o art. 59 da Lei Complementar nº 258/2024.",
                },
            ]

        def fetch_materia_by_id(self, matter_id):
            assert matter_id == 48759
            return {
                "id": 48759,
                "numero": 12,
                "ano": 2025,
                "tipo__descricao": "Projeto de Lei Complementar",
                "em_tramitacao": True,
                "resultado": "",
                "data_publicacao": None,
                "data_ultima_atualizacao": "2026-10-08T13:08:57-03:00",
                "ementa": "Altera o art. 59 da Lei Complementar nº 258, de 26 de dezembro de 2024.",
            }

        def get_public_materia_url(self, matter_id):
            return f"https://sapl.natal.rn.leg.br/materia/{matter_id}"

    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", FakeClient),
    ):
        rows = lookup_related_matter_sources(
            "O texto do Art. 59 da LC nº 258/2024 é atual? Verifique se existe "
            "proposição posterior sobre esse artigo."
        )
        exact_article_lookup = lookup_related_matter_result(
            "O que prevê o Art. 59 da LC nº 258/2024?",
            include_exact_article=True,
        )
        contextual_rows = lookup_related_matter_sources(
            "E existe alguma proposta posterior para alterar esse dispositivo? "
            "(contexto normativo: Lei Complementar nº 258/2024; "
            "dispositivo de referência: Art. 59º)"
        )

    assert len(rows) == 1
    assert rows[0]["citation_id"] == "sapl:materia:48759"
    assert rows[0]["relation_label"] == "Lei Complementar nº 258/2024, Art. 59"
    assert rows[0]["matter_status"] is True
    assert rows[0]["matter_updated_at"] == "2026-10-08T13:08:57-03:00"
    assert rows[0]["matter_updated_at_label"] == "08/10/2026 às 13:08"
    assert "não confirma efeito modificador" in rows[0]["contribution"]
    assert exact_article_lookup.status == "searched"
    assert [source["citation_id"] for source in exact_article_lookup.sources] == [
        "sapl:materia:48759"
    ]
    assert [row["citation_id"] for row in contextual_rows] == ["sapl:materia:48759"]


def test_whole_norm_followup_searches_exact_norm_mentions_without_guessing_article():
    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 5, "max_retries": 0}
            self.session = type("Session", (), {"close": lambda self: None})()

        def search_public_materias_by_ementa(self, expression):
            assert expression == "Lei 6859 2018"
            return [
                {
                    "id": "51001",
                    "tipo__descricao": "Projeto de Lei Ordinária",
                    "ementa": "Altera dispositivos da Lei nº 6.859, de 2018.",
                },
                {
                    "id": "51002",
                    "tipo__descricao": "Projeto de Lei Ordinária",
                    "ementa": "Altera dispositivos da Lei nº 6.858, de 2018.",
                },
            ]

        def fetch_materia_by_id(self, matter_id):
            assert matter_id == 51001
            return {
                "id": 51001,
                "numero": 40,
                "ano": 2025,
                "tipo__descricao": "Projeto de Lei Ordinária",
                "em_tramitacao": True,
                "ementa": "Altera dispositivos da Lei nº 6.859, de 2018.",
            }

        def get_public_materia_url(self, matter_id):
            return f"https://sapl.natal.rn.leg.br/materia/{matter_id}"

    question = (
        "E essa lei teve alterações posteriores? "
        "(contexto normativo: Lei nº 6859/2018)"
    )
    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", FakeClient),
    ):
        result = lookup_related_matter_result(question)

    assert result.status == "searched"
    assert [source["citation_id"] for source in result.sources] == ["sapl:materia:51001"]
    source = result.sources[0]
    assert source["match_kind"] == "official_ementa_explicit_norm_reference"
    assert source["relation_label"] == "Lei nº 6859/2018"
    assert "não confirma efeito modificador" in source["contribution"]


def test_related_lookup_fails_closed_when_ementa_does_not_match_exact_article():
    class FakeClient:
        def __init__(self, **_kwargs):
            self.session = type("Session", (), {"close": lambda self: None})()

        def search_public_materias_by_ementa(self, _expression):
            return [{
                "id": 48759,
                "numero": 12,
                "ano": 2025,
                "tipo__descricao": "Projeto de Lei Complementar",
                "ementa": "Altera o art. 60 da Lei Complementar nº 258/2024.",
            }]

        def fetch_materia_by_id(self, _matter_id):
            raise AssertionError("resultado não deveria ser consultado")

    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", FakeClient),
    ):
        rows = lookup_related_matter_sources(
            "O Art. 59 da LC nº 258/2024 foi alterado?"
        )
    assert rows == []


def test_related_lookup_distinguishes_completed_empty_search_from_sapl_outage():
    class EmptyClient:
        def __init__(self, **_kwargs):
            self.session = type("Session", (), {"close": lambda self: None})()

        def search_public_materias_by_ementa(self, _expression):
            return []

    class OfflineClient(EmptyClient):
        def search_public_materias_by_ementa(self, _expression):
            raise TimeoutError("public SAPL unavailable")

    question = "O Art. 59 da LC nº 258/2024 foi alterado?"
    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", EmptyClient),
    ):
        completed = lookup_related_matter_result(question)
    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", OfflineClient),
    ):
        unavailable = lookup_related_matter_result(question)

    assert completed.status == "searched"
    assert completed.sources == ()
    assert unavailable.status == "unavailable"
    assert unavailable.sources == ()


def test_extract_proposed_revocation_requires_exact_norm_and_article_in_same_bill_article():
    bill_text = (
        "Art. 1º A matriz remuneratória da Lei Complementar nº 120, de 2010, fica atualizada.\n"
        "Art. 3º Ficam revogados o art. 18 da Lei Complementar nº 120, de 3 de dezembro de 2010, "
        "e outras disposições em contrário.\n"
        "Art. 4º Esta Lei Complementar entra em vigor na data de sua publicação."
    )

    clause = _extract_proposed_effect_clause(
        bill_text,
        type_key="lei_complementar",
        number="120",
        year=2010,
        article="18",
    )
    unrelated_article = _extract_proposed_effect_clause(
        bill_text,
        type_key="lei_complementar",
        number="120",
        year=2010,
        article="26",
    )

    assert clause is not None
    assert clause.startswith("Art. 3º Ficam revogados")
    assert "art. 18 da Lei Complementar nº 120" in clause
    assert unrelated_article is None


def test_related_article_lookup_follows_explicit_amendment_to_parent_bill_and_original_pdf():
    amendment_ementa = (
        "Suprime o art. 3º do Projeto de Lei Complementar nº 09/2026, "
        "para preservar o art. 18 da Lei Complementar nº 120, de 3 de dezembro de 2010."
    )
    bill_ementa = "Altera o Anexo I da Lei Complementar nº 120, de 3 de dezembro de 2010."
    bill_pdf_url = (
        "https://sapl.natal.rn.leg.br/media/sapl/public/materialegislativa/2026/54742/original.pdf"
    )
    bill_text = (
        "Art. 1º A matriz da LC nº 120/2010 fica atualizada.\n"
        "Art. 3º Ficam revogados o art. 18 da Lei Complementar nº 120, de 3 de dezembro de 2010, "
        "e outras disposições em contrário.\n"
        "Art. 4º Esta Lei Complementar entra em vigor na data de sua publicação."
    )

    class FakeClient:
        def __init__(self, **kwargs):
            assert kwargs == {"timeout": 5, "max_retries": 0}
            self.session = type("Session", (), {"close": lambda self: None})()

        @staticmethod
        def _normalize_matter_type_label(value):
            return " ".join(str(value).casefold().split())

        def search_public_materias_by_ementa(self, expression):
            assert expression == "Art. 18 Lei Complementar 120 2010"
            return [{
                "id": 54885,
                "numero": 1,
                "ano": 2026,
                "tipo__descricao": "Emenda Supressiva",
                "ementa": amendment_ementa,
            }]

        def fetch_materia_by_id(self, matter_id):
            if matter_id == 54885:
                return {
                    "id": 54885,
                    "numero": 1,
                    "ano": 2026,
                    "tipo__descricao": "Emenda Supressiva",
                    "em_tramitacao": False,
                    "ementa": amendment_ementa,
                }
            assert matter_id == 54742
            return {
                "id": 54742,
                "numero": 9,
                "ano": 2026,
                "tipo__descricao": "Projeto de Lei Complementar",
                "em_tramitacao": False,
                "resultado": "",
                "data_publicacao": None,
                "ementa": bill_ementa,
                "data_ultima_atualizacao": "2026-05-19T08:25:10-03:00",
                "texto_original": bill_pdf_url,
            }

        def fetch_materias_by_references(self, references):
            assert references == [
                {"tipo": "Projeto de Lei Complementar", "numero": 9, "ano": 2026}
            ]
            return {
                ("projeto de lei complementar", 9, 2026): [{
                    "_jurix_materia_id": 54742,
                    "numero": 9,
                    "ano": 2026,
                    "tipo__descricao": "Projeto de Lei Complementar",
                    "ementa": bill_ementa,
                }]
            }

        def get_public_materia_url(self, matter_id):
            return f"https://sapl.natal.rn.leg.br/materia/{matter_id}"

        def _validated_sapl_pdf_url(self, value):
            assert value == bill_pdf_url
            return value

        def read_pdf_text(self, value, *, include_pages=False):
            assert value == bill_pdf_url
            if include_pages:
                return bill_text, (bill_text,)
            return bill_text

    question = (
        "O art. 18 da Lei Complementar nº 120/2010 foi alterado ou revogado? "
        "Identifique o ato modificador e compare a redação anterior e posterior."
    )
    with (
        override_settings(SAPL_MATTER_LOOKUP_ENABLED=True),
        patch("src.clients.sapl.sapl_client.SaplAPIClient", FakeClient),
    ):
        result = lookup_related_matter_result(question)

    by_citation = {source["citation_id"]: source for source in result.sources}
    assert result.status == "searched"
    assert set(by_citation) == {
        "sapl:materia:54885",
        "sapl:materia:54742",
        "sapl:materia:54742:texto-original:art-3",
    }
    assert by_citation["sapl:materia:54885"]["matter_status"] is False
    assert by_citation["sapl:materia:54742"]["data_publicacao"] is None
    proposed_clause = by_citation["sapl:materia:54742:texto-original:art-3"]
    assert proposed_clause["source_kind"] == "sapl_matter_original_pdf"
    assert proposed_clause["page"] == 1
    assert "art. 18 da Lei Complementar nº 120" in proposed_clause["full_text"]
    assert "não é norma promulgada" in proposed_clause["contribution"]
