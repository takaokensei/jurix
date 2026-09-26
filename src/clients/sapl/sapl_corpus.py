# ruff: noqa: F401,F403,E501,E701
from __future__ import annotations

import logging
import os
import time
from typing import Any

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SaplCorpusMixin:
    def fetch_all_normas(
        self,
        max_normas: int | None = None,
        tipo: str | None = None,
        ano: int | None = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Busca todas as normas com paginação automática e segue o link ``next`` do SAPL.

        Algumas implantações do SAPL devolvem uma página fixa mesmo quando ``offset``
        muda. Nesses casos a paginação por offset é interrompida de forma segura em vez
        de duplicar indefinidamente a primeira página. Para corpus científico use
        ``fetch_normas_for_corpus`` que particiona a busca por ano/tipo quando necessário.
        """
        logger.info(
            "Iniciando fetch paginado: max_normas=%s, tipo=%s, ano=%s, page_size=%s",
            max_normas,
            tipo,
            ano,
            page_size,
        )

        all_normas: list[dict[str, Any]] = []
        seen_ids: set[Any] = set()
        seen_urls: set[str] = set()
        offset = 0
        data = self.fetch_normas_page(limit=page_size, offset=offset, tipo=tipo, ano=ano)
        page_guard = 0
        max_pages = max(1, int(getattr(settings, "SAPL_FULL_SYNC_MAX_PAGES", 1000)))

        while data and page_guard < max_pages:
            page_guard += 1
            results = data.get("results") or []
            if not results:
                break

            new_count = 0
            for norma in results:
                sapl_id = norma.get("id")
                if sapl_id is None or sapl_id in seen_ids:
                    continue
                seen_ids.add(sapl_id)
                all_normas.append(norma)
                new_count += 1

            logger.info("Progresso: %s normas acumuladas", len(all_normas))
            if max_normas and len(all_normas) >= max_normas:
                return all_normas[:max_normas]

            next_url = data.get("next")
            if next_url:
                next_url = str(next_url)
                if next_url in seen_urls:
                    logger.warning("SAPL repetiu o mesmo link de paginação; encerrando.")
                    break
                seen_urls.add(next_url)
                data = self._make_request_url(next_url)
                time.sleep(0.2)
                continue

            # Fallback para APIs que omitem ``next`` mas respeitam offset.
            if new_count == 0:
                logger.warning(
                    "SAPL devolveu uma página repetida sem link next; "
                    "não avançando por offset para evitar loop."
                )
                break
            offset += len(results)
            expected = int(data.get("count") or 0)
            if expected and offset >= expected:
                break
            data = self.fetch_normas_page(limit=page_size, offset=offset, tipo=tipo, ano=ano)
            time.sleep(0.2)

        if page_guard >= max_pages:
            logger.warning("Limite de %s páginas SAPL atingido.", max_pages)
        return all_normas[:max_normas] if max_normas else all_normas

    def fetch_normas_for_corpus(
        self,
        target: int = 300,
        ano_inicio: int | None = None,
        ano_fim: int | None = None,
        tipos: list[str] | None = None,
        page_size: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Collect a bounded municipal corpus even when SAPL pagination is defective.

        Strategy:
        1. Follow real ``next`` links whenever SAPL supplies them.
        2. Probe each year independently to avoid a global "latest 10" ceiling.
        3. Discover type labels from the payload and re-query year/type partitions,
           which provides additional coverage on installations that cap each response.

        The result is deliberately bounded (default 300) and deduplicated by SAPL id.
        It is a corpus-selection tool, not a claim that the remote database was fully
        enumerated. Logging records when fewer than ``target`` unique norms were found.
        """
        if isinstance(target, bool) or target < 1:
            raise ValueError("target must be a positive integer")

        current_year = time.gmtime().tm_year
        start_year = ano_inicio or int(getattr(settings, "SAPL_CORPUS_START_YEAR", 2000))
        end_year = ano_fim or current_year
        if start_year > end_year:
            raise ValueError("ano_inicio must be <= ano_fim")

        discovered_types: set[str] = set(tipos or [])
        collected: dict[Any, dict[str, Any]] = {}
        years = range(end_year, start_year - 1, -1)
        delay = float(getattr(settings, "SAPL_CORPUS_REQUEST_DELAY_SECONDS", 0.2))

        def add_results(items: list[dict[str, Any]]) -> None:
            for item in items:
                sapl_id = item.get("id")
                if sapl_id is None:
                    continue
                collected.setdefault(sapl_id, item)
                raw_type = item.get("tipo")
                if isinstance(raw_type, dict):
                    label = str(raw_type.get("descricao") or raw_type.get("sigla") or "").strip()
                else:
                    label = str(raw_type or "").strip()
                if label:
                    discovered_types.add(label)

        for year in years:
            if len(collected) >= target:
                break
            try:
                page = self.fetch_normas_page(limit=page_size, offset=0, ano=year)
                add_results(page.get("results") or [])
                next_url = page.get("next")
                seen: set[str] = set()
                guard = 0
                max_pages = max(1, int(getattr(settings, "SAPL_FULL_SYNC_MAX_PAGES", 1000)))
                while next_url and len(collected) < target and guard < max_pages:
                    next_url = str(next_url)
                    if next_url in seen:
                        break
                    seen.add(next_url)
                    guard += 1
                    page = self._make_request_url(next_url)
                    add_results(page.get("results") or [])
                    next_url = page.get("next")
                    time.sleep(delay)
                time.sleep(delay)
            except Exception:
                logger.warning("Falha ao consultar SAPL no ano %s", year, exc_info=True)

        # Fallback for installations where year-only queries are capped at 10 rows.
        for tipo in sorted(discovered_types):
            for year in years:
                if len(collected) >= target:
                    break
                try:
                    page = self.fetch_normas_page(
                        limit=page_size,
                        offset=0,
                        tipo=tipo,
                        ano=year,
                    )
                    add_results(page.get("results") or [])
                    time.sleep(delay)
                except Exception:
                    logger.debug(
                        "Ignorando partição SAPL tipo=%s ano=%s", tipo, year, exc_info=True
                    )

        result = list(collected.values())[:target]
        if len(result) < target:
            logger.warning(
                "Corpus SAPL incompleto: %s/%s normas únicas coletadas no intervalo %s-%s.",
                len(result),
                target,
                start_year,
                end_year,
            )
        else:
            logger.info("Corpus SAPL alvo atingido: %s normas únicas.", len(result))
        return result
