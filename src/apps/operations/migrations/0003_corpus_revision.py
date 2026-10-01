from django.db import migrations, models


def seed_revision(apps, schema_editor):
    CorpusRevision = apps.get_model("operations", "CorpusRevision")
    CorpusRevision.objects.using(schema_editor.connection.alias).get_or_create(
        key="municipal",
        defaults={"completeness": "unknown", "segmentation_version": "hierarchy-v1"},
    )


class Migration(migrations.Migration):
    dependencies = [("operations", "0002_attachmentrecord_and_more")]

    operations = [
        migrations.CreateModel(
            name="CorpusRevision",
            fields=[
                ("key", models.CharField(default="municipal", max_length=32, primary_key=True, serialize=False)),
                ("revision", models.PositiveBigIntegerField(default=0)),
                ("digest", models.CharField(blank=True, max_length=64)),
                ("norm_count", models.PositiveIntegerField(default=0)),
                ("device_count", models.PositiveIntegerField(default=0)),
                ("active_event_count", models.PositiveIntegerField(default=0)),
                ("schema_version", models.PositiveSmallIntegerField(default=1)),
                ("segmentation_version", models.CharField(default="hierarchy-v1", max_length=40)),
                (
                    "completeness",
                    models.CharField(
                        choices=[("unknown", "Desconhecida"), ("partial", "Parcial"), ("complete", "Declarada completa")],
                        default="unknown",
                        max_length=16,
                    ),
                ),
                ("generated_at", models.DateTimeField(blank=True, null=True)),
                ("updated_at", models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.RunPython(seed_revision, migrations.RunPython.noop),
    ]
