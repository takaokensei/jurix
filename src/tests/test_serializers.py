from src.apps.legislation.serializers import serialize_dispositivo_source


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
