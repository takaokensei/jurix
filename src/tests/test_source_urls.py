from types import SimpleNamespace

from django.test import override_settings

from src.apps.legislation.serializers import serialize_dispositivo_source
from src.apps.legislation.source_urls import (
    canonical_norma_url,
    canonical_sapl_url,
    public_source_url,
)


@override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api")
def test_legacy_sapl_ui_route_is_rewritten():
    assert canonical_sapl_url("https://sapl.natal.rn.leg.br/norma/normajuridica/9386/") == (
        "https://sapl.natal.rn.leg.br/norma/9386/"
    )


@override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api")
def test_id_only_url_is_built():
    assert canonical_sapl_url(sapl_id=9386) == "https://sapl.natal.rn.leg.br/norma/9386/"


@override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api")
def test_non_sapl_url_is_not_destroyed():
    value = "https://example.com/source/123"
    assert canonical_sapl_url(value, 9386) == value


@override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api")
def test_norma_object_uses_canonical_source():
    norma = SimpleNamespace(
        sapl_id=9386, sapl_url="https://sapl.natal.rn.leg.br/norma/normajuridica/9386/", pdf_url=""
    )
    assert canonical_norma_url(norma).endswith("/norma/9386/")
    assert public_source_url(norma).endswith("/norma/9386/")


@override_settings(SAPL_BASE_URL="https://sapl.natal.rn.leg.br/api")
def test_cached_source_legacy_sapl_route_is_canonicalized():
    serialized = serialize_dispositivo_source(
        {
            "norma_ref": "Lei nº 8206/2026",
            "sapl_url": "https://sapl.natal.rn.leg.br/norma/normajuridica/9387/",
            "similarity_score": 0.9,
        }
    )
    assert serialized["sapl_url"] == "https://sapl.natal.rn.leg.br/norma/9387/"
