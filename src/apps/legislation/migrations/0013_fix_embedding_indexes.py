"""
Fix the embedding indexes created by migration 0007.

1. dispositivo_embedding_cosine_idx was an expression index on
   ``embedding <-> '[0,0,0]'::vector`` (a 3-dimension vector) over a vector(768) column. The
   expression is recomputed on every write, so on a database built with ``migrate`` writing
   ANY embedding failed with "different vector dimensions 768 and 3". It is dropped, and it
   is deliberately NOT recreated on reverse: recreating it would restore the bug.

2. dispositivo_embedding_ivfflat_idx (lists=10) was built on an EMPTY table, so its centroids
   were never trained. Measured recall@10 against exact search: 28.5% (synthetic clustered
   data, 4000 x 768). It also needed re-tuning as the corpus grows. HNSW needs no training,
   works from an empty table and measured 100% on the same data. Requires pgvector >= 0.5.0
   (the compose/CI image pgvector/pgvector:pg16 ships a recent one).

3. HNSW returns at most ``hnsw.ef_search`` rows (default 40) but the semantic search API
   accepts k up to 50; the value is raised to 100 for this database (new connections).

Note: CREATE INDEX (non-concurrent) blocks writes to the table while it builds; the corpus
is small, so this is brief.
"""
from django.db import migrations

EF_SEARCH = 100

FORWARD = f"""
DROP INDEX IF EXISTS dispositivo_embedding_cosine_idx;

CREATE INDEX IF NOT EXISTS dispositivo_embedding_hnsw_idx
    ON legislation_dispositivo
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

DROP INDEX IF EXISTS dispositivo_embedding_ivfflat_idx;

DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I SET hnsw.ef_search = {EF_SEARCH}', current_database());
END
$$;
"""

REVERSE = """
DROP INDEX IF EXISTS dispositivo_embedding_hnsw_idx;

CREATE INDEX IF NOT EXISTS dispositivo_embedding_ivfflat_idx
    ON legislation_dispositivo
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 10);

DO $$
BEGIN
    EXECUTE format('ALTER DATABASE %I RESET hnsw.ef_search', current_database());
END
$$;
"""


def forward_sql(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(FORWARD)


def reverse_sql(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute(REVERSE)


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0012_backfill_chatsession_slug'),
    ]

    operations = [
        migrations.RunPython(forward_sql, reverse_sql),
    ]
