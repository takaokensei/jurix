from datetime import date
from types import SimpleNamespace

import pytest

from src.processing.temporal_scope import TemporalScope, parse_iso_date, temporal_status


def test_parse_iso_date_accepts_calendar_dates():
    assert parse_iso_date("2026-01-30", "as_of") == date(2026, 1, 30)


def test_parse_iso_date_rejects_invalid_values():
    with pytest.raises(ValueError):
        parse_iso_date("30/01/2026", "as_of")


def test_scope_rejects_future_publication():
    scope = TemporalScope(as_of=date(2025, 1, 1))
    assert not scope.contains_publication(date(2025, 2, 1))


def test_unfiltered_scope_accepts_unknown_publication():
    scope = TemporalScope()
    assert scope.contains_publication(None)


def test_explicit_historical_scope_excludes_unknown_publication_or_effective_dates():
    from src.processing.temporal_scope import matches_temporal_scope

    scope = TemporalScope(as_of=date(2025, 1, 1))
    unknown_publication = SimpleNamespace(
        id=1, data_publicacao=None, data_vigencia=date(2024, 1, 1)
    )
    unknown_effective = SimpleNamespace(id=2, data_publicacao=date(2024, 1, 1), data_vigencia=None)
    assert not matches_temporal_scope(unknown_publication, scope)
    assert not matches_temporal_scope(unknown_effective, scope)


def test_temporal_status_for_vacatio():
    norma = SimpleNamespace(data_publicacao=date(2025, 1, 1), data_vigencia=date(2025, 2, 1), id=1)
    assert temporal_status(norma, as_of=date(2025, 1, 15)) == "vacatio_legis"


@pytest.mark.django_db
def test_temporal_status_requires_registered_effective_date():
    from src.apps.legislation.models import Norma

    norma = Norma.objects.create(
        tipo="Lei", numero="901", ano=2024, data_publicacao=date(2024, 1, 1)
    )
    assert temporal_status(norma, as_of=date(2025, 1, 1)) == "data_indeterminada"


@pytest.mark.django_db
def test_unvalidated_and_partial_revocations_do_not_mark_the_whole_norma_revoked():
    from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma

    target = Norma.objects.create(
        tipo="Lei",
        numero="902",
        ano=2024,
        data_publicacao=date(2024, 1, 1),
        data_vigencia=date(2024, 1, 1),
    )
    amending = Norma.objects.create(
        tipo="Lei",
        numero="903",
        ano=2024,
        data_publicacao=date(2024, 2, 1),
        data_vigencia=date(2024, 2, 1),
    )
    target_device = Dispositivo.objects.create(
        norma=target, tipo="artigo", numero="1º", texto="Artigo um", ordem=1
    )
    source_device = Dispositivo.objects.create(
        norma=amending, tipo="artigo", numero="1º", texto="Revoga art. 1º", ordem=1
    )
    event = EventoAlteracao.objects.create(
        dispositivo_fonte=source_device,
        dispositivo_alvo=target_device,
        norma_alvo=target,
        acao="REVOGA",
        target_text="Art. 1º",
        validado=False,
    )

    assert temporal_status(target, as_of=date(2025, 1, 1)) == "vigente"
    event.validado = True
    event.save(update_fields=["validado"])
    assert temporal_status(target, as_of=date(2025, 1, 1)) == "parcialmente_revogada"

    event.dispositivo_alvo = None
    event.save(update_fields=["dispositivo_alvo"])
    assert temporal_status(target, as_of=date(2025, 1, 1)) == "revogada"
