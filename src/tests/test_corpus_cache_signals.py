import pytest

from src.apps.legislation.models import Dispositivo, Norma
from src.apps.operations.models import CorpusRevision
from src.processing.corpus_write_boundary import corpus_write_boundary


@pytest.mark.django_db(transaction=True)
def test_norma_mutations_schedule_corpus_cache_invalidation(mocker):
    bump = mocker.patch("src.apps.legislation.signals._bump_after_commit")

    norma = Norma.objects.create(
        sapl_id=991003,
        tipo="1",
        numero="991003",
        ano=2026,
        status=Norma.Status.CONSOLIDATED,
        ementa="Norma de teste para invalidação do corpus.",
        texto_consolidado="Art. 1º Norma de teste.",
    )
    assert bump.call_count == 1

    norma.delete()
    assert bump.call_count == 2


@pytest.mark.django_db(transaction=True)
def test_dispositivo_mutations_schedule_corpus_cache_invalidation(mocker):
    bump = mocker.patch("src.apps.legislation.signals._bump_after_commit")
    norma = Norma.objects.create(
        sapl_id=991004,
        tipo="1",
        numero="991004",
        ano=2026,
        status=Norma.Status.CONSOLIDATED,
        ementa="Norma de teste para dispositivo.",
        texto_consolidado="Art. 1º Norma de teste.",
    )
    dispositivo = Dispositivo.objects.create(
        norma=norma,
        tipo="artigo",
        numero="1",
        texto="Norma de teste.",
        ordem=1,
    )
    assert bump.call_count == 2

    dispositivo.delete()
    assert bump.call_count == 3
    norma.delete()


@pytest.mark.django_db(transaction=True)
def test_fifty_norma_saves_recompute_corpus_once_inside_write_boundary(mocker):
    compute = mocker.patch(
        "src.processing.corpus_identity.compute_corpus_identity",
        return_value=(
            "f" * 64,
            {"norm_count": 50, "device_count": 0, "active_event_count": 0},
        ),
    )
    mocker.patch("src.processing.cache_service.get_cache_service")

    with corpus_write_boundary():
        for index in range(50):
            Norma.objects.create(
                tipo="Lei",
                numero=f"997{index:02d}",
                ano=2026,
            )

    assert compute.call_count == 1


@pytest.mark.django_db(transaction=True)
def test_rolled_back_write_boundary_does_not_recompute_or_invalidate(mocker):
    compute = mocker.patch("src.processing.corpus_identity.compute_corpus_identity")
    bump = mocker.patch("src.apps.legislation.signals._bump_after_commit")
    CorpusRevision.objects.update_or_create(
        key="municipal",
        defaults={"completeness": "complete", "digest": "d" * 64},
    )

    with pytest.raises(RuntimeError), corpus_write_boundary():
        Norma.objects.create(tipo="Lei", numero="99750", ano=2026)
        assert CorpusRevision.objects.get(key="municipal").completeness == "unknown"
        raise RuntimeError("rollback QA fixture")

    assert compute.call_count == 0
    assert bump.call_count == 0
    assert CorpusRevision.objects.get(key="municipal").completeness == "complete"


@pytest.mark.django_db(transaction=True)
def test_nested_boundary_savepoint_rollback_restores_dirty_state(mocker):
    bump = mocker.patch("src.apps.legislation.signals._bump_after_commit")

    with corpus_write_boundary():
        try:
            with corpus_write_boundary():
                Norma.objects.create(tipo="Lei", numero="99751", ano=2026)
                raise RuntimeError("inner savepoint QA fixture")
        except RuntimeError:
            pass

    assert bump.call_count == 0
