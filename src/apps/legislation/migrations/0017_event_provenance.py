from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("legislation", "0016_device_revision_identity")]

    operations = [
        migrations.AddField(
            model_name="eventoalteracao",
            name="revision_fingerprint",
            field=models.CharField(
                blank=True,
                db_index=True,
                help_text="Identidade da evidência e da versão do extrator desta revisão.",
                max_length=64,
            ),
        ),
        migrations.AddField(
            model_name="eventoalteracao",
            name="provenance_json",
            field=models.JSONField(
                blank=True,
                default=dict,
                help_text="Proveniência da extração, sem credenciais ou dados de requisição.",
            ),
        ),
        migrations.AddField(
            model_name="eventoalteracao",
            name="is_active",
            field=models.BooleanField(
                db_index=True,
                default=True,
                help_text="Evento encontrado na extração atual; revisões antigas são preservadas.",
            ),
        ),
    ]
