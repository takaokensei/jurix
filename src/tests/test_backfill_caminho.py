"""
Migration 0011 backfills Dispositivo.caminho / nivel for rows created before 0010
(audit P1.4). Rows without a materialized path forced get_caminho_completo() to
walk the parent chain with one query per level.
"""
import importlib

import pytest
from django.apps import apps as global_apps
from django.db import connection
from django.test.utils import CaptureQueriesContext

from src.apps.legislation.models import Dispositivo, Norma

pytestmark = pytest.mark.django_db

migration = importlib.import_module("src.apps.legislation.migrations.0011_backfill_dispositivo_caminho")


@pytest.fixture
def norma():
    return Norma.objects.create(tipo="Lei", numero="1", ano=2020)


def _mk(norma, tipo, numero, ordem, pai=None, **extra):
    return Dispositivo.objects.create(
        norma=norma, tipo=tipo, numero=numero, texto="t", ordem=ordem, dispositivo_pai=pai, **extra
    )


def _legacy_tree(norma):
    """A tree as it existed before 0010: caminho='' and nivel=0 everywhere."""
    art = _mk(norma, "artigo", "1º", 1)
    par = _mk(norma, "paragrafo", "2º", 2, art)
    inc = _mk(norma, "inciso", "III", 3, par)
    ali = _mk(norma, "alinea", "b", 4, inc)
    itm = _mk(norma, "item", "1", 5, ali)
    return art, par, inc, ali, itm


def test_backfill_fills_path_and_level_from_the_parent_chain(norma):
    art, par, inc, ali, itm = _legacy_tree(norma)

    migration.backfill_caminho_nivel(global_apps, None)

    for d in (art, par, inc, ali, itm):
        d.refresh_from_db()
    assert art.caminho == "Art. 1º" and art.nivel == 0
    assert par.caminho == "Art. 1º > § 2º" and par.nivel == 1
    assert inc.caminho == "Art. 1º > § 2º > Inciso III" and inc.nivel == 2
    assert ali.caminho == "Art. 1º > § 2º > Inciso III > Alínea b" and ali.nivel == 3
    assert itm.caminho == "Art. 1º > § 2º > Inciso III > Alínea b > Item 1" and itm.nivel == 4


def test_backfill_matches_what_the_parser_materializes(norma):
    """Same labels as LegalTextParser.build_hierarchy, so old and new rows are consistent."""
    from src.processing.legal_parser import LegalTextParser

    hier = LegalTextParser.build_hierarchy(LegalTextParser.parse_legal_text(
        "Art. 1º Requisitos:\nI - docs:\na) pessoais:\n1. identidade;\nParágrafo único. Vale."
    ))
    by_key = {(e["tipo"], e["numero"]): e for e in hier}

    art = _mk(norma, "artigo", "1º", 1)
    inc = _mk(norma, "inciso", "I", 2, art)
    ali = _mk(norma, "alinea", "a", 3, inc)
    itm = _mk(norma, "item", "1", 4, ali)
    pu = _mk(norma, "paragrafo", "único", 5, art)
    migration.backfill_caminho_nivel(global_apps, None)

    for d in (art, inc, ali, itm, pu):
        d.refresh_from_db()
        parsed = by_key[(d.tipo, d.numero)]
        assert (d.caminho, d.nivel) == (parsed["caminho"], parsed["nivel"]), d.tipo


def test_backfill_leaves_already_materialized_rows_untouched(norma):
    art = _mk(norma, "artigo", "1º", 1, caminho="CUSTOM", nivel=7)
    migration.backfill_caminho_nivel(global_apps, None)
    art.refresh_from_db()
    assert (art.caminho, art.nivel) == ("CUSTOM", 7)


def test_backfill_does_not_touch_updated_at(norma):
    art = _mk(norma, "artigo", "1º", 1)
    before = Dispositivo.objects.get(pk=art.pk).updated_at
    migration.backfill_caminho_nivel(global_apps, None)
    assert Dispositivo.objects.get(pk=art.pk).updated_at == before


def test_backfill_survives_a_parent_cycle(norma):
    a = _mk(norma, "artigo", "1º", 1)
    b = _mk(norma, "paragrafo", "1º", 2, a)
    Dispositivo.objects.filter(pk=a.pk).update(dispositivo_pai=b)   # corrupt data: a <-> b
    migration.backfill_caminho_nivel(global_apps, None)             # must terminate
    a.refresh_from_db()
    assert a.caminho


def test_backfill_query_count_does_not_grow_with_tree_size():
    def run(n_nodes):
        n = Norma.objects.create(tipo="Lei", numero=f"q{n_nodes}", ano=2020)
        parent = None
        for i in range(n_nodes):                       # a deep chain: worst case for per-level queries
            tipo = "artigo" if parent is None else "inciso"
            parent = _mk(n, tipo, str(i + 1), i + 1, parent)
        with CaptureQueriesContext(connection) as ctx:
            migration.backfill_caminho_nivel(global_apps, None)
        return len(ctx)

    Dispositivo.objects.all().delete()
    assert run(5) == run(50)


def test_backfilled_path_removes_the_per_level_queries():
    norma = Norma.objects.create(tipo="Lei", numero="2", ano=2020)
    *_, itm = _legacy_tree(norma)

    itm = Dispositivo.objects.get(pk=itm.pk)               # legacy row: no path
    with CaptureQueriesContext(connection) as before:
        itm.get_caminho_completo()
    migration.backfill_caminho_nivel(global_apps, None)

    itm = Dispositivo.objects.get(pk=itm.pk)               # migrated row
    with CaptureQueriesContext(connection) as after:
        assert itm.get_caminho_completo().endswith("Item 1")
    assert len(before) >= 4 and len(after) == 0


def test_migration_is_reversible():
    assert migration.Migration.operations[0].reverse_code is not None
