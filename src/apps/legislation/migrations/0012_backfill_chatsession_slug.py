"""
Give every ChatSession a slug.

ChatSession.save() now generates the slug, but sessions created before that (through the
API, which never generated one) still have NULL/'' and cannot be opened by URL.

Self-contained on purpose: migrations must keep working when application code changes.
"""
import secrets
import string

from django.db import migrations

ALPHABET = string.ascii_lowercase + string.digits


def backfill_slugs(apps, schema_editor):
    ChatSession = apps.get_model('legislation', 'ChatSession')
    taken = set(
        ChatSession.objects.exclude(slug__isnull=True).exclude(slug='')
        .values_list('slug', flat=True)
    )
    pending = list(ChatSession.objects.filter(slug__isnull=True) | ChatSession.objects.filter(slug=''))
    for session in pending:
        while True:
            slug = ''.join(secrets.choice(ALPHABET) for _ in range(12))
            if slug not in taken:
                break
        taken.add(slug)
        session.slug = slug
    # bulk_update does not touch auto_now fields: updated_at stays truthful
    ChatSession.objects.bulk_update(pending, ['slug'], batch_size=1000)


class Migration(migrations.Migration):

    dependencies = [
        ('legislation', '0011_backfill_dispositivo_caminho'),
    ]

    operations = [
        # Reverse is a no-op: a slug is harmless once assigned.
        migrations.RunPython(backfill_slugs, migrations.RunPython.noop),
    ]
