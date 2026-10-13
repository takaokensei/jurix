"""Diagnose SAPL connectivity and pagination without mutating the corpus."""

from __future__ import annotations

import hashlib

from django.core.management.base import BaseCommand, CommandError

from src.clients.sapl.sapl_client import SaplAPIClient


class Command(BaseCommand):
    help = "Testa a API do SAPL e diagnostica paginação repetida/limitada."

    def add_arguments(self, parser):
        parser.add_argument("--limit", type=int, default=10)
        parser.add_argument("--max-pages", type=int, default=4)

    def handle(self, *args, **options):
        client = SaplAPIClient()
        limit = max(1, min(options["limit"], 100))
        max_pages = max(1, min(options["max_pages"], 50))
        self.stdout.write(f"SAPL base: {client.base_url}")
        seen_urls = set()
        seen_page_fingerprints = set()
        seen_ids = set()
        total = 0
        offset = 0
        requested_url = ""

        for page_no in range(1, max_pages + 1):
            try:
                page = (
                    client._make_request_url(requested_url)
                    if requested_url
                    else client.fetch_normas_page(limit=limit, offset=offset)
                )
            except Exception as exc:
                raise CommandError(f"Falha consultando SAPL na página {page_no}: {exc}") from exc
            if not isinstance(page, dict) or not isinstance(page.get("results"), list):
                raise CommandError(
                    f"Resposta SAPL inesperada na página {page_no}: {type(page).__name__}"
                )
            results = page["results"]
            ids = tuple(
                str(item.get("id"))
                for item in results
                if isinstance(item, dict) and item.get("id") is not None
            )
            unique = len(set(ids))
            if len(ids) != len(results) or unique != len(ids):
                raise CommandError(
                    f"Página SAPL {page_no} tem IDs ausentes ou repetidos; diagnóstico não certificado."
                )
            metadata = page.get("_jurix_pagination")
            page_index = metadata.get("page") if isinstance(metadata, dict) else page_no
            total_pages = metadata.get("total_pages") if isinstance(metadata, dict) else None
            total_entries = metadata.get("total_entries") if isinstance(metadata, dict) else None
            start_index = metadata.get("start_index") if isinstance(metadata, dict) else None
            end_index = metadata.get("end_index") if isinstance(metadata, dict) else None
            next_url = page.get("next")

            current_url = requested_url
            if not current_url and page_index:
                current_url = client.build_normas_page_url(int(page_index))
            if current_url:
                if current_url in seen_urls:
                    raise CommandError("SAPL repetiu a URL de uma página; diagnóstico não certificado.")
                seen_urls.add(current_url)

            self.stdout.write(
                f"Página {page_index}: {len(results)} registros, {unique} IDs únicos, "
                f"intervalo={start_index or 'n/d'}-{end_index or 'n/d'}, "
                f"total informado={total_entries or 'n/d'}, páginas informadas={total_pages or 'n/d'}"
            )

            page_fingerprint = hashlib.sha256(",".join(ids).encode("utf-8")).hexdigest()
            if ids and page_fingerprint in seen_page_fingerprints:
                raise CommandError("SAPL repetiu o conteúdo de uma página; diagnóstico não certificado.")
            if ids:
                seen_page_fingerprints.add(page_fingerprint)
                overlap = seen_ids.intersection(ids)
                if overlap:
                    overlap_count = len(overlap)
                    noun = "ID" if overlap_count == 1 else "IDs"
                    verb = "repetido" if overlap_count == 1 else "repetidos"
                    raise CommandError(
                        f"SAPL repetiu {overlap_count} {noun} {verb} entre páginas; "
                        "diagnóstico não certificado."
                    )
                    break
                seen_ids.update(ids)
                total += unique

            if not next_url:
                break
            try:
                requested_url = client.validate_pagination_url(next_url)
            except (TypeError, ValueError) as exc:
                raise CommandError("URL de paginação SAPL inválida; diagnóstico interrompido.") from exc
            offset = 0

        if total == 0:
            self.stdout.write(
                self.style.WARNING(
                    "Nenhum registro retornado. Verifique URL, autenticação ou bloqueio do SAPL."
                )
            )
        else:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Diagnóstico concluído: {total} registros distintos observados."
                )
            )
