from django.db import migrations

TOPICS = (
    ("educacao", "Educação"),
    ("saude", "Saúde"),
    ("meio-ambiente", "Meio ambiente"),
    ("urbanismo", "Urbanismo"),
    ("orcamento", "Orçamento público"),
    ("servidor-publico", "Servidor público"),
    ("tributario", "Tributário"),
)


def seed_topics(apps, schema_editor):
    Topic = apps.get_model("legislation", "Topic")
    for code, label in TOPICS:
        Topic.objects.get_or_create(code=code, defaults={"label": label})


def unseed_topics(apps, schema_editor):
    # Do not delete curated records on reverse; the schema migration owns teardown.
    pass


class Migration(migrations.Migration):
    dependencies = [("legislation", "0025_topic_normatopic")]
    operations = [migrations.RunPython(seed_topics, unseed_topics)]
