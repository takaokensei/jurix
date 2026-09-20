"""
End-to-end check of the schema produced by the REAL migrations (audit P3.1, severity raised).

The rest of the suite runs with --nomigrations (the schema is built from the models), so
the raw SQL inside migrations is never executed by it. That is how migration 0007 shipped an
index on ``embedding <-> '[0,0,0]'``: on a database built with ``migrate``, writing ANY
768-dimension embedding failed with "different vector dimensions 768 and 3", because the
expression index is recomputed on every write.

This test builds a throwaway database with ``manage.py migrate`` and writes an embedding.
"""
import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote

import psycopg2
import pytest
from django.conf import settings

ROOT = Path(__file__).resolve().parents[2]
DIM = 768


def probe(tag):
    """Shell snippet that writes embeddings; `tag` keeps the norma unique across tests."""
    return f"""
from src.apps.legislation.models import Norma, Dispositivo
n = Norma.objects.create(tipo="Lei", numero="{tag}", ano=2020)
d = Dispositivo.objects.create(norma=n, tipo="artigo", numero="1", texto="t", ordem=1)
Dispositivo.objects.filter(pk=d.pk).update(embedding=[0.01] * {DIM})
Dispositivo.objects.create(norma=n, tipo="artigo", numero="2", texto="t", ordem=2, embedding=[0.02] * {DIM})
print("EMBEDDINGS-OK")
"""


@pytest.fixture(scope="module")
def migrated_db_url():
    cfg = settings.DATABASES["default"]
    if cfg.get("ENGINE") != "django.db.backends.postgresql":
        pytest.skip("PostgreSQL backend required for migrated_db_url fixture")
    name = f"jurix_migtest_{os.getpid()}"
    try:
        admin = psycopg2.connect(
            dbname=cfg["NAME"], user=cfg["USER"], password=cfg["PASSWORD"],
            host=cfg["HOST"], port=cfg["PORT"],
        )
    except psycopg2.OperationalError as exc:  # pragma: no cover
        pytest.skip(f"cannot connect to PostgreSQL: {exc}")
    admin.autocommit = True
    cur = admin.cursor()
    try:
        cur.execute(f'CREATE DATABASE "{name}"')
    except psycopg2.Error as exc:  # pragma: no cover
        admin.close()
        pytest.skip(f"cannot create a scratch database: {exc}")
    try:
        scratch = psycopg2.connect(
            dbname=name, user=cfg["USER"], password=cfg["PASSWORD"], host=cfg["HOST"], port=cfg["PORT"]
        )
        scratch.autocommit = True
        scratch.cursor().execute("CREATE EXTENSION IF NOT EXISTS vector")
        scratch.close()
        yield (
            f"postgresql://{quote(cfg['USER'])}:{quote(cfg['PASSWORD'])}"
            f"@{cfg['HOST']}:{cfg['PORT']}/{name}"
        )
    finally:
        cur.execute(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)')
        admin.close()


def _manage(url, *args):
    env = {**os.environ, "DATABASE_URL": url, "PYTHONPATH": str(ROOT), "PYTHONUTF8": "1"}
    return subprocess.run(
        [sys.executable, "manage.py", *args], cwd=ROOT, env=env, capture_output=True, text=True, timeout=300
    )


def test_migrations_apply_and_embeddings_can_be_written(migrated_db_url):
    migrate = _manage(migrated_db_url, "migrate", "-v0")
    assert migrate.returncode == 0, migrate.stderr[-1500:]

    probe_run = _manage(migrated_db_url, "shell", "-c", probe("forward"))
    assert "EMBEDDINGS-OK" in probe_run.stdout, probe_run.stderr[-1500:]


def test_no_migration_leaves_the_schema_out_of_sync_with_the_models(migrated_db_url):
    _manage(migrated_db_url, "migrate", "-v0")
    check = _manage(migrated_db_url, "makemigrations", "--check", "--dry-run")
    assert check.returncode == 0, check.stdout[-800:]


def _psql(url, sql):
    """Run one statement on a NEW connection (so database-level settings apply)."""
    conn = psycopg2.connect(url)
    conn.autocommit = True
    try:
        cur = conn.cursor()
        cur.execute(sql)
        return cur.fetchall()
    finally:
        conn.close()


def test_embedding_indexes_are_the_intended_ones(migrated_db_url):
    _manage(migrated_db_url, "migrate", "-v0")
    rows = _psql(migrated_db_url, "select indexname, indexdef from pg_indexes "
                                  "where tablename = 'legislation_dispositivo' and indexdef ilike '%embedding%'")
    defs = {name: definition for name, definition in rows}

    assert "dispositivo_embedding_cosine_idx" not in defs, "the broken 3-dimension expression index is back"
    assert "dispositivo_embedding_ivfflat_idx" not in defs, "untrained IVFFlat index is back"
    assert "hnsw" in defs["dispositivo_embedding_hnsw_idx"].lower()
    assert "vector_cosine_ops" in defs["dispositivo_embedding_hnsw_idx"]


def test_hnsw_search_can_return_up_to_50_rows(migrated_db_url):
    """The default hnsw.ef_search (40) would silently cut a k=50 search to 40 rows."""
    _manage(migrated_db_url, "migrate", "-v0")
    assert _psql(migrated_db_url, "show hnsw.ef_search") == [("100",)]

    seed = """
from src.apps.legislation.models import Norma, Dispositivo
n = Norma.objects.create(tipo="Lei", numero="2", ano=2020)
Dispositivo.objects.bulk_create([
    Dispositivo(norma=n, tipo="artigo", numero=str(i), texto="t", ordem=i,
                embedding=[(i % 7 + 1) / 10] * 768 if i % 2 else [0.5, *[(i % 5) / 10] * 767])
    for i in range(1, 121)
])
print("SEEDED")
"""
    assert "SEEDED" in _manage(migrated_db_url, "shell", "-c", seed).stdout
    conn = psycopg2.connect(migrated_db_url)
    try:
        cur = conn.cursor()
        cur.execute("set enable_seqscan = off")          # force the HNSW index
        cur.execute("select count(*) from (select id from legislation_dispositivo "
                    "order by embedding <=> %s::vector limit 50) t", ("[" + ",".join(["0.3"] * 768) + "]",))
        assert cur.fetchone()[0] == 50
    finally:
        conn.close()


def test_migration_0013_is_reversible_without_reintroducing_the_bug(migrated_db_url):
    _manage(migrated_db_url, "migrate", "-v0")
    back = _manage(migrated_db_url, "migrate", "legislation", "0012", "-v0")
    assert back.returncode == 0, back.stderr[-800:]

    names = {r[0] for r in _psql(migrated_db_url, "select indexname from pg_indexes where tablename='legislation_dispositivo'")}
    assert "dispositivo_embedding_ivfflat_idx" in names
    assert "dispositivo_embedding_cosine_idx" not in names          # never recreated
    assert "EMBEDDINGS-OK" in _manage(migrated_db_url, "shell", "-c", probe("reverse")).stdout
