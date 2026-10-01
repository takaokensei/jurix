from io import StringIO

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command

from src.processing.device_hierarchy import validate_hierarchy


def test_parsed_hierarchy_rejects_missing_parents_self_links_and_cycles():
    valid = [
        {"index": 1, "parent_index": None},
        {"index": 2, "parent_index": 1},
        {"index": 3, "parent_index": 2},
    ]
    validate_hierarchy(valid)

    for invalid in (
        [{"index": 1, "parent_index": 2}],
        [{"index": 1, "parent_index": 1}],
        [
            {"index": 1, "parent_index": 2},
            {"index": 2, "parent_index": 1},
        ],
    ):
        with pytest.raises(ValueError):
            validate_hierarchy(invalid)


@pytest.mark.django_db
def test_device_save_rejects_self_and_cross_norma_parent_links():
    from src.apps.legislation.models import Dispositivo, Norma

    norma = Norma.objects.create(tipo="Lei", numero="901", ano=2026)
    other = Norma.objects.create(tipo="Lei", numero="902", ano=2026)
    parent = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Artigo", ordem=1
    )
    child = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="I",
        texto="Inciso",
        ordem=2,
        dispositivo_pai=parent,
    )
    child.dispositivo_pai = child
    with pytest.raises(ValidationError, match="si mesmo"):
        child.save()

    external_parent = Dispositivo.objects.create(
        norma=other, tipo="artigo", numero="1º", texto="Outro", ordem=1
    )
    child.dispositivo_pai = external_parent
    with pytest.raises(ValidationError, match="mesma norma"):
        child.save()


@pytest.mark.django_db
def test_corrupt_cycle_has_bounded_display_and_read_only_integrity_diagnostic():
    from src.apps.legislation.models import Dispositivo, Norma

    norma = Norma.objects.create(tipo="Lei", numero="903", ano=2026)
    first = Dispositivo.objects.create(norma=norma, tipo="artigo", numero="1º", texto="Um", ordem=1)
    second = Dispositivo.objects.create(
        norma=norma,
        tipo="inciso",
        numero="I",
        texto="Dois",
        ordem=2,
        dispositivo_pai=first,
    )
    Dispositivo.objects.filter(pk=first.pk).update(dispositivo_pai=second)
    first.refresh_from_db()

    assert "ciclo hierárquico detectado" in first.get_caminho_completo()
    assert first.get_nivel() <= 64
    output = StringIO()
    call_command("check_corpus_integrity_v2", stdout=output, stderr=output)
    assert "Device parent cycles" in output.getvalue()
