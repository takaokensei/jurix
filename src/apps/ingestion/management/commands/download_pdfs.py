"""
Django management command para download em massa de PDFs de normas.

Uso:
    python manage.py download_pdfs --all
    python manage.py download_pdfs --limit 50
    python manage.py download_pdfs --status pending
"""

from django.core.management.base import BaseCommand, CommandError
from src.apps.legislation.models import Norma
from src.apps.ingestion.tasks import download_pdf_task


class Command(BaseCommand):
    help = 'Baixa PDFs de normas do SAPL de forma assíncrona'
    
    def add_arguments(self, parser):
        parser.add_argument(
            '--all',
            action='store_true',
            help='Baixar PDFs de todas as normas sem PDF local'
        )
        parser.add_argument(
            '--limit',
            type=int,
            default=None,
            help='Limitar número de downloads'
        )
        parser.add_argument(
            '--status',
            type=str,
            default='pending',
            help='Filtrar por status da norma (padrão: pending)'
        )
        parser.add_argument(
            '--sync',
            action='store_true',
            help='Executar downloads de forma síncrona (bloqueante)'
        )
        parser.add_argument(
            '--force',
            action='store_true',
            help='Reprocessar normas que já têm PDF (sobrescrever)'
        )
    
    def handle(self, *args, **options):
        download_all = options['all']
        limit = options['limit']
        status = options['status']
        is_sync = options['sync']
        force = options['force']
        
        # Construir queryset
        if force:
            # Baixar todas, independente de já terem PDF
            queryset = Norma.objects.filter(status=status) if status else Norma.objects.all()
        else:
            # Baixar apenas as que não têm PDF local
            if download_all:
                # Se --all, buscar todas as normas sem PDF, independente do status
                queryset = Norma.objects.filter(
                    pdf_path__isnull=True
                ) | Norma.objects.filter(pdf_path='')
                queryset = queryset.exclude(pdf_url='')
            else:
                # Filtrar por status se especificado
                queryset = Norma.objects.filter(
                    status=status,
                    pdf_path__isnull=True
                ) | Norma.objects.filter(
                    status=status,
                    pdf_path=''
                )
                queryset = queryset.exclude(pdf_url='')
        
        # Aplicar limite se especificado
        if limit:
            queryset = queryset[:limit]
        elif not download_all:
            # Se não passou --all nem --limit, pedir confirmação
            count = queryset.count()
            if count > 10:
                self.stdout.write(self.style.WARNING(
                    f'Você está prestes a baixar PDFs de {count} normas.'
                ))
                confirm = input('Deseja continuar? (s/N): ')
                if confirm.lower() != 's':
                    self.stdout.write(self.style.ERROR('Operação cancelada'))
                    return
        
        normas = list(queryset)
        total = len(normas)
        
        if total == 0:
            self.stdout.write(self.style.WARNING(
                'Nenhuma norma encontrada para download'
            ))
            return
        
        self.stdout.write(self.style.NOTICE(
            f'Iniciando download de {total} PDF(s)...'
        ))
        
        if is_sync:
            self.stdout.write(self.style.WARNING(
                'Modo SÍNCRONO ativado. Isso pode demorar...'
            ))
        
        success_count = 0
        failed_count = 0
        task_ids = []
        
        for i, norma in enumerate(normas, 1):
            self.stdout.write(f'[{i}/{total}] Processando {norma}...')
            
            try:
                if is_sync:
                    # Executar síncronamente
                    result = download_pdf_task(norma.id)
                    if result['success']:
                        success_count += 1
                        self.stdout.write(self.style.SUCCESS(
                            f'  ✓ PDF baixado: {result["path"]}'
                        ))
                    else:
                        failed_count += 1
                        self.stdout.write(self.style.ERROR(
                            f'  ✗ Falha: {result.get("error", "Erro desconhecido")}'
                        ))
                else:
                    # Executar assíncronamente via Celery
                    task = download_pdf_task.delay(norma.id)
                    task_ids.append(task.id)
                    self.stdout.write(self.style.NOTICE(
                        f'  → Task disparada: {task.id}'
                    ))
            
            except Exception as e:
                failed_count += 1
                self.stdout.write(self.style.ERROR(
                    f'  ✗ Erro crítico: {str(e)}'
                ))
        
        # Resumo
        self.stdout.write('\n' + '='*50)
        if is_sync:
            self.stdout.write(self.style.SUCCESS(
                f'\nDownload concluído:\n'
                f'  - Sucessos: {success_count}\n'
                f'  - Falhas: {failed_count}\n'
                f'  - Total: {total}'
            ))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'\nTasks disparadas: {len(task_ids)}\n'
            ))
            self.stdout.write(self.style.NOTICE(
                'Use os comandos abaixo para monitorar:\n'
                '  docker-compose logs -f worker\n'
                '  docker-compose exec worker celery -A config inspect active'
            ))

