# Migration to create IVFFlat index for pgvector semantic search optimization

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0006_dispositivo_embedding_and_more'),
    ]

    operations = [
        # Create IVFFlat index for cosine distance similarity search
        # IVFFlat is an approximate nearest neighbor (ANN) algorithm
        # that provides faster searches on large datasets
        #
        # Parameters:
        # - lists: Number of inverted lists (clusters)
        #   Rule of thumb: sqrt(total_rows) for small datasets, or rows/1000 for large
        #   Using 10 lists for small datasets (will be efficient for < 10,000 rows)
        #
        # Note: This index dramatically speeds up vector searches but adds
        # overhead on inserts/updates. For < 1000 rows, brute force might be faster.
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS dispositivo_embedding_ivfflat_idx
                ON legislation_dispositivo
                USING ivfflat (embedding vector_cosine_ops)
                WITH (lists = 10);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS dispositivo_embedding_ivfflat_idx;
            """
        ),
        
        # Optional: Create additional index for distance operator
        # This allows efficient filtering by distance threshold
        migrations.RunSQL(
            sql="""
                CREATE INDEX IF NOT EXISTS dispositivo_embedding_cosine_idx
                ON legislation_dispositivo
                ((embedding <-> '[0,0,0]'::vector))
                WHERE embedding IS NOT NULL;
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS dispositivo_embedding_cosine_idx;
            """,
            # This index is optional and might fail on some pgvector versions
            # Using noop for reverse to avoid migration errors
            state_operations=[]
        ),
    ]

