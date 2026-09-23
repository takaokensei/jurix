"""Diagnose SAPL connectivity and pagination without mutating the corpus."""
from __future__ import annotations

from django.core.management.base import BaseCommand, CommandError

from src.clients.sapl.sapl_client import SAPLClient


class Command(BaseCommand):
    help = "Testa a API do SAPL e diagnostica paginação repetida/limitada."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--max-pages", type=int, default=4)

    def handle(self, *args, **options):
        client = SAPLClient()
        limit = max(1, min(options["limit"], 100))
        max_pages = max(1, min(options["max_pages"], 50))
        self.stdout.write(f"SAPL base: {client.base_url}")
        seen = set()
        total = 0
        offset = 0

        for page_no in range(1, max_pages + 1):
            try:
                payload = client.fetch_normas(limit=limit, offset=offset)
            except Exception as exc:
                raise CommandError(f"Falha consultando SAPL na página {page_no}: {exc}") from exc
            if not isinstance(payload, dict):
                raise CommandError(f"Resposta SAPL inesperada na página {page_no}: {type(payload).__name__}")
            results = payload.get("results") or payload.get("objects") or []
            ids = tuple(str(item.get("id")) for item in results if isinstance(item, dict) and item.get("id") is not None)
            unique = len(set(ids))
            self.stdout.write(
                f"Página {page_no}: {len(results)} registros, {unique} IDs únicos, offset={offset}, total acumulado={total + unique}"
            )
            if ids and ids in seen:
                self.stdout.write(self.style.WARNING("SAPL repetiu exatamente a mesma página; paginação por offset não é confiável."))
                break
            if ids:
                seen.add(ids)
                total += unique
            if len(results) < limit:
                break
            offset += limit

        if total == 0:
            self.stdout.write(self.style.WARNING("Nenhum registro retornado. Verifique URL, autenticação ou bloqueio do SAPL."))
        else:
            self.stdout.write(self.style.SUCCESS(f"Diagnóstico concluído: {total} registros distintos observados."))
