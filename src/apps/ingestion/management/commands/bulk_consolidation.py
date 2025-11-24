"""
Django Management Command: bulk_consolidation

Triggers consolidation for normas with extracted entities.
Dispatches consolidate_norma_task for normas with status='entities_extracted'.
"""

import logging
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from src.apps.legislation.models import Norma
from src.apps.ingestion.tasks import consolidate_norma_task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Trigger legal consolidation for normas with status="entities_extracted". '
        'Dispatches Celery task consolidate_norma_task for each norma.'
    )
    
    def add_arguments(self, parser):
        """Define command arguments."""
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of normas to process (default: all available)'
        )
        
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Skip this many normas before starting (default: 0)'
        )
        
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run consolidation synchronously (blocking) instead of async via Celery'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-consolidation for normas already processed (status=consolidated)'
        )
        
        parser.add_argument(
            '--norma-id',
            type=int,
            default=None,
            help='Process a specific norma by ID'
        )
        
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process ALL normas regardless of status (use with --force)'
        )
    
    def handle(self, *args, **options):
        """Execute the bulk consolidation."""
        limit: Optional[int] = options['limit']
        offset: int = options['offset']
        sync_mode: bool = options['sync']
        force: bool = options['force']
        norma_id: Optional[int] = options['norma_id']
        process_all: bool = options['all']
        
        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(self.style.NOTICE('Legal Consolidation - Bulk Processing'))
        self.stdout.write(self.style.NOTICE('=' * 80))
        
        # Specific norma by ID
        if norma_id:
            try:
                norma = Norma.objects.get(id=norma_id)
                self.stdout.write(
                    self.style.WARNING(f'\n🎯 Processing specific Norma: {norma}')
                )
                
                if sync_mode:
                    result = consolidate_norma_task(norma.id)
                    self._display_result(result)
                else:
                    task = consolidate_norma_task.delay(norma.id)
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Task dispatched: {task.id}')
                    )
                
                return
                
            except Norma.DoesNotExist:
                raise CommandError(f'Norma with ID={norma_id} not found')
        
        # Build queryset based on options
        if process_all:
            queryset = Norma.objects.all()
            self.stdout.write(
                self.style.WARNING('\n⚠️  Processing ALL normas (--all flag active)')
            )
        elif force:
            queryset = Norma.objects.filter(
                Q(status='entities_extracted') | Q(status='consolidated')
            )
            self.stdout.write(
                self.style.WARNING(
                    '\n🔄 Force mode: Re-consolidating entities_extracted and consolidated normas'
                )
            )
        else:
            queryset = Norma.objects.filter(status='entities_extracted')
        
        # Apply ordering, offset, and limit
        queryset = queryset.order_by('id')[offset:]
        if limit:
            queryset = queryset[:limit]
        
        total = queryset.count()
        
        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  No normas found matching criteria. '
                    'Try --force or --all flags.'
                )
            )
            return
        
        self.stdout.write(
            self.style.NOTICE(f'\n📊 Found {total} norma(s) to process')
        )
        self.stdout.write(self.style.NOTICE(f'   Offset: {offset}'))
        self.stdout.write(self.style.NOTICE(f'   Limit: {limit if limit else "None (all)"}'))
        self.stdout.write(
            self.style.NOTICE(f'   Mode: {"Synchronous (blocking)" if sync_mode else "Async (Celery)"}')
        )
        self.stdout.write(self.style.NOTICE('-' * 80))
        
        # Process normas
        success_count = 0
        failure_count = 0
        
        for idx, norma in enumerate(queryset, start=1):
            self.stdout.write(
                f'\n[{idx}/{total}] Processing: {norma} (ID={norma.id}, Status={norma.status})'
            )
            
            try:
                if sync_mode:
                    # Synchronous execution (blocking)
                    result = consolidate_norma_task(norma.id)
                    
                    if result.get('success'):
                        success_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✓ SUCCESS: '
                                f'{result.get("total_dispositivos", 0)} dispositivos, '
                                f'{result.get("revoked_count", 0)} revoked, '
                                f'{result.get("altered_count", 0)} altered, '
                                f'{result.get("events_processed", 0)} events '
                                f'in {result.get("processing_time", 0):.2f}s'
                            )
                        )
                        self.stdout.write(
                            f'    Consolidated text: {result.get("consolidated_length", 0)} chars'
                        )
                    else:
                        failure_count += 1
                        self.stdout.write(
                            self.style.ERROR(
                                f'  ✗ FAILED: {result.get("error", "Unknown error")}'
                            )
                        )
                else:
                    # Asynchronous execution via Celery
                    task = consolidate_norma_task.delay(norma.id)
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Task dispatched: {task.id}')
                    )
                    
            except Exception as e:
                failure_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ ERROR: {str(e)}')
                )
                logger.error(f'Error processing Norma {norma.id}: {e}', exc_info=True)
        
        # Summary
        self.stdout.write(self.style.NOTICE('\n' + '=' * 80))
        self.stdout.write(self.style.NOTICE('SUMMARY'))
        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(f'Total processed: {total}')
        self.stdout.write(self.style.SUCCESS(f'✓ Success: {success_count}'))
        
        if failure_count > 0:
            self.stdout.write(self.style.ERROR(f'✗ Failures: {failure_count}'))
        
        if not sync_mode:
            self.stdout.write(
                self.style.WARNING(
                    '\n💡 Tasks are running asynchronously. '
                    'Check Celery worker logs for results.'
                )
            )
        
        self.stdout.write(self.style.NOTICE('=' * 80))
    
    def _display_result(self, result: dict):
        """Display detailed result for a single task execution."""
        if result.get('success'):
            self.stdout.write(self.style.SUCCESS('\n✓ SUCCESS'))
            self.stdout.write(f'  Total dispositivos: {result.get("total_dispositivos", 0)}')
            self.stdout.write(f'  Revoked: {result.get("revoked_count", 0)}')
            self.stdout.write(f'  Altered: {result.get("altered_count", 0)}')
            self.stdout.write(f'  Events processed: {result.get("events_processed", 0)}')
            self.stdout.write(f'  Consolidated text length: {result.get("consolidated_length", 0)} chars')
            self.stdout.write(f'  Processing time: {result.get("processing_time", 0):.2f}s')
        else:
            self.stdout.write(self.style.ERROR('\n✗ FAILED'))
            self.stdout.write(self.style.ERROR(f'  Error: {result.get("error", "Unknown")}'))

