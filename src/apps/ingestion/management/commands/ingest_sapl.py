"""
Django management command para ingestão manual de normas do SAPL.

Uso:
    python manage.py ingest_sapl --limit 50
    python manage.py ingest_sapl --ano 2024 --tipo "Lei Ordinária"
    python manage.py ingest_sapl --ano-inicio 2020 --ano-fim 2025 --auto-download
"""

from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.tasks import _process_norma_data, ingest_normas_task
from src.clients.sapl.sapl_client import SaplAPIClient


class Command(BaseCommand):
    help = "Ingere normas jurídicas da API SAPL"

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=50,
            help="Número máximo de normas a buscar (padrão: 50). Ignorado se usar --ano-inicio/--ano-fim",
        )
        parser.add_argument(
            "--offset",
            type=int,
            default=0,
            help="Offset para paginação (padrão: 0). Ignorado se usar --ano-inicio/--ano-fim",
        )
        parser.add_argument(
            "--tipo", type=str, default=None, help='Filtro por tipo de norma (ex: "Lei Ordinária")'
        )
        parser.add_argument(
            "--ano",
            type=int,
            default=None,
            help="Filtro por ano único (ex: 2024). Use --ano-inicio/--ano-fim para intervalo",
        )
        parser.add_argument(
            "--ano-inicio",
            type=int,
            default=None,
            help="Ano inicial do intervalo (ex: 2020). Requer --ano-fim",
        )
        parser.add_argument(
            "--ano-fim",
            type=int,
            default=None,
            help="Ano final do intervalo (ex: 2025). Requer --ano-inicio",
        )
        parser.add_argument(
            "--async", action="store_true", help="Executar de forma assíncrona via Celery"
        )
        parser.add_argument(
            "--auto-download",
            action="store_true",
            help="Baixar PDFs automaticamente após ingestão (requer worker ativo)",
        )

    def handle(self, *args, **options):
        limit = options["limit"]
        offset = options["offset"]
        tipo = options["tipo"]
        ano = options["ano"]
        ano_inicio = options["ano_inicio"]
        ano_fim = options["ano_fim"]
        is_async = options["async"]
        auto_download = options["auto_download"]

        # Validar argumentos de intervalo de ano
        if (ano_inicio is not None) != (ano_fim is not None):
            raise CommandError("--ano-inicio e --ano-fim devem ser especificados juntos")

        if ano_inicio and ano_fim:
            if ano_inicio > ano_fim:
                raise CommandError(
                    f"--ano-inicio ({ano_inicio}) deve ser menor ou igual a --ano-fim ({ano_fim})"
                )

        # Se intervalo de anos especificado, usar estratégia de busca por ano
        if ano_inicio and ano_fim:
            self._handle_year_range_ingestion(
                ano_inicio=ano_inicio,
                ano_fim=ano_fim,
                tipo=tipo,
                auto_download=auto_download,
                is_async=is_async,
            )
            return

        # Caso contrário, usar método tradicional
        self.stdout.write(
            self.style.NOTICE(
                f"Iniciando ingestão: limit={limit}, offset={offset}, "
                f"tipo={tipo}, ano={ano}, auto_download={auto_download}"
            )
        )

        try:
            if is_async:
                # Executar via Celery (assíncrono)
                task = ingest_normas_task.delay(
                    limit=limit, offset=offset, tipo=tipo, ano=ano, auto_download=auto_download
                )
                self.stdout.write(self.style.SUCCESS(f"Task Celery iniciada: {task.id}"))
                if auto_download:
                    self.stdout.write(
                        self.style.NOTICE("Downloads de PDFs serão disparados automaticamente")
                    )
                self.stdout.write('Use "celery -A config inspect active" para monitorar')
            else:
                # Executar síncronamente (bloqueante)
                stats = ingest_normas_task(
                    limit=limit, offset=offset, tipo=tipo, ano=ano, auto_download=auto_download
                )

                self.stdout.write(
                    self.style.SUCCESS(
                        f'\nIngestão concluída:\n'
                        f'  - Total buscadas: {stats["total_fetched"]}\n'
                        f'  - Criadas: {stats["created"]}\n'
                        f'  - Atualizadas: {stats["updated"]}\n'
                        f'  - Falhas: {stats["failed"]}\n'
                        f'  - Downloads disparados: {len(stats.get("download_tasks", []))}'
                    )
                )

                if stats["errors"]:
                    self.stdout.write(self.style.WARNING("\nErros encontrados:"))
                    for error in stats["errors"][:10]:  # Mostrar até 10 erros
                        self.stdout.write(f"  - {error}")

                    if len(stats["errors"]) > 10:
                        self.stdout.write(f'  ... e mais {len(stats["errors"]) - 10} erro(s)')

        except Exception as e:
            raise CommandError(f"Falha na ingestão: {str(e)}") from e

    def _handle_year_range_ingestion(
        self, ano_inicio: int, ano_fim: int, tipo: str | None, auto_download: bool, is_async: bool
    ):
        """
        Processa ingestão usando estratégia de busca por intervalo de anos.
        """
        self.stdout.write(self.style.WARNING("=" * 80))
        self.stdout.write(
            self.style.WARNING(f"INGESTÃO POR INTERVALO DE ANOS: {ano_inicio} - {ano_fim}")
        )
        self.stdout.write(self.style.WARNING("=" * 80))
        self.stdout.write("")

        client = None

        try:
            # Buscar normas usando estratégia de intervalo de anos
            self.stdout.write(
                self.style.NOTICE(f"Buscando normas da API SAPL (anos {ano_inicio} a {ano_fim})...")
            )
            client = SaplAPIClient()

            normas_data = client.fetch_normas_by_year_range(
                ano_inicio=ano_inicio, ano_fim=ano_fim, tipo=tipo, max_normas_por_ano=None
            )

            total_encontradas = len(normas_data)
            self.stdout.write(self.style.SUCCESS(f"✓ {total_encontradas} normas encontradas"))

            if total_encontradas == 0:
                self.stdout.write(self.style.WARNING("Nenhuma norma encontrada. Abortando."))
                return

            # Processar cada norma
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("Processando normas no banco..."))

            stats = {
                "processed": 0,
                "created": 0,
                "updated": 0,
                "failed": 0,
                "download_tasks": [],
                "errors": [],
            }

            for idx, norma_data in enumerate(normas_data, 1):
                try:
                    result = _process_norma_data(norma_data, auto_download=False)

                    if result["created"]:
                        stats["created"] += 1
                    else:
                        stats["updated"] += 1

                    # Disparar download se solicitado
                    if auto_download and result.get("norma_id"):
                        norma_id = result["norma_id"]
                        if is_async:
                            from src.apps.ingestion.tasks import download_pdf_task

                            task = download_pdf_task.delay(norma_id)
                            stats["download_tasks"].append(task.id)
                        else:
                            stats["download_tasks"].append(norma_id)

                    stats["processed"] += 1

                    if idx % 50 == 0:
                        self.stdout.write(f"  Progresso: {idx}/{total_encontradas}...")

                except Exception as e:
                    stats["failed"] += 1
                    error_msg = f"Norma ID {norma_data.get('id')}: {str(e)}"
                    stats["errors"].append(error_msg)

            # Resumo
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("=" * 80))
            self.stdout.write(self.style.SUCCESS("RESUMO DA INGESTÃO"))
            self.stdout.write(self.style.SUCCESS("=" * 80))
            self.stdout.write(f'  ✓ Normas processadas: {stats["processed"]}')
            self.stdout.write(f'  ✓ Novas criadas: {stats["created"]}')
            self.stdout.write(f'  ✓ Atualizadas: {stats["updated"]}')
            self.stdout.write(f'  ✗ Falhas: {stats["failed"]}')

            if auto_download:
                self.stdout.write(f'  📥 Downloads agendados: {len(stats["download_tasks"])}')

            if stats["errors"]:
                self.stdout.write(
                    self.style.WARNING(f'\n⚠️  {len(stats["errors"])} erro(s) encontrado(s)')
                )
                for error in stats["errors"][:5]:
                    self.stdout.write(f"  - {error}")

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("✅ Ingestão concluída!"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Erro fatal: {str(e)}"))
            raise CommandError(f"Falha na ingestão por intervalo de anos: {str(e)}") from e

        finally:
            if client:
                client.close()
