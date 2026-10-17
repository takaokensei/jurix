from django.contrib.postgres.indexes import GinIndex
from django.contrib.postgres.search import SearchVector
from django.db import migrations

SEARCH_CONFIG = "jurix_archive_pt_v1"
INDEX_NAME = "extr_legal_pt_gin"


def install_search_config(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("CREATE EXTENSION IF NOT EXISTS unaccent")
        cursor.execute(
            f"CREATE TEXT SEARCH CONFIGURATION public.{SEARCH_CONFIG} "
            "(COPY = pg_catalog.portuguese)"
        )
        cursor.execute(
            f"ALTER TEXT SEARCH CONFIGURATION public.{SEARCH_CONFIG} "
            "ALTER MAPPING FOR hword, hword_part, word "
            "WITH unaccent, pg_catalog.portuguese_stem"
        )


def remove_search_config(apps, schema_editor):
    if schema_editor.connection.vendor == "postgresql":
        schema_editor.execute(
            f"DROP TEXT SEARCH CONFIGURATION IF EXISTS public.{SEARCH_CONFIG}"
        )


def create_search_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    extraction = apps.get_model("legislation", "ExtracaoDocumento")
    index = GinIndex(
        SearchVector("legal_text", config=SEARCH_CONFIG),
        name=INDEX_NAME,
    )
    statement = str(index.create_sql(extraction, schema_editor))
    statement = statement.replace("CREATE INDEX ", "CREATE INDEX CONCURRENTLY ", 1)
    schema_editor.execute(statement)


def remove_search_index(apps, schema_editor):
    if schema_editor.connection.vendor != "postgresql":
        return
    extraction = apps.get_model("legislation", "ExtracaoDocumento")
    index = GinIndex(
        SearchVector("legal_text", config=SEARCH_CONFIG),
        name=INDEX_NAME,
    )
    statement = index.remove_sql(extraction, schema_editor)
    statement = str(statement).replace("DROP INDEX ", "DROP INDEX CONCURRENTLY ", 1)
    schema_editor.execute(statement)


class Migration(migrations.Migration):
    atomic = False

    dependencies = [("legislation", "0027_collectionevidenceversion")]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunPython(install_search_config, remove_search_config),
                migrations.RunPython(create_search_index, remove_search_index),
            ],
            state_operations=[
                migrations.AddIndex(
                    model_name="extracaodocumento",
                    index=GinIndex(
                        SearchVector("legal_text", config=SEARCH_CONFIG),
                        name=INDEX_NAME,
                    ),
                ),
            ],
        ),
    ]
