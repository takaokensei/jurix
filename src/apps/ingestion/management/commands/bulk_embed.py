"""
Django Management Command: bulk_embed

Triggers embedding generation for dispositivos.
Dispatches generate_embedding_task for dispositivos without embeddings.
"""

import logging
from typing import Optional

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from src.apps.legislation.models import Dispositivo
from src.apps.ingestion.tasks import generate_embedding_task

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Generate embeddings for dispositivos using Ollama. '
        'Dispatches Celery task generate_embedding_task for each dispositivo.'
    )
    
    def add_arguments(self, parser):
        """Define command arguments."""
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of dispositivos to process (default: all available)'
        )
        
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Skip this many dispositivos before starting (default: 0)'
        )
        
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Run embedding generation synchronously (blocking) instead of async via Celery'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-generation of embeddings for dispositivos that already have them'
        )
        
        parser.add_argument(
            '--dispositivo-id',
            type=int,
            default=None,
            help='Process a specific dispositivo by ID'
        )
        
        parser.add_argument(
            '--model',
            type=str,
            default='nomic-embed-text',
            help='Ollama model to use for embeddings (default: nomic-embed-text)'
        )
        
        parser.add_argument(
            '--norma-id',
            type=int,
            default=None,
            help='Process only dispositivos from a specific norma'
        )
    
    def handle(self, *args, **options):
        """Execute the bulk embedding generation."""
        limit: Optional[int] = options['limit']
        offset: int = options['offset']
        sync_mode: bool = options['sync']
        force: bool = options['force']
        dispositivo_id: Optional[int] = options['dispositivo_id']
        model: str = options['model']
        norma_id: Optional[int] = options['norma_id']
        
        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(self.style.NOTICE('Embedding Generation - Bulk Processing'))
        self.stdout.write(self.style.NOTICE('=' * 80))
        
        # Specific dispositivo by ID
        if dispositivo_id:
            try:
                dispositivo = Dispositivo.objects.get(id=dispositivo_id)
                self.stdout.write(
                    self.style.WARNING(f'\n🎯 Processing specific Dispositivo: {dispositivo}')
                )
                
                if sync_mode:
                    result = generate_embedding_task(dispositivo.id, model=model)
                    self._display_result(result)
                else:
                    task = generate_embedding_task.delay(dispositivo.id, model=model)
                    self.stdout.write(
                        self.style.SUCCESS(f'✓ Task dispatched: {task.id}')
                    )
                
                return
                
            except Dispositivo.DoesNotExist:
                raise CommandError(f'Dispositivo with ID={dispositivo_id} not found')
        
        # Build queryset based on options
        if force:
            queryset = Dispositivo.objects.all()
            self.stdout.write(
                self.style.WARNING('\n🔄 Force mode: Re-generating embeddings for all dispositivos')
            )
        else:
            queryset = Dispositivo.objects.filter(embedding__isnull=True)
        
        # Filter by norma if specified
        if norma_id:
            queryset = queryset.filter(norma_id=norma_id)
            self.stdout.write(
                self.style.WARNING(f'\n📝 Filtering by Norma ID={norma_id}')
            )
        
        # Apply ordering, offset, and limit
        queryset = queryset.select_related('norma').order_by('id')[offset:]
        if limit:
            queryset = queryset[:limit]
        
        total = queryset.count()
        
        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    '\n⚠️  No dispositivos found matching criteria. '
                    'Try --force flag to regenerate embeddings.'
                )
            )
            return
        
        self.stdout.write(
            self.style.NOTICE(f'\n📊 Found {total} dispositivo(s) to process')
        )
        self.stdout.write(self.style.NOTICE(f'   Offset: {offset}'))
        self.stdout.write(self.style.NOTICE(f'   Limit: {limit if limit else "None (all)"}'))
        self.stdout.write(self.style.NOTICE(f'   Model: {model}'))
        self.stdout.write(
            self.style.NOTICE(f'   Mode: {"Synchronous (blocking)" if sync_mode else "Async (Celery)"}')
        )
        self.stdout.write(self.style.NOTICE('-' * 80))
        
        # Process dispositivos
        success_count = 0
        failure_count = 0
        
        for idx, dispositivo in enumerate(queryset, start=1):
            self.stdout.write(
                f'\n[{idx}/{total}] Processing: {dispositivo} (ID={dispositivo.id})'
            )
            
            try:
                if sync_mode:
                    # Synchronous execution (blocking)
                    result = generate_embedding_task(dispositivo.id, model=model)
                    
                    if result.get('success'):
                        success_count += 1
                        self.stdout.write(
                            self.style.SUCCESS(
                                f'  ✓ SUCCESS: dimension={result.get("embedding_dimension", 0)}, '
                                f'text_length={result.get("text_length", 0)}, '
                                f'time={result.get("processing_time", 0):.2f}s'
                            )
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
                    task = generate_embedding_task.delay(dispositivo.id, model=model)
                    success_count += 1
                    self.stdout.write(
                        self.style.SUCCESS(f'  ✓ Task dispatched: {task.id}')
                    )
                    
            except Exception as e:
                failure_count += 1
                self.stdout.write(
                    self.style.ERROR(f'  ✗ ERROR: {str(e)}')
                )
                logger.error(f'Error processing Dispositivo {dispositivo.id}: {e}', exc_info=True)
        
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
            self.stdout.write(f'  Embedding dimension: {result.get("embedding_dimension", 0)}')
            self.stdout.write(f'  Text length: {result.get("text_length", 0)}')
            self.stdout.write(f'  Model: {result.get("model", "unknown")}')
            self.stdout.write(f'  Processing time: {result.get("processing_time", 0):.2f}s')
        else:
            self.stdout.write(self.style.ERROR('\n✗ FAILED'))
            self.stdout.write(self.style.ERROR(f'  Error: {result.get("error", "Unknown")}'))

