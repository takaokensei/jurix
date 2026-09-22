"""
Django Management Command: bulk_embed

Triggers embedding generation for dispositivos.
Dispatches generate_embedding_task for dispositivos without embeddings.
"""

import logging

from django.core.management import call_command
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = (
        'Generate embeddings for dispositivos using Ollama. '
        'Dispatches Celery task generate_embedding_task for each dispositivo.'
    )

    def add_arguments(self, parser):
        """Define command arguments."""
        parser.add_argument(
            '--all',
            action='store_true',
            help='Process all dispositivos without embeddings (default behavior if no limit specified)'
        )

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
        parser.add_argument(
            '--batch-size',
            type=int,
            default=16,
            help='Items per Ollama /api/embed request; delegates to bulk_embed_batch.',
        )

    def handle(self, *args, **options):
        """Execute the bulk embedding generation."""
        # Compatibility facade: use one operational implementation for bulk embedding.
        call_command(
            'bulk_embed_batch',
            batch_size=options['batch_size'],
            limit=options.get('limit'),
            offset=options['offset'],
            force=options['force'],
            model=options['model'],
            dispositivo_id=options.get('dispositivo_id'),
            norma_id=options.get('norma_id'),
        )
        return
