# Generated manually for slug field addition

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0008_chatsession_chatmessage_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='chatsession',
            name='slug',
            field=models.CharField(blank=True, db_index=True, help_text='Identificador único da sessão para URL (ex: abc123def456)', max_length=50, null=True, unique=True, verbose_name='Slug'),
        ),
    ]

