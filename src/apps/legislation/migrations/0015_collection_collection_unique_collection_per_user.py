import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0014_embedding_model_index'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='Collection',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created_at', models.DateTimeField(auto_now_add=True, verbose_name='Criado em')),
                ('updated_at', models.DateTimeField(auto_now=True, verbose_name='Atualizado em')),
                ('name', models.CharField(max_length=120)),
                ('description', models.CharField(blank=True, max_length=500)),
                ('normas', models.ManyToManyField(blank=True, related_name='collections', to='legislation.norma')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='jurix_collections', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-updated_at', 'name'],
            },
        ),
        migrations.AddConstraint(
            model_name='collection',
            constraint=models.UniqueConstraint(fields=('user', 'name'), name='unique_collection_per_user'),
        ),
    ]
