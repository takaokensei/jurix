"""
Django Management Command: clear_vector_data

Clears all vector embeddings from the database to resolve dimension conflicts.
Useful when migrating between embedding models with different dimensions.
"""

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = (
        'Clear all vector embeddings from Dispositivo table. '
        'Use this to resolve dimension conflicts before regenerating embeddings.'
    )

    def add_arguments(self, parser):
        parser.add_argument(
            '--recreate-column',
            action='store_true',
            help='Recreate the embedding column with correct dimensions (768)'
        )

    def handle(self, *args, **options):
        recreate = options['recreate_column']
        
        self.stdout.write(self.style.WARNING('=' * 80))
        self.stdout.write(self.style.WARNING('Vector Data Cleanup'))
        self.stdout.write(self.style.WARNING('=' * 80))
        
        with connection.cursor() as cursor:
            if recreate:
                self.stdout.write(self.style.NOTICE('Recreating embedding column...'))
                cursor.execute(
                    'ALTER TABLE legislation_dispositivo DROP COLUMN IF EXISTS embedding;'
                )
                cursor.execute(
                    'ALTER TABLE legislation_dispositivo ADD COLUMN embedding vector(768);'
                )
                self.stdout.write(
                    self.style.SUCCESS('✓ Column recreated with dimension 768')
                )
            else:
                self.stdout.write(self.style.NOTICE('Clearing all embeddings...'))
                cursor.execute('UPDATE legislation_dispositivo SET embedding = NULL')
                affected = cursor.rowcount
                self.stdout.write(
                    self.style.SUCCESS(f'✓ Cleared embeddings for {affected} dispositivos')
                )
        
        self.stdout.write(self.style.SUCCESS('=' * 80))
        self.stdout.write(self.style.SUCCESS('Cleanup completed successfully!'))

