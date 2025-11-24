"""
Django management command for bulk OCR processing of PDFs.

Usage:
    python manage.py bulk_ocr --limit 10
    python manage.py bulk_ocr --all
    python manage.py bulk_ocr --status pdf_downloaded --sync
"""

from django.core.management.base import BaseCommand, CommandError
from src.apps.legislation.models import Norma
from src.apps.ingestion.tasks import ocr_pdf_task


class Command(BaseCommand):
    help = 'Process PDFs with Tesseract OCR to extract text'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all normas with pdf_downloaded status'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limit number of PDFs to process'
        )
        parser.add_argument(
            '--status',
            type=str,
            default='pdf_downloaded',
            help='Filter by norma status (default: pdf_downloaded)'
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run OCR synchronously (blocking) instead of via Celery'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reprocess normas that already have OCR completed'
        )
    
    def handle(self, *args, **options):
        process_all = options['all']
        limit = options['limit']
        status = options['status']
        is_sync = options['sync']
        force = options['force']
        
        # Build queryset
        if force:
            # Reprocess all with given status
            queryset = Norma.objects.filter(status=status)
        else:
            # Only process pdf_downloaded normas (not yet OCR'd)
            queryset = Norma.objects.filter(status='pdf_downloaded')
        
        # Exclude normas without PDF path
        queryset = queryset.exclude(pdf_path='')
        
        # Apply limit if specified
        if limit:
            queryset = queryset[:limit]
        elif not process_all:
            # If not --all and not --limit, ask for confirmation
            count = queryset.count()
            if count > 10:
                self.stdout.write(self.style.WARNING(
                    f'You are about to process OCR for {count} normas.'
                ))
                confirm = input('Continue? (y/N): ')
                if confirm.lower() != 'y':
                    self.stdout.write(self.style.ERROR('Operation cancelled'))
                    return
        
        normas = list(queryset)
        total = len(normas)
        
        if total == 0:
            self.stdout.write(self.style.WARNING(
                'No normas found for OCR processing'
            ))
            return
        
        self.stdout.write(self.style.NOTICE(
            f'Starting OCR processing for {total} norma(s)...'
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
                    result = ocr_pdf_task(norma.id)
                    if result['success']:
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(
                            f'  ✓ OCR completed: {result["pages_processed"]} pages, '
                            f'{result["total_chars"]} chars, '
                            f'{result["processing_time"]:.2f}s'
                        ))
                    else:
                        failed_count += 1
                        self.stdout.write(self.style.ERROR(
                            f'  ✗ Failed: {result.get("error", "Unknown error")}'
                        ))
                else:
                    # Execute asynchronously via Celery
                    task = ocr_pdf_task.delay(norma.id)
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
                f'\nOCR processing completed:\n'
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

