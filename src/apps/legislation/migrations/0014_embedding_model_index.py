from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0013_fix_embedding_indexes'),
    ]

    operations = [
        migrations.AddIndex(
            model_name='dispositivo',
            index=models.Index(
                fields=['embedding_model'],
                name='disp_embed_model_idx',
            ),
        ),
    ]
