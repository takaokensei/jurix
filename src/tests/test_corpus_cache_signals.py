import pytest

from src.apps.legislation.models import Dispositivo, Norma


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
