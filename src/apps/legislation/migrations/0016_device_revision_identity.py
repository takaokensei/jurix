from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0015_collection_collection_unique_collection_per_user")]

    operations = [
        migrations.AddField(
            model_name="dispositivo",
            name="structural_key",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Identidade estrutural estável do dispositivo dentro da norma.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="dispositivo",
            name="revision_fingerprint",
            field=models.CharField(
                blank=True,
                help_text="Hash do texto e redação bruta desta revisão do dispositivo.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="dispositivo",
            name="is_active",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text="Dispositivo presente na última segmentação validada da norma.",
            ),
        ),
    ]
