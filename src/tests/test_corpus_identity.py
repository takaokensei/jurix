import pytest

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.operations.models import CorpusRevision
from src.processing.corpus_identity import get_corpus_revision, refresh_corpus_revision


@pytest.mark.django_db
def test_durable_corpus_revision_is_shared_and_changes_with_current_records():
    initial = refresh_corpus_revision()
    same = refresh_corpus_revision()
    assert same["revision"] == initial["revision"]
    assert same["digest"] == initial["digest"]
    assert same["changed"] is False

    norma = Norma.objects.create(tipo="Lei", numero="99401", ano=2026)
    device = Dispositivo.objects.create(
        norma=norma, tipo="artigo", numero="1º", texto="Dispositivo.", ordem=1
    )
    changed = refresh_corpus_revision()
    assert changed["changed"] is True
    assert changed["revision"] == initial["revision"] + 1
    assert changed["norm_count"] == initial["norm_count"] + 1
    assert changed["device_count"] == initial["device_count"] + 1

    source_norma = Norma.objects.create(tipo="Lei", numero="99402", ano=2026)
    source = Dispositivo.objects.create(
        norma=source_norma, tipo="artigo", numero="1º", texto="Revoga o art. 1º.", ordem=1
    )
    EventoAlteracao.objects.create(
        dispositivo_fonte=source,
        acao="REVOGA",
        target_text="art. 1º",
        norma_alvo=norma,
        dispositivo_alvo=device,
        validado=False,
    )
    with_event = refresh_corpus_revision()
    assert with_event["active_event_count"] == changed["active_event_count"] + 1
    assert with_event["digest"] != changed["digest"]

    durable_read = get_corpus_revision()
    assert durable_read is not None
    assert durable_read["revision"] == with_event["revision"]
    assert durable_read["digest"] == with_event["digest"]
    assert durable_read["completeness"] == "unknown"


@pytest.mark.django_db(transaction=True)
def test_rolled_back_norma_does_not_change_durable_corpus_identity():
    from django.db import transaction

    before = refresh_corpus_revision()
    with pytest.raises(RuntimeError), transaction.atomic():
        Norma.objects.create(tipo="Lei", numero="99403", ano=2026)
        raise RuntimeError("rollback fixture")

    after = refresh_corpus_revision()
    assert after["digest"] == before["digest"]
    assert after["revision"] == before["revision"]


@pytest.mark.django_db
def test_corpus_revision_is_recreated_when_the_seed_row_is_missing():
    CorpusRevision.objects.filter(key="municipal").delete()

    revision = refresh_corpus_revision()

    assert revision["revision"] == 0
    assert revision["changed"] is False
    assert CorpusRevision.objects.filter(key="municipal").exists()
