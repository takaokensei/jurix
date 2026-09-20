from django.db import migrations


def create_vector_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("""
            CREATE INDEX IF NOT EXISTS dispositivo_embedding_ivfflat_idx
            ON legislation_dispositivo
            USING ivfflat (embedding vector_cosine_ops)
            WITH (lists = 10);
        """)
        try:
            schema_editor.execute("""
                CREATE INDEX IF NOT EXISTS dispositivo_embedding_cosine_idx
                ON legislation_dispositivo
                ((embedding <-> '[0,0,0]'::vector))
                WHERE embedding IS NOT NULL;
            """)
        except Exception:
            pass


def drop_vector_indexes(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute("DROP INDEX IF EXISTS dispositivo_embedding_ivfflat_idx;")
        schema_editor.execute("DROP INDEX IF EXISTS dispositivo_embedding_cosine_idx;")


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0006_dispositivo_embedding_and_more'),
    ]

    operations = [
        migrations.RunPython(create_vector_indexes, drop_vector_indexes),
    ]

