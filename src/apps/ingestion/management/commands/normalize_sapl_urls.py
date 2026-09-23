from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from src.apps.legislation.models import Norma
from src.apps.legislation.source_urls import canonical_norma_url


class Command(BaseCommand):
    help = "Corrige URLs SAPL legadas /norma/normajuridica/<id>/ no banco."

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true')
        parser.add_argument('--batch-size', type=int, default=500)

    def handle(self, *args, **options):
        changed = 0
        batch_size = max(1, min(options['batch_size'], 5000))
        qs = Norma.objects.all().only('id', 'sapl_id', 'sapl_url').order_by('id')

        for start in range(0, qs.count(), batch_size):
            with transaction.atomic():
                for norma in qs[start:start + batch_size]:
                    canonical = canonical_norma_url(norma)
                    if canonical and canonical != norma.sapl_url:
                        changed += 1
                        if not options['dry_run']:
                            Norma.objects.filter(pk=norma.pk).update(sapl_url=canonical)

        action = 'seriam corrigidas' if options['dry_run'] else 'foram corrigidas'
        self.stdout.write(self.style.SUCCESS(f'{changed} URL(s) SAPL {action}.'))
