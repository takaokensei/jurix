"""
Django Management Command: bulk_embed_batch

Optimized batch processing for embedding generation.
Processes multiple dispositivos in batches to reduce API calls to Ollama.
"""

import logging
from typing import List, Dict, Any
import time

from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q

from src.apps.legislation.models import Dispositivo
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Generate embeddings for dispositivos using batch processing. '
        'Optimized version that processes multiple items per API call.'
    )
    
    def add_arguments(self, parser):
        """Define command arguments."""
        parser.add_argument(
            '--batch-size',
            type=int,
            default=10,
            help='Number of dispositivos to process per batch (default: 10)'
        )
        
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Maximum number of dispositivos to process (default: all)'
        )
        
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Skip this many dispositivos before starting (default: 0)'
        )
        
        parser.add_argument(
            '--force',
            action='store_true',
            help='Force re-generation of embeddings for dispositivos that already have them'
        )
        
        parser.add_argument(
            '--model',
            type=str,
            default='nomic-embed-text',
            help='Ollama model to use for embeddings (default: nomic-embed-text)'
        )
        
        parser.add_argument(
            '--use-cache',
            action='store_true',
            default=True,
            help='Use Redis cache for embeddings (default: True)'
        )
    
    def handle(self, *args, **options):
        """Execute the batch embedding generation."""
        batch_size: int = options['batch_size']
        limit: int = options.get('limit')
        offset: int = options['offset']
        force: bool = options['force']
        model: str = options['model']
        use_cache: bool = options['use_cache']
        
        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(self.style.NOTICE('Batch Embedding Generation - Optimized'))
        self.stdout.write(self.style.NOTICE('=' * 80))
        
        # Build queryset
        if force:
            queryset = Dispositivo.objects.all()
            self.stdout.write(
                self.style.WARNING('\n🔄 Force mode: Re-generating all embeddings')
            )
        else:
            queryset = Dispositivo.objects.filter(
                Q(embedding__isnull=True) | Q(embedding=[])
            )
        
        # Apply ordering, offset, and limit
        queryset = queryset.select_related('norma', 'dispositivo_pai').order_by('id')[offset:]
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
        self.stdout.write(self.style.NOTICE(f'   Batch size: {batch_size}'))
        self.stdout.write(self.style.NOTICE(f'   Model: {model}'))
        self.stdout.write(self.style.NOTICE(f'   Cache: {"Enabled" if use_cache else "Disabled"}'))
        self.stdout.write(self.style.NOTICE('-' * 80))
        
        # Initialize services
        ollama = OllamaService(model=model)
        cache = get_cache_service() if use_cache else None
        
        # Check Ollama health
        if not ollama.check_health():
            raise CommandError('Ollama service is not accessible at configured URL')
        
        # Process in batches
        success_count = 0
        failure_count = 0
        cache_hits = 0
        start_time = time.time()
        
        dispositivos = list(queryset)
        batches = [dispositivos[i:i + batch_size] for i in range(0, len(dispositivos), batch_size)]
        
        for batch_idx, batch in enumerate(batches, 1):
            self.stdout.write(
                f'\n[Batch {batch_idx}/{len(batches)}] Processing {len(batch)} dispositivos...'
            )
            
            batch_start = time.time()
            
            # Process each dispositivo in the batch
            for disp in batch:
                try:
                    # Prepare text for embedding
                    norma = disp.norma
                    context_parts = [
                        f"{norma.tipo} {norma.numero}/{norma.ano}",
                        f"{disp.get_full_identifier()}",
                        disp.texto
                    ]
                    
                    if disp.dispositivo_pai:
                        context_parts.insert(2, f"Contexto: {disp.dispositivo_pai}")
                    
                    embedding_text = " | ".join(context_parts)
                    
                    # Try cache first
                    embedding = None
                    if use_cache and cache:
                        embedding = cache.get_embedding(embedding_text, model)
                        if embedding:
                            cache_hits += 1
                    
                    # Generate embedding if not cached
                    if not embedding:
                        embedding = ollama.generate_embedding(embedding_text, model=model)
                        
                        if not embedding:
                            raise Exception("Failed to generate embedding (None returned)")
                        
                        # Cache the generated embedding
                        if use_cache and cache:
                            cache.set_embedding(embedding_text, model, embedding)
                    
                    # Store embedding
                    from datetime import datetime
                    disp.embedding = embedding
                    disp.embedding_model = model
                    disp.embedding_generated_at = datetime.now()
                    disp.save(update_fields=['embedding', 'embedding_model', 'embedding_generated_at', 'updated_at'])
                    
                    success_count += 1
                    
                except Exception as e:
                    failure_count += 1
                    self.stdout.write(
                        self.style.ERROR(f'  ✗ Failed: {disp} - {str(e)}')
                    )
                    logger.error(f'Error processing Dispositivo {disp.id}: {e}', exc_info=True)
            
            batch_time = time.time() - batch_start
            self.stdout.write(
                self.style.SUCCESS(
                    f'  ✓ Batch completed in {batch_time:.2f}s '
                    f'({len(batch)/batch_time:.1f} items/sec)'
                )
            )
        
        # Summary
        total_time = time.time() - start_time
        
        self.stdout.write(self.style.NOTICE('\n' + '=' * 80))
        self.stdout.write(self.style.NOTICE('SUMMARY'))
        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(f'Total processed: {total}')
        self.stdout.write(self.style.SUCCESS(f'✓ Success: {success_count}'))
        
        if failure_count > 0:
            self.stdout.write(self.style.ERROR(f'✗ Failures: {failure_count}'))
        
        if use_cache:
            self.stdout.write(self.style.WARNING(f'🔥 Cache hits: {cache_hits}'))
            cache_hit_rate = (cache_hits / total * 100) if total > 0 else 0
            self.stdout.write(f'   Cache hit rate: {cache_hit_rate:.1f}%')
        
        self.stdout.write(f'\n⏱️  Total time: {total_time:.2f}s')
        self.stdout.write(f'   Average: {total/total_time:.1f} items/sec')
        self.stdout.write(self.style.NOTICE('=' * 80))

