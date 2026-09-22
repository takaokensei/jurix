"""
Django Management Command: bulk_embed_batch

Optimized batch processing for embedding generation.
Processes multiple dispositivos in batches to reduce API calls to Ollama.
"""

import logging
import time

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from src.apps.legislation.models import Dispositivo
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service

logger = logging.getLogger(__name__)


def generate_embeddings_batch(
    ollama: OllamaService, texts: list[str], model: str
) -> list[list[float]] | None:
    """Use Ollama's batch endpoint, with legacy single-input fallback."""
    if not texts:
        return []
    if any(not text.strip() for text in texts):
        raise ValueError('Embedding inputs must not be empty')
    try:
        response = ollama.session.post(
            f'{ollama.base_url}/api/embed',
            json={'model': model, 'input': texts},
            timeout=ollama.timeout,
        )
        if response.status_code == 200:
            embeddings = response.json().get('embeddings', [])
            return embeddings if len(embeddings) == len(texts) else None
        if response.status_code not in (404, 405):
            logger.error('Ollama /api/embed returned HTTP %s', response.status_code)
            return None
    except Exception:
        logger.warning('Ollama batch embedding request failed', exc_info=True)
        return None
    return [ollama.generate_embedding(text, model=model) for text in texts]


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
            default=None,
            help='Ollama embedding model (default: OLLAMA_EMBEDDING_MODEL)',
        )

        parser.add_argument(
            '--use-cache',
            dest='use_cache',
            action='store_true',
            default=True,
            help='Use Redis cache for embeddings (default: True)'
        )

        parser.add_argument(
            '--no-cache', dest='use_cache', action='store_false',
            help='Disable Redis embedding cache',
        )

        parser.add_argument('--dispositivo-id', type=int, default=None)
        parser.add_argument('--norma-id', type=int, default=None)
        parser.add_argument(
            '--sync', action='store_true',
            help='Compatibility flag; this command is synchronous.',
        )

    def handle(self, *args, **options):
        """Execute the batch embedding generation."""
        batch_size: int = options['batch_size']
        limit: int | None = options.get('limit')
        offset: int = options['offset']
        force: bool = options['force']
        model: str = options['model'] or settings.OLLAMA_EMBEDDING_MODEL
        use_cache: bool = options['use_cache']
        dispositivo_id: int | None = options.get('dispositivo_id')
        norma_id: int | None = options.get('norma_id')

        if batch_size <= 0:
            raise CommandError('--batch-size must be greater than zero')

        self.stdout.write(self.style.NOTICE('=' * 80))
        self.stdout.write(self.style.NOTICE('Batch Embedding Generation - Optimized'))
        self.stdout.write(self.style.NOTICE('=' * 80))

        # Build queryset
        if dispositivo_id is not None:
            queryset = Dispositivo.objects.filter(id=dispositivo_id)
        elif force:
            queryset = Dispositivo.objects.all()
            self.stdout.write(
                self.style.WARNING('\n🔄 Force mode: Re-generating all embeddings')
            )
        else:
            queryset = Dispositivo.objects.filter(
                Q(embedding__isnull=True) | ~Q(embedding_model=model)
            )

        if norma_id:
            queryset = queryset.filter(norma_id=norma_id)

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
            pending: list[tuple[Dispositivo, str]] = []
            embeddings_by_id: dict[int, list[float]] = {}
            for disp in batch:
                norma = disp.norma
                context_parts = [
                    f"{norma.tipo} {norma.numero}/{norma.ano}",
                    f"{disp.get_full_identifier()}",
                    disp.texto,
                ]
                if disp.dispositivo_pai:
                    context_parts.insert(2, f"Contexto: {disp.dispositivo_pai}")
                embedding_text = " | ".join(context_parts)
                embedding = cache.get_embedding(embedding_text, model) if cache else None
                if embedding:
                    embeddings_by_id[disp.id] = embedding
                    cache_hits += 1
                else:
                    pending.append((disp, embedding_text))

            if pending:
                texts = [text for _, text in pending]
                generated = generate_embeddings_batch(ollama, texts, model)
                if (
                    generated is None
                    or len(generated) != len(pending)
                    or any(e is None for e in generated)
                ):
                    failure_count += len(pending)
                    logger.error('Unexpected batch embedding result for %s items', len(pending))
                else:
                    for (disp, text), embedding in zip(pending, generated, strict=True):
                        if len(embedding) != 768:
                            failure_count += 1
                            logger.error(
                                'Unexpected embedding dimension for Dispositivo ID=%s: '
                                'expected=768 got=%s',
                                disp.id, len(embedding),
                            )
                            continue
                        embeddings_by_id[disp.id] = embedding
                        if cache:
                            try:
                                cache.set_embedding(text, model, embedding)
                            except Exception:
                                logger.warning(
                                    'Embedding cache write failed for Dispositivo ID=%s',
                                    disp.id, exc_info=True,
                                )

            to_update = []
            for disp in batch:
                embedding = embeddings_by_id.get(disp.id)
                if embedding is None:
                    continue
                disp.embedding = embedding
                disp.embedding_model = model
                disp.embedding_generated_at = timezone.now()
                to_update.append(disp)

            if to_update:
                Dispositivo.objects.bulk_update(
                    to_update,
                    ['embedding', 'embedding_model', 'embedding_generated_at', 'updated_at'],
                    batch_size=batch_size,
                )
                success_count += len(to_update)

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
