"""Bounded, exact lookup helpers for SAPL legislative matters.

Matter records (projects, amendments and vetoes) are not normative texts. Keep
their workflow metadata separate from normative validity and from the SAPL
``normajuridica`` endpoints.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Any
from urllib.parse import urlparse


class SaplMateriasMixin:
    MATERIA_ENDPOINT = "/materia/materialegislativa/"
    MATERIA_TYPE_ENDPOINT = "/materia/tipomaterialegislativa/"
    MATERIA_MAX_PAGES = 5

    @staticmethod
    def _normalize_matter_type_label(value: object) -> str:
        folded = unicodedata.normalize("NFKD", str(value or "").casefold())
        unaccented = "".join(char for char in folded if not unicodedata.combining(char))
        return re.sub(r"[^a-z0-9]+", " ", unaccented).strip()

    @staticmethod
    def _validate_reference_part(value: object, label: str) -> int:
        if isinstance(value, bool):
            raise ValueError(f"{label} inválido")
        try:
            normalized = int(value)
        except (TypeError, ValueError) as exc:
            raise ValueError(f"{label} inválido") from exc
        if normalized <= 0:
            raise ValueError(f"{label} deve ser positivo")
        return normalized

    def _fetch_all_matter_pages(
        self,
        endpoint: str,
        *,
        params: dict[str, Any],
        max_pages: int | None = None,
    ) -> list[dict[str, Any]]:
        page_limit = max_pages or self.MATERIA_MAX_PAGES
        if isinstance(page_limit, bool) or not 1 <= int(page_limit) <= self.MATERIA_MAX_PAGES:
            raise ValueError("Limite de páginas SAPL inválido")

        payload = self._make_request(endpoint, params=params)
        seen_urls: set[str] = set()
        results: list[dict[str, Any]] = []
        expected_count: int | None = None

        for page_index in range(int(page_limit)):
            page_results = payload.get("results")
            if not isinstance(page_results, list):
                raise ValueError("Resposta SAPL de matérias sem lista de resultados")
            results.extend(item for item in page_results if isinstance(item, dict))

            pagination = payload.get("_jurix_pagination")
            page_count = payload.get("count")
            if isinstance(page_count, int) and not isinstance(page_count, bool):
                if expected_count is not None and expected_count != page_count:
                    raise ValueError("Contagem SAPL mudou durante a paginação")
                expected_count = page_count
            elif isinstance(pagination, dict):
                page_count = pagination.get("total_entries")
                if isinstance(page_count, int) and not isinstance(page_count, bool):
                    expected_count = page_count

            next_url = payload.get("next")
            if not next_url:
                if expected_count is not None and len(results) != expected_count:
                    raise ValueError("Paginação SAPL terminou antes da contagem declarada")
                return results

            safe_url = self.validate_pagination_url(str(next_url))
            if safe_url in seen_urls:
                raise ValueError("SAPL repetiu URL de paginação de matérias")
            seen_urls.add(safe_url)
            if page_index + 1 >= int(page_limit):
                raise ValueError("Busca de matérias SAPL excedeu o limite de páginas")
            payload = self._make_request_url(safe_url)

        raise ValueError("Paginação SAPL de matérias incompleta")

    def fetch_materias_by_reference(
        self,
        tipo: str,
        numero: int | str,
        ano: int | str,
    ) -> list[dict[str, Any]]:
        """Find exact matter records by the installation's own type catalogue.

        Numeric SAPL type IDs are local to an installation. Resolve the exact
        textual label first; never assume a hard-coded ID means the same thing
        across SAPL instances. Empty ``resultado``/publication fields remain
        empty in the returned source payload and are not interpreted as a
        legislative outcome.
        """
        rows = self.fetch_materias_by_references(
            [{"tipo": tipo, "numero": numero, "ano": ano}]
        )
        key = (
            self._normalize_matter_type_label(tipo),
            self._validate_reference_part(numero, "Número"),
            self._validate_reference_part(ano, "Ano"),
        )
        return rows.get(key, [])

    def fetch_materias_by_references(
        self, references: list[dict[str, Any]]
    ) -> dict[tuple[str, int, int], list[dict[str, Any]]]:
        """Resolve a bounded set of exact references with one type-catalog request."""
        if len(references) > 3:
            raise ValueError("A busca SAPL aceita no máximo três referências por chamada")
        normalized_references: list[tuple[tuple[str, int, int], int | None]] = []
        seen_references = set()
        for reference in references:
            requested_type = self._normalize_matter_type_label(reference.get("tipo"))
            if not requested_type:
                raise ValueError("Tipo de matéria é obrigatório")
            number = self._validate_reference_part(reference.get("numero"), "Número")
            year = self._validate_reference_part(reference.get("ano"), "Ano")
            key = (requested_type, number, year)
            if key not in seen_references:
                seen_references.add(key)
                normalized_references.append((key, None))
        if not normalized_references:
            return {}
        type_rows = self._fetch_all_matter_pages(
            self.MATERIA_TYPE_ENDPOINT,
            params={"limit": 100},
        )
        requested_types = {key[0] for key, _type_id in normalized_references}
        matching_type_ids: dict[str, set[int]] = {label: set() for label in requested_types}
        for row in type_rows:
            label = self._normalize_matter_type_label(
                row.get("descricao") or row.get("__str__") or row.get("sigla")
            )
            if label in matching_type_ids:
                matching_type_ids[label].add(
                    self._validate_reference_part(row.get("id"), "ID do tipo SAPL")
                )

        found: dict[tuple[str, int, int], list[dict[str, Any]]] = {}
        for key, _unused in normalized_references:
            requested_type, requested_number, requested_year = key
            type_ids = matching_type_ids[requested_type]
            found[key] = []
            if len(type_ids) != 1:
                continue
            type_id = next(iter(type_ids))
            matter_rows = self._fetch_all_matter_pages(
                self.MATERIA_ENDPOINT,
                params={
                    "limit": 100,
                    "tipo": type_id,
                    "numero": requested_number,
                    "ano": requested_year,
                },
            )
            for row in matter_rows:
                try:
                    row_type = int(row.get("tipo"))
                    row_number = int(row.get("numero"))
                    row_year = int(row.get("ano"))
                    row_id = self._validate_reference_part(row.get("id"), "ID da matéria")
                except (TypeError, ValueError):
                    continue
                if (row_type, row_number, row_year) != (type_id, requested_number, requested_year):
                    continue
                found[key].append({**row, "_jurix_materia_id": row_id})
        return found

    def search_public_materias_by_ementa(self, expression: str) -> list[dict[str, Any]]:
        """Use SAPL's public, bounded matter-search export for exact ementa terms."""
        query = " ".join(str(expression or "").split())
        if not 8 <= len(query) <= 180:
            raise ValueError("Expressão de ementa SAPL fora do limite")
        parsed = urlparse(self.base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Origem SAPL configurada inválida")
        base_path = parsed.path.rstrip("/")
        if base_path.lower().endswith("/api"):
            base_path = base_path[:-4]
        base_url = parsed._replace(path=base_path, params="", query="", fragment="").geturl().rstrip("/")
        url = f"{base_url}/materia/pesquisar-materia"
        response = self.session.get(
            url,
            params={"format": "json", "ementa": query},
            headers=self._get_headers(),
            timeout=self.timeout,
            allow_redirects=False,
        )
        response.raise_for_status()
        payload = response.json()
        rows = payload.get("results") if isinstance(payload, dict) else None
        if not isinstance(rows, list) or len(rows) > 25:
            raise ValueError("Resultado da pesquisa pública SAPL inválido ou amplo demais")
        return [row for row in rows if isinstance(row, dict)]

    def fetch_materia_by_id(self, materia_id: int | str) -> dict[str, Any]:
        """Fetch one SAPL matter by a validated ID returned by its public search."""
        normalized_id = self._validate_reference_part(materia_id, "ID da matéria")
        payload = self._make_request(f"{self.MATERIA_ENDPOINT}{normalized_id}/")
        if not isinstance(payload, dict) or str(payload.get("id") or "") != str(normalized_id):
            raise ValueError("Resposta SAPL não corresponde à matéria solicitada")
        return payload

    def get_public_materia_url(self, materia_id: int | str) -> str:
        """Build the public SAPL page URL from a validated local matter ID."""
        normalized_id = self._validate_reference_part(materia_id, "ID da matéria")
        parsed = urlparse(self.base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("Origem SAPL configurada inválida")
        base = self.base_url.rstrip("/")
        if base.lower().endswith("/api"):
            base = base[:-4]
        return f"{base}/materia/{normalized_id}"
