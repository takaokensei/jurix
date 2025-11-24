"""
Django management command para ingestão manual de normas do SAPL.

Uso:
    python manage.py ingest_sapl --limit 50
    python manage.py ingest_sapl --ano 2024 --tipo "Lei Ordinária"
"""

from django.core.management.base import BaseCommand, CommandError
from src.apps.ingestion.tasks import ingest_normas_task


class Command(BaseCommand):
    help = 'Ingere normas jurídicas da API SAPL'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--limit',
            type=int,
            default=50,
            help='Número máximo de normas a buscar (padrão: 50)'
        )
        parser.add_argument(
            '--offset',
            type=int,
            default=0,
            help='Offset para paginação (padrão: 0)'
        )
        parser.add_argument(
            '--tipo',
            type=str,
            default=None,
            help='Filtro por tipo de norma (ex: "Lei Ordinária")'
        )
        parser.add_argument(
            '--ano',
            type=int,
            default=None,
            help='Filtro por ano (ex: 2024)'
        )
        parser.add_argument(
            '--async',
            action='store_true',
            help='Executar de forma assíncrona via Celery'
        )
    
    def handle(self, *args, **options):
        limit = options['limit']
        offset = options['offset']
        tipo = options['tipo']
        ano = options['ano']
        is_async = options['async']
        
        self.stdout.write(self.style.NOTICE(
            f'Iniciando ingestão: limit={limit}, offset={offset}, '
            f'tipo={tipo}, ano={ano}'
        ))
        
        try:
            if is_async:
                # Executar via Celery (assíncrono)
                task = ingest_normas_task.delay(
                    limit=limit,
                    offset=offset,
                    tipo=tipo,
                    ano=ano
                )
                self.stdout.write(self.style.SUCCESS(
                    f'Task Celery iniciada: {task.id}'
                ))
                self.stdout.write(
                    'Use "celery -A config inspect active" para monitorar'
                )
            else:
                # Executar síncronamente (bloqueante)
                stats = ingest_normas_task(
                    limit=limit,
                    offset=offset,
                    tipo=tipo,
                    ano=ano
                )
                
                self.stdout.write(self.style.SUCCESS(
                    f'\nIngestão concluída:\n'
                    f'  - Total buscadas: {stats["total_fetched"]}\n'
                    f'  - Criadas: {stats["created"]}\n'
                    f'  - Atualizadas: {stats["updated"]}\n'
                    f'  - Falhas: {stats["failed"]}'
                ))
                
                if stats['errors']:
                    self.stdout.write(self.style.WARNING(
                        f'\nErros encontrados:'
                    ))
                    for error in stats['errors'][:10]:  # Mostrar até 10 erros
                        self.stdout.write(f'  - {error}')
                    
                    if len(stats['errors']) > 10:
                        self.stdout.write(
                            f'  ... e mais {len(stats["errors"]) - 10} erro(s)'
                        )
        
        except Exception as e:
            raise CommandError(f'Falha na ingestão: {str(e)}')

