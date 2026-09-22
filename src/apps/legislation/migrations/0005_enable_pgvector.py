# Generated migration to enable pgvector extension

from django.db import migrations


def enable_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('CREATE EXTENSION IF NOT EXISTS vector;')


def disable_pgvector(apps, schema_editor):
    if schema_editor.connection.vendor == 'postgresql':
        schema_editor.execute('DROP EXTENSION IF EXISTS vector;')


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0004_norma_texto_consolidado_alter_norma_status'),
    ]

    operations = [
        migrations.RunPython(enable_pgvector, disable_pgvector),
    ]

