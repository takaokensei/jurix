from datetime import date
from types import SimpleNamespace

from src.apps.legislation.serializers import serialize_citation_sources
from src.processing.answer_contract import build_answer_contract


def _temporal_source():
    norma = SimpleNamespace(
        id=31,
        tipo="Lei",
        numero="8205",
        ano=2026,
        pdf_url="https://sapl.natal.rn.leg.br/media/lei.pdf#:~:text=old-marker",
        sapl_url="https://sapl.natal.rn.leg.br/norma/9386/",
        sapl_id=9386,
        data_publicacao=date(2026, 4, 2),
        data_vigencia=date(2026, 4, 2),
        get_tipo_display_name=lambda: "Lei",
    )
    device = SimpleNamespace(
        id=81,
        norma=norma,
        texto="Redação historicamente projetada.",
        structural_key="a" * 64,
        get_full_identifier=lambda: "Art. 1º",
    )
    return {
        "dispositivo": device,
        "temporal_version": {
            "as_of": "2026-05-01",
            "legal_status": "in_force",
            "snapshot_id": 9,
            "version_hash": "b" * 64,
            "input_hash": "c" * 64,
            "policy": "normative-projection-v1",
            "provenance": {
                "base_document_id": "12345678-1234-5678-1234-567812345678",
                "base_extraction_id": 22,
                "event_id": 99,
                "effective_on": "2026-04-15",
                "secret": "must-not-serialize",
            },
        },
        "evidence_text": "Redação historicamente projetada.",
    }


def test_historical_citation_is_versioned_and_links_unmarked_official_base():
    source = serialize_citation_sources([_temporal_source()])[0]

    assert source["citation_id"] == f"jurix:norma:31:version:{'b' * 64}:device:{'a' * 64}"
    assert "projetada pelo Jurix em 2026-05-01" in source["citation_label"]
    assert source["temporal_version"] == {
        "as_of": "2026-05-01",
        "legal_status": "in_force",
        "version_hash": "b" * 64,
        "input_hash": "c" * 64,
        "policy": "normative-projection-v1",
        "source_document_id": "12345678-1234-5678-1234-567812345678",
        "effective_on": "2026-04-15",
    }
    assert "#:~:text=" not in source["pdf_url"]
    assert "secret" not in str(source["temporal_version"])


def test_versioned_answer_contract_preserves_citation_provenance_only():
    serialized_source = serialize_citation_sources([_temporal_source()])[0]
    contract = build_answer_contract(
        question="O que previa?",
        retrieval_query="O que previa?",
        filters={"as_of": date(2026, 5, 1)},
        provider="ollama",
        model="fixture",
        sources=[serialized_source],
        grounded=True,
    )

    row = contract["sources"][0]
    assert row["citation_id"] == serialized_source["citation_id"]
    assert row["temporal_version"]["version_hash"] == "b" * 64
    assert row["evidence_text"] == "Redação historicamente projetada."
    assert "secret" not in str(contract)


def test_graph_relation_is_whitelisted_in_contract():
    contract = build_answer_contract(
        question="Quem alterou?",
        retrieval_query="Quem alterou?",
        filters={},
        provider="ollama",
        model="fixture",
        sources=[
            {
                "id": 4,
                "graph_relation": {
                    "action": "REFERENCIA",
                    "role": "referencing_device",
                    "label": "Remissão, não alteração",
                    "quote": "cita a Lei nº 8.205/2026",
                    "api_key": "never-serialize",
                },
            }
        ],
    )

    relation = contract["sources"][0]["graph_relation"]
    assert relation["action"] == "REFERENCIA"
    assert relation["quote"] == "cita a Lei nº 8.205/2026"
    assert "api_key" not in str(contract)
