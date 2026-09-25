# Generated manually for the operational state introduced by the SAPL sync hardening.
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True

    dependencies = []

    operations = [
        migrations.CreateModel(
            name='SaplSyncState',
            fields=[
                (
                    'id',
                    models.BigAutoField(
                        auto_created=True,
                        primary_key=True,
                        serialize=False,
                        verbose_name='ID',
                    ),
                ),
                ('source', models.CharField(db_index=True, default='sapl', max_length=100)),
                ('filter_fingerprint', models.CharField(max_length=64)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('last_started_at', models.DateTimeField(blank=True, null=True)),
                ('last_cursor', models.PositiveIntegerField(default=0)),
                ('last_remote_timestamp', models.DateTimeField(blank=True, null=True)),
                ('last_sync_count', models.PositiveIntegerField(default=0)),
                ('last_error', models.TextField(blank=True)),
                ('lease_until', models.DateTimeField(blank=True, null=True)),
                ('lease_token', models.CharField(blank=True, max_length=64)),
                ('last_full_sync_at', models.DateTimeField(blank=True, null=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
        ),
        migrations.AddConstraint(
            model_name='saplsyncstate',
            constraint=models.UniqueConstraint(
                fields=('source', 'filter_fingerprint'),
                name='unique_sapl_sync_state_scope',
            ),
        ),
        migrations.AddIndex(
            model_name='saplsyncstate',
            index=models.Index(
                fields=['source', 'last_success_at'],
                name='operations_source_last_success',
            ),
        ),
        migrations.AddIndex(
            model_name='saplsyncstate',
            index=models.Index(fields=['lease_until'], name='operations_lease_until'),
        ),
    ]
