from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0017_event_provenance")]

    operations = [
        migrations.AddField(
            model_name="dispositivo",
            name="embedding_revision_fingerprint",
            field=models.CharField(
                blank=True,
                help_text="Fingerprint do conteúdo de origem usado para gerar o embedding.",
                max_length=64,
            ),
        ),
    ]
