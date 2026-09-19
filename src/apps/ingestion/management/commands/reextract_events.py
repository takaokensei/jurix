"""
Django Management Command: reextract_events

Reprocesses EventoAlteracao instances across existing normas using the improved
LegalNERExtractor (window-based syntax parsing without Cartesian product).

Maintains database integrity and idempotency by purging old events per norma
within an atomic transaction before inserting newly extracted events.
"""

import logging
import time
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import Count

from src.apps.legislation.models import Norma, EventoAlteracao
from src.apps.ingestion.tasks import extract_entities_task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Re-extract legal alteration events using the updated LegalNERExtractor. '
        'Purges outdated/spurious Cartesian-product events idempotently.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--norma-id',
            type=int,
            default=None,
            help='Process a specific Norma ID only'
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            default=True,
            help='Run extraction synchronously in the current process (default: True)'
        )
        parser.add_argument(
            '--async',
            dest='sync',
            action='store_false',
            help='Dispatch Celery tasks asynchronously'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of normas to process'
        )

    def handle(self, *args, **options):
        norma_id: Optional[int] = options.get('norma_id')
        sync_mode: bool = options.get('sync', True)
        limit: Optional[int] = options.get('limit')

        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(self.style.NOTICE('Re-extract Legal Alteration Events (Clean NER)'))
        self.stdout.write(self.style.NOTICE('=' * 80))

        initial_events_count = EventoAlteracao.objects.count()
        self.stdout.write(f'Initial EventoAlteracao count in DB: {initial_events_count}')

        if norma_id:
            try:
                norma = Norma.objects.get(id=norma_id)
                queryset = Norma.objects.filter(id=norma_id)
            except Norma.DoesNotExist:
                raise CommandError(f'Norma with id={norma_id} does not exist.')
        else:
            # Target all normas that have parsed/segmented dispositivos
            queryset = Norma.objects.filter(dispositivos__isnull=False).distinct().order_by('id')
            if limit:
                queryset = queryset[:limit]

        total = queryset.count()
        self.stdout.write(self.style.NOTICE(f'Found {total} Norma(s) eligible for re-extraction.'))

        if total == 0:
            self.stdout.write(self.style.WARNING('No matching normas found.'))
            return

        start_time = time.time()
        success_count = 0
        failure_count = 0

        for idx, norma in enumerate(queryset, start=1):
            self.stdout.write(f'[{idx}/{total}] Processing Norma #{norma.id} ({norma})...', ending=' ')
            try:
                if sync_mode:
                    result = extract_entities_task(norma.id)
                    events_created = result.get('events_created', 0)
                    self.stdout.write(self.style.SUCCESS(f'OK ({events_created} events)'))
                    success_count += 1
                else:
                    task = extract_entities_task.delay(norma.id)
                    self.stdout.write(self.style.SUCCESS(f'Dispatched task {task.id}'))
                    success_count += 1
            except Exception as exc:
                self.stdout.write(self.style.ERROR(f'FAILED: {exc}'))
                logger.exception(f'Error re-extracting events for norma #{norma.id}: {exc}')
                failure_count += 1

        elapsed = time.time() - start_time
        final_events_count = EventoAlteracao.objects.count()

        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(self.style.SUCCESS(f'Completed in {elapsed:.2f}s'))
        self.stdout.write(f'Successfully processed: {success_count}')
        if failure_count:
            self.stdout.write(self.style.ERROR(f'Failures: {failure_count}'))
        
        if sync_mode:
            self.stdout.write(f'Previous total events: {initial_events_count}')
            self.stdout.write(f'Current total events:  {final_events_count}')
            diff = final_events_count - initial_events_count
            self.stdout.write(f'Net event delta:       {"+" if diff >= 0 else ""}{diff}')
            
            # Action distribution breakdown
            distribution = dict(EventoAlteracao.objects.values_list('acao').annotate(Count('id')))
            self.stdout.write(f'Event actions breakdown: {distribution}')
        else:
            self.stdout.write(self.style.WARNING('Tasks dispatched asynchronously; inspect worker logs.'))

        self.stdout.write(self.style.NOTICE('=' * 80))
