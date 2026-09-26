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


class SaplNormasMixin:
    def fetch_normas_page(
        self,
        limit: int = 50,
        offset: int = 0,
        tipo: str | None = None,
        ano: int | None = None,
    ) -> dict[str, Any]:
        """Return the complete SAPL page payload, including ``count`` and ``next``."""
        params: dict[str, Any] = {"limit": limit, "offset": offset}
        if tipo:
            params["tipo"] = tipo
        if ano:
            params["ano"] = ano
        return self._make_request(self.NORMA_ENDPOINT, params)

    def fetch_normas(
        self, limit: int = 50, offset: int = 0, tipo: str | None = None, ano: int | None = None
    ) -> list[dict[str, Any]]:
        """
        Busca normas jurídicas na API SAPL.

        A API do SAPL retorna dados paginados no formato:
        {
            "count": <total>,
            "next": "<url_proxima_pagina>",
            "previous": "<url_pagina_anterior>",
            "results": [...]
        }

        Args:
            limit: Número máximo de normas a buscar
            offset: Offset para paginação
            tipo: Filtro por tipo de norma (ex: "Lei Ordinária")
            ano: Filtro por ano

        Returns:
            Lista de dicionários com metadados das normas

        Raises:
            requests.RequestException: Em caso de falha na API
        """
        logger.info(
            f"Iniciando fetch de normas: limit={limit}, offset={offset}, tipo={tipo}, ano={ano}"
        )

        try:
            start_time = time.time()
            data = self.fetch_normas_page(limit=limit, offset=offset, tipo=tipo, ano=ano)
            elapsed = time.time() - start_time

            results = data.get("results", [])
            total_count = data.get("count", 0)

            logger.info(
                f"Fetch concluído: {len(results)} normas recuperadas de {total_count} "
                f"totais em {elapsed:.2f}s"
            )

            return results

        except Exception as e:
            logger.error(f"Falha no fetch de normas: {str(e)}")
            raise

    def fetch_norma_by_id(self, norma_id: int) -> dict[str, Any]:
        """
        Busca uma norma específica por ID.

        Args:
            norma_id: ID da norma no SAPL

        Returns:
            Dicionário com metadados da norma

        Raises:
            requests.RequestException: Em caso de falha na API
        """
        logger.info(f"Buscando norma ID={norma_id}")

        endpoint = f"{self.NORMA_ENDPOINT}{norma_id}/"

        try:
            data = self._make_request(endpoint)
            logger.info(f"Norma ID={norma_id} recuperada com sucesso")
            return data

        except Exception as e:
            logger.error(f"Falha ao buscar norma ID={norma_id}: {str(e)}")
            raise

    def fetch_normas_by_year_range(
        self,
        ano_inicio: int,
        ano_fim: int,
        tipo: str | None = None,
        max_normas_por_ano: int | None = None,
    ) -> list[dict[str, Any]]:
        """
        Busca normas por intervalo de anos (workaround para limitação de paginação da API).

        Esta estratégia contorna a limitação da API SAPL que retorna sempre as mesmas
        10 normas independente do offset, iterando ano por ano.

        Args:
            ano_inicio: Ano inicial do intervalo (inclusive)
            ano_fim: Ano final do intervalo (inclusive)
            tipo: Filtro opcional por tipo de norma
            max_normas_por_ano: Limite máximo de normas por ano (None = todas)

        Returns:
            Lista completa de normas do intervalo
        """
        logger.info(
            f"Iniciando fetch por intervalo de anos: {ano_inicio}-{ano_fim}, "
            f"tipo={tipo}, max_por_ano={max_normas_por_ano}"
        )

        all_normas = []
        anos_para_processar = list(range(ano_inicio, ano_fim + 1))

        for ano in anos_para_processar:
            try:
                logger.info(f"Buscando normas do ano {ano}...")

                # Buscar todas as normas deste ano
                normas_do_ano = self.fetch_all_normas(
                    max_normas=max_normas_por_ano, tipo=tipo, ano=ano, page_size=50
                )

                # Remover duplicatas por sapl_id
                normas_unicas = {}
                for norma in normas_do_ano:
                    sapl_id = norma.get("id")
                    if sapl_id and sapl_id not in normas_unicas:
                        normas_unicas[sapl_id] = norma

                normas_do_ano_unicas = list(normas_unicas.values())
                all_normas.extend(normas_do_ano_unicas)

                logger.info(
                    f"Ano {ano}: {len(normas_do_ano_unicas)} normas únicas encontradas "
                    f"(total acumulado: {len(all_normas)})"
                )

                # Rate limiting entre anos
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Erro ao buscar normas do ano {ano}: {str(e)}")
                continue

        # Remover duplicatas finais (caso alguma norma apareça em múltiplos anos)
        normas_finais_unicas = {}
        for norma in all_normas:
            sapl_id = norma.get("id")
            if sapl_id and sapl_id not in normas_finais_unicas:
                normas_finais_unicas[sapl_id] = norma

        resultado_final = list(normas_finais_unicas.values())

        logger.info(
            f"Fetch por intervalo de anos concluído: {len(resultado_final)} normas únicas "
            f"de {ano_inicio} a {ano_fim}"
        )

        return resultado_final
