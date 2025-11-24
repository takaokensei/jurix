# Generated migration to enable pgvector extension

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0004_norma_texto_consolidado_alter_norma_status'),
    ]

    operations = [
        migrations.RunSQL(
            sql='CREATE EXTENSION IF NOT EXISTS vector;',
            reverse_sql='DROP EXTENSION IF EXISTS vector;'
        ),
    ]

