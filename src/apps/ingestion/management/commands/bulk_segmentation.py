"""
Django management command for bulk text segmentation of normas.

Usage:
    python manage.py bulk_segmentation --limit 10
    python manage.py bulk_segmentation --all
    python manage.py bulk_segmentation --status ocr_completed --sync
"""

from django.core.management.base import BaseCommand, CommandError
from src.apps.legislation.models import Norma
from src.apps.ingestion.tasks import segment_text_task


class Command(BaseCommand):
    help = 'Segment legal text into hierarchical Dispositivo structure'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all normas with ocr_completed status'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of normas to process'
        )
        parser.add_argument(
            '--status',
            type=str,
            default='ocr_completed',
            help='Filter by norma status (default: ocr_completed)'
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run segmentation synchronously (blocking) instead of via Celery'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reprocess normas that already have segmentation completed'
        )
    
    def handle(self, *args, **options):
        process_all = options['all']
        limit = options['limit']
        status = options['status']
        is_sync = options['sync']
        force = options['force']
        
        # Build queryset
        if force:
            if process_all:
                # Reprocess ALL normas with texto_original, regardless of status
                queryset = Norma.objects.exclude(texto_original='').exclude(texto_original__isnull=True)
            else:
                # Reprocess all with given status
                queryset = Norma.objects.filter(status=status).exclude(texto_original='')
        else:
            # Only process ocr_completed normas (not yet segmented)
            queryset = Norma.objects.filter(status='ocr_completed')
        
        # Exclude normas without texto_original
        queryset = queryset.exclude(texto_original='').exclude(texto_original__isnull=True)
        
        # Apply limit if specified
        if limit:
            queryset = queryset[:limit]
        elif not process_all:
            # If not --all and not --limit, ask for confirmation
            count = queryset.count()
            if count > 10:
                self.stdout.write(self.style.WARNING(
                    f'You are about to process segmentation for {count} normas.'
                ))
                confirm = input('Continue? (y/N): ')
                if confirm.lower() != 'y':
                    self.stdout.write(self.style.ERROR('Operation cancelled'))
                    return
        
        normas = list(queryset)
        total = len(normas)
        
        if total == 0:
            self.stdout.write(self.style.WARNING(
                'No normas found for segmentation'
            ))
            return
        
        self.stdout.write(self.style.NOTICE(
            f'Starting text segmentation for {total} norma(s)...'
        ))
        
        if is_sync:
            self.stdout.write(self.style.WARNING(
                'SYNC mode enabled. This may take a while...'
            ))
        
        success_count = 0
        failed_count = 0
        task_ids = []
        
        for i, norma in enumerate(normas, 1):
            self.stdout.write(f'[{i}/{total}] Processing {norma}...')
            
            try:
                if is_sync:
                    # Execute synchronously
                    result = segment_text_task(norma.id)
                    if result['success']:
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(
                            f'  ✓ Segmentation completed: {result["dispositivos_created"]} '
                            f'dispositivos ({result["articles"]} articles, '
                            f'{result["paragraphs"]} paragraphs, {result["incisos"]} incisos, '
                            f'{result["alineas"]} alineas) in {result["processing_time"]:.2f}s'
                        ))
                    else:
                        failed_count += 1
                        self.stdout.write(self.style.ERROR(
                            f'  ✗ Failed: {result.get("error", "Unknown error")}'
                        ))
                else:
                    # Execute asynchronously via Celery
                    task = segment_text_task.delay(norma.id)
                    task_ids.append(task.id)
                    self.stdout.write(self.style.NOTICE(
                        f'  → Task dispatched: {task.id}'
                    ))
            
            except Exception as e:
                failed_count += 1
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Critical error: {str(e)}'
                ))
        
        # Summary
        self.stdout.write('\n' + '='*50)
        if is_sync:
            self.stdout.write(self.style.SUCCESS(
                f'\nText segmentation completed:\n'
                f'  - Success: {success_count}\n'
                f'  - Failed: {failed_count}\n'
                f'  - Total: {total}'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nTasks dispatched: {len(task_ids)}\n'
            ))
            self.stdout.write(self.style.NOTICE(
                'Monitor with:\n'
                '  docker-compose logs -f worker\n'
                '  docker-compose exec worker celery -A config inspect active'
            ))

