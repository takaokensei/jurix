from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("operations", "0006_normativeworkitem_review_reason_and_more"),
    ]

    operations = [
        migrations.AddField(
            model_name="saplsyncstate",
            name="full_sweep_token",
            field=models.CharField(blank=True, max_length=64),
        ),
        migrations.AddField(
            model_name="saplsyncstate",
            name="full_sweep_expected_count",
            field=models.PositiveIntegerField(blank=True, null=True),
        ),
    ]
