"""
Django Management Command: bulk_ingest_all

Ingere TODAS as normas disponíveis na API SAPL usando fetch_all_normas com paginação automática.
"""

import logging

from django.core.management.base import BaseCommand

from src.apps.ingestion.tasks import _process_norma_data, download_pdf_task
from src.clients.sapl.sapl_client import SaplAPIClient

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Ingere TODAS as normas disponíveis da API SAPL usando paginação automática"

    def add_arguments(self, parser):
        parser.add_argument(
            "--max-normas",
            type=int,
            default=None,
            help="Número máximo de normas a buscar (None = todas disponíveis)",
        )
        parser.add_argument("--tipo", type=str, default=None, help="Filtro por tipo de norma")
        parser.add_argument("--ano", type=int, default=None, help="Filtro por ano")
        parser.add_argument(
            "--auto-download", action="store_true", help="Baixar PDFs automaticamente após ingestão"
        )
        parser.add_argument(
            "--async", action="store_true", help="Executar downloads via Celery (assíncrono)"
        )

    def handle(self, *args, **options):
        max_normas = options["max_normas"]
        tipo = options["tipo"]
        ano = options["ano"]
        auto_download = options["auto_download"]
        is_async = options["async"]

        self.stdout.write(self.style.WARNING("=" * 80))
        self.stdout.write(self.style.WARNING("INGESTÃO MASSIVA DE NORMAS SAPL"))
        self.stdout.write(self.style.WARNING("=" * 80))

        client = None

        try:
            # Buscar todas as normas usando fetch_all_normas (paginação automática)
            self.stdout.write(
                self.style.NOTICE("🔍 Buscando normas da API SAPL (paginação automática)...")
            )
            client = SaplAPIClient()

            normas_data = client.fetch_all_normas(
                max_normas=max_normas, tipo=tipo, ano=ano, page_size=50
            )

            total_found = len(normas_data)
            self.stdout.write(self.style.SUCCESS(f"✓ {total_found} normas encontradas na API SAPL"))

            if total_found == 0:
                self.stdout.write(self.style.WARNING("⚠️  Nenhuma norma encontrada. Abortando."))
                return

            # Processar cada norma
            self.stdout.write("")
            self.stdout.write(self.style.NOTICE("📥 Processando normas no banco..."))

            stats = {"created": 0, "updated": 0, "failed": 0, "download_tasks": [], "errors": []}

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
                            task = download_pdf_task.delay(norma_id)
                            stats["download_tasks"].append(task.id)
                        else:
                            # Download síncrono será feito depois
                            stats["download_tasks"].append(norma_id)

                    if idx % 10 == 0:
                        self.stdout.write(f"  Progresso: {idx}/{total_found}...")

                except Exception as e:
                    stats["failed"] += 1
                    error_msg = f"Norma ID {norma_data.get('id')}: {str(e)}"
                    stats["errors"].append(error_msg)
                    logger.error(error_msg)

            # Resumo
            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("=" * 80))
            self.stdout.write(self.style.SUCCESS("RESUMO DA INGESTÃO"))
            self.stdout.write(self.style.SUCCESS("=" * 80))
            self.stdout.write(f"  ✓ Normas processadas: {stats['created'] + stats['updated']}")
            self.stdout.write(f"  ✓ Novas criadas: {stats['created']}")
            self.stdout.write(f"  ✓ Atualizadas: {stats['updated']}")
            self.stdout.write(f"  ✗ Falhas: {stats['failed']}")

            if auto_download:
                self.stdout.write(f"  📥 Downloads agendados: {len(stats['download_tasks'])}")
                if is_async:
                    self.stdout.write(self.style.NOTICE("💡 Downloads via Celery (assíncrono)"))

            if stats["errors"]:
                self.stdout.write(
                    self.style.WARNING(f"\n⚠️  {len(stats['errors'])} erro(s) encontrado(s)")
                )

            self.stdout.write("")
            self.stdout.write(self.style.SUCCESS("✅ Ingestão concluída!"))

        except Exception as e:
            self.stdout.write(self.style.ERROR(f"❌ Erro fatal: {str(e)}"))
            logger.exception("Erro na ingestão massiva")
            raise

        finally:
            if client:
                client.close()
