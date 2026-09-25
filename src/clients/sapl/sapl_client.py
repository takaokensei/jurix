"""
SAPL API Client for Jurix project.

Cliente HTTP para consumir a API REST do SAPL (Sistema de Apoio ao Processo Legislativo)
da Câmara Municipal de Natal/RN.

API Base URL: https://sapl.natal.rn.leg.br/api/
Documentação: https://sapl.natal.rn.leg.br/api/docs/
"""

import logging
import os
import time
from typing import Any

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from requests.packages.urllib3.util.retry import Retry

logger = logging.getLogger(__name__)


class SaplAPIClient:
    """
    Cliente para consumo da API REST do SAPL.

    Features:
    - Retry automático com backoff exponencial
    - Rotação de User-Agents
    - Logging estruturado
    - Tratamento robusto de erros
    - Configurabilidade de Base URL via env/settings
    """

    DEFAULT_BASE_URL = getattr(
        settings,
        'SAPL_BASE_URL',
        os.getenv('SAPL_BASE_URL', "https://sapl.natal.rn.leg.br/api")
    )
    BASE_URL = DEFAULT_BASE_URL
    NORMA_ENDPOINT = "/norma/normajuridica/"

    USER_AGENTS = [
        'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36',
        'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36',
    ]

    def __init__(
        self,
        base_url: str | None = None,
        timeout: int = 30,
        max_retries: int = 3
    ):
        """
        Inicializa o cliente SAPL.

        Args:
            base_url: URL base da API SAPL (defaults to settings.SAPL_BASE_URL)
            timeout: Timeout em segundos para requisições HTTP
            max_retries: Número máximo de tentativas em caso de falha
        """
        resolved_url = base_url or getattr(settings, 'SAPL_BASE_URL', self.BASE_URL)
        self.base_url = str(resolved_url).rstrip('/')
        self.timeout = timeout
        self.session = self._create_session(max_retries)
        self._request_count = 0

        logger.info(
            f"SaplAPIClient inicializado: base_url={self.base_url}, "
            f"timeout={timeout}s, max_retries={max_retries}"
        )

    def _create_session(self, max_retries: int) -> requests.Session:
        """
        Cria uma sessão HTTP com retry automático.

        Args:
            max_retries: Número máximo de tentativas

        Returns:
            Sessão requests configurada
        """
        session = requests.Session()

        retry_strategy = Retry(
            total=max_retries,
            backoff_factor=1,  # 1s, 2s, 4s, 8s...
            status_forcelist=[429, 500, 502, 503, 504],
            allowed_methods=["GET", "POST"]
        )

        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        return session

    def _get_headers(self) -> dict[str, str]:
        """
        Gera headers HTTP com rotação de User-Agent.

        Returns:
            Dicionário de headers
        """
        user_agent = self.USER_AGENTS[self._request_count % len(self.USER_AGENTS)]
        self._request_count += 1

        return {
            'User-Agent': user_agent,
            'Accept': 'application/json',
            'Accept-Language': 'pt-BR,pt;q=0.9',
        }

    def get_public_norma_url(self, sapl_id: int | str) -> str:
        """Return the current public SAPL URL, never the API route."""
        base = self.base_url.rstrip('/')
        if base.endswith('/api'):
            base = base[:-4]
        return f"{base}/norma/{int(sapl_id)}/"

    def _make_request(
        self,
        endpoint: str,
        params: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """
        Executa uma requisição GET na API SAPL.

        Args:
            endpoint: Endpoint relativo (ex: '/norma/normajuridica/')
            params: Query parameters opcionais

        Returns:
            Resposta JSON deserializada

        Raises:
            requests.RequestException: Em caso de falha na requisição
        """
        url = f"{self.base_url}{endpoint}"
        headers = self._get_headers()

        logger.debug(f"Requisitando: {url} com params={params}")

        try:
            response = self.session.get(
                url,
                headers=headers,
                params=params,
                timeout=self.timeout
            )
            response.raise_for_status()

            data = response.json()
            logger.info(f"Requisição bem-sucedida: {url} - Status {response.status_code}")

            return data

        except requests.exceptions.Timeout:
            logger.error(f"Timeout ao acessar {url}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"Erro HTTP {e.response.status_code}: {url}")
            raise
        except requests.exceptions.RequestException as e:
            logger.error(f"Erro de requisição: {url} - {str(e)}")
            raise
        except ValueError as e:
            logger.error(f"Erro ao parsear JSON: {url} - {str(e)}")
            raise

    def fetch_normas(
        self,
        limit: int = 50,
        offset: int = 0,
        tipo: str | None = None,
        ano: int | None = None
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
            f"Iniciando fetch de normas: limit={limit}, offset={offset}, "
            f"tipo={tipo}, ano={ano}"
        )

        params = {
            'limit': limit,
            'offset': offset,
        }

        if tipo:
            params['tipo'] = tipo
        if ano:
            params['ano'] = ano

        try:
            start_time = time.time()
            data = self._make_request(self.NORMA_ENDPOINT, params)
            elapsed = time.time() - start_time

            results = data.get('results', [])
            total_count = data.get('count', 0)

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
        max_normas_por_ano: int | None = None
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
                    max_normas=max_normas_por_ano,
                    tipo=tipo,
                    ano=ano,
                    page_size=50
                )

                # Remover duplicatas por sapl_id
                normas_unicas = {}
                for norma in normas_do_ano:
                    sapl_id = norma.get('id')
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
            sapl_id = norma.get('id')
            if sapl_id and sapl_id not in normas_finais_unicas:
                normas_finais_unicas[sapl_id] = norma

        resultado_final = list(normas_finais_unicas.values())

        logger.info(
            f"Fetch por intervalo de anos concluído: {len(resultado_final)} normas únicas "
            f"de {ano_inicio} a {ano_fim}"
        )

        return resultado_final

    def fetch_all_normas(
        self,
        max_normas: int | None = None,
        tipo: str | None = None,
        ano: int | None = None,
        page_size: int = 50
    ) -> list[dict[str, Any]]:
        """
        Busca todas as normas com paginação automática.

        NOTA: Devido à limitação da API SAPL (retorna sempre as mesmas 10 normas),
        recomenda-se usar fetch_normas_by_year_range para busca histórica completa.

        Args:
            max_normas: Número máximo de normas (None = todas)
            tipo: Filtro por tipo
            ano: Filtro por ano
            page_size: Tamanho de cada página

        Returns:
            Lista completa de normas
        """
        logger.info(
            f"Iniciando fetch paginado: max_normas={max_normas}, "
            f"tipo={tipo}, ano={ano}, page_size={page_size}"
        )

        all_normas = []
        offset = 0
        seen_ids = set()  # Para detectar duplicatas

        while True:
            try:
                normas = self.fetch_normas(
                    limit=page_size,
                    offset=offset,
                    tipo=tipo,
                    ano=ano
                )

                if not normas:
                    logger.info("Nenhuma norma adicional encontrada. Fetch completo.")
                    break

                # Filtrar duplicatas
                novas_normas = []
                for norma in normas:
                    sapl_id = norma.get('id')
                    if sapl_id and sapl_id not in seen_ids:
                        seen_ids.add(sapl_id)
                        novas_normas.append(norma)

                if not novas_normas:
                    logger.info("Apenas normas duplicadas encontradas. Encerrando paginação.")
                    break

                all_normas.extend(novas_normas)
                logger.info(f"Progresso: {len(all_normas)} normas acumuladas")

                if max_normas and len(all_normas) >= max_normas:
                    all_normas = all_normas[:max_normas]
                    logger.info(f"Limite de {max_normas} normas atingido")
                    break

                offset += page_size

                # Rate limiting (boa prática)
                time.sleep(0.5)

            except Exception as e:
                logger.error(f"Erro durante fetch paginado no offset {offset}: {str(e)}")
                break

        logger.info(f"Fetch paginado concluído: {len(all_normas)} normas totais")
        return all_normas

    def download_pdf(self, pdf_url: str, output_path: str) -> bool:
        """
        Baixa um arquivo PDF da URL fornecida.

        Args:
            pdf_url: URL do PDF
            output_path: Caminho local para salvar

        Returns:
            True se bem-sucedido, False caso contrário
        """
        logger.info(f"Baixando PDF: {pdf_url} -> {output_path}")

        max_bytes = int(getattr(settings, 'SAPL_DOWNLOAD_MAX_BYTES', 80 * 1024 * 1024))
        timeout = int(getattr(settings, 'SAPL_DOWNLOAD_TIMEOUT_SECONDS', self.timeout))
        target = os.path.abspath(output_path)
        os.makedirs(os.path.dirname(target), exist_ok=True)
        temporary = target + '.part'
        try:
            headers = self._get_headers()
            response = self.session.get(
                pdf_url,
                headers=headers,
                timeout=timeout,
                stream=True
            )
            response.raise_for_status()
            content_length = response.headers.get('Content-Length')
            if content_length and int(content_length) > max_bytes:
                logger.warning("PDF exceeds configured download limit: %s bytes", content_length)
                return False

            total = 0
            with open(temporary, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if not chunk:
                        continue
                    total += len(chunk)
                    if total > max_bytes:
                        logger.warning("PDF exceeded configured download limit while streaming")
                        return False
                    f.write(chunk)

            os.replace(temporary, target)

            logger.info(f"PDF baixado com sucesso: {output_path}")
            return True

        except Exception as e:
            logger.error(f"Falha ao baixar PDF {pdf_url}: {str(e)}")
            return False
        finally:
            try:
                if os.path.exists(temporary):
                    os.remove(temporary)
            except OSError:
                logger.debug("Could not remove partial SAPL PDF", exc_info=True)

    def close(self):
        """Fecha a sessão HTTP."""
        self.session.close()
        logger.info("Sessão HTTP fechada")

