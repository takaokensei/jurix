import django.core.validators
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):
    dependencies = [("legislation", "0028_archive_search_vector_index")]

    operations = [
        migrations.CreateModel(
            name="EventoNormativoCandidato",
            fields=[
                (
                    "id",
                    models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID"),
                ),
                ("fingerprint", models.CharField(max_length=64, unique=True, validators=[django.core.validators.RegexValidator(r"^[a-f0-9]{64}$", "Informe um SHA-256 hexadecimal válido.")])),
                ("source_structural_key", models.CharField(max_length=160)),
                ("source_device_label", models.CharField(max_length=120)),
                ("action", models.CharField(max_length=20)),
                ("action_quote", models.CharField(max_length=500)),
                ("target_text", models.CharField(max_length=500)),
                ("target_reference_json", models.JSONField(blank=True, default=dict)),
                ("evidence_json", models.JSONField(default=dict)),
                ("extraction_confidence", models.FloatField(default=0.0)),
                ("extraction_method", models.CharField(default="regex_inherited_list", max_length=50)),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "extracao",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="eventos_normativos_candidatos",
                        to="legislation.extracaodocumento",
                    ),
                ),
            ],
            options={
                "ordering": ["extracao_id", "source_structural_key", "pk"],
                "indexes": [models.Index(fields=["extracao", "action"], name="doc_event_cand_act_idx")],
            },
        ),
    ]
