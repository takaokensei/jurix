from datetime import date
from types import SimpleNamespace

from src.apps.legislation.serializers import (
    serialize_citation_sources,
    serialize_dispositivo_source,
)


def test_source_serializer_survives_broken_norma_relation():
    class BrokenDispositivo:
        id = 42
        texto = "Trecho preservado"

        @property
        def norma(self):
            raise RuntimeError("relação indisponível")

        def get_full_identifier(self):
            return "Art. 1º"

    result = serialize_dispositivo_source({"dispositivo": BrokenDispositivo()})

    assert result["id"] == 42
    assert result["full_text"] == "Trecho preservado"
    assert result["source_url"] is None
    assert result["temporal_status"] == "data_indeterminada"


def test_cached_source_coerces_legacy_non_string_text():
    result = serialize_dispositivo_source({"id": 7, "text": 12345})

    assert result["full_text"] == "12345"
    assert result["text"] == "12345"


def test_cached_source_builds_readable_stable_citation_identity():
    result = serialize_citation_sources(
        [
            {
                "id": 81,
                "norma_id": 22,
                "norma_ref": "Lei nº 8.206/2026",
                "dispositivo_ref": "Art. 2º > Inciso I",
                "text": "Regra do inciso.",
            }
        ]
    )[0]

    assert result["citation_id"] == "jurix:norma:22:dispositivo:81"
    assert result["citation_index"] == 1
    assert result["citation_label"] == "Lei nº 8.206/2026, Art. 2º, inciso I"


def test_explicit_reference_match_kind_survives_cached_source_serialization():
    result = serialize_dispositivo_source(
        {
            "id": 7,
            "norma_ref": "Lei nº 8.206/2026",
            "dispositivo_ref": "Art. 1º",
            "text": "Texto exato.",
            "match_kind": "explicit_reference",
            "similarity_score": 0,
        }
    )

    assert result["match_kind"] == "explicit_reference"
    assert result["similarity_score"] == 0


def test_missing_match_kind_remains_compatible_with_legacy_sources():
    result = serialize_dispositivo_source({"id": 8, "text": "Fonte antiga."})

    assert result["match_kind"] is None


def test_explicit_reference_match_kind_survives_model_source_serialization():
    norma = SimpleNamespace(
        id=4,
        tipo="Lei",
        numero="8206",
        ano=2026,
        pdf_url="https://sapl.natal.rn.leg.br/test.pdf",
        sapl_url=None,
        sapl_id=4,
        data_publicacao=date(2026, 1, 1),
        data_vigencia=None,
        get_tipo_display_name=lambda: "Lei",
    )
    dispositivo = SimpleNamespace(
        id=9,
        norma=norma,
        texto="Texto legal.",
        get_full_identifier=lambda: "Art. 1º",
    )

    result = serialize_dispositivo_source(
        {"dispositivo": dispositivo, "match_kind": "explicit_reference"}
    )

    assert result["match_kind"] == "explicit_reference"
    assert result["dispositivo_id"] == 9
