from src.apps.legislation.models import Norma
from src.apps.legislation.views import _norma_tipo_label
from src.apps.legislation.workspace_views import _tipo_label


def test_legacy_numeric_type_without_catalog_provenance_is_not_called_a_law():
    norma = Norma(tipo="5", numero="12", ano=2020, sapl_metadata={})

    assert norma.get_tipo_display_name() == "Tipo não identificado"
    assert norma.sapl_metadata == {}


def test_legacy_numeric_type_uses_its_preserved_catalog_label():
    norma = Norma(
        tipo="5",
        numero="12",
        ano=2020,
        sapl_metadata={
            "_jurix_type_catalog": {
                "raw_code": "5",
                "raw_label": "DECRETO LEGISLATIVO",
                "public_label": "Decreto Legislativo",
                "type_key": "decreto_legislativo",
                "known": True,
                "catalog_version": "natal-type-catalog-observed-2026-10-v1",
            },
        },
    )

    assert norma.get_tipo_display_name() == "Decreto Legislativo"
    assert norma.sapl_metadata["_jurix_type_catalog"]["raw_code"] == "5"


def test_explicit_executive_decree_label_is_not_confused_with_legislative_decree():
    executive = Norma(tipo="Decreto", numero="1", ano=2020)
    legislative = Norma(tipo="Decreto Legislativo", numero="1", ano=2020)

    assert executive.get_tipo_display_name() == "Decreto"
    assert legislative.get_tipo_display_name() == "Decreto Legislativo"


def test_unrecognized_textual_type_is_preserved_for_review():
    norma = Norma(tipo="Ato normativo experimental", numero="1", ano=2020)

    assert norma.get_tipo_display_name() == "Ato normativo experimental"


def test_norm_list_and_workspace_filters_use_the_same_conservative_type_resolver():
    assert _norma_tipo_label("3") == "Tipo não identificado"
    assert _tipo_label("5") == "Tipo não identificado"
    assert _norma_tipo_label("Decreto Legislativo") == "Decreto Legislativo"
    assert _tipo_label("Decreto") == "Decreto"
