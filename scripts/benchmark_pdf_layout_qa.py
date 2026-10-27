#!/usr/bin/env python3
"""Compare stored table candidates with independent PDF text/HTML renderers (QA, read-only)."""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import os
import re
import subprocess
import sys
from html.parser import HTMLParser
from pathlib import Path
from uuid import UUID

ALLOWED_SETTINGS = {
    "config.settings_normative_qa",
    "config.settings_normative_container_qa",
}


def _require_qa() -> None:
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") not in ALLOWED_SETTINGS
    ):
        raise RuntimeError("Este benchmark exige um perfil QA normativo isolado.")


def _normalized(value: object) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().casefold()


class _HtmlText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.table_count = 0
        self.row_count = 0
        self.cell_count = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table":
            self.table_count += 1
        elif tag == "tr":
            self.row_count += 1
        elif tag in {"td", "th"}:
            self.cell_count += 1

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _run_renderer(command: list[str], timeout: int) -> str:
    result = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Renderer {Path(command[0]).name} falhou com código {result.returncode}.")
    return result.stdout


def _table_summary(table: object, baseline_texts: dict[str, str]) -> dict[str, object] | None:
    if not isinstance(table, dict) or not isinstance(table.get("rows"), list):
        return None
    rows = table["rows"]
    normalized_rows = [
        [str(cell or "").strip() for cell in row] if isinstance(row, list) else []
        for row in rows
    ]
    column_count = max((len(row) for row in normalized_rows), default=0)
    cells = [cell for row in normalized_rows for cell in row if _normalized(cell)]
    relevant_cells = [cell for cell in cells if len(_normalized(cell)) >= 2]
    markdown_rows = [
        "| " + " | ".join(cell.replace("|", "\\|").replace("\n", "<br>") for cell in row)
        + " |"
        for row in normalized_rows
    ]
    if markdown_rows:
        markdown_rows.insert(1, "| " + " | ".join("---" for _ in range(column_count)) + " |")
    def render_cells(row: list[str], tag: str) -> str:
        return "<tr>" + "".join(
            f"<{tag}>{html.escape(cell).replace(chr(10), '<br>')}</{tag}>" for cell in row
        ) + "</tr>"

    html_table = "<table>"
    if normalized_rows:
        html_table += "<thead>" + render_cells(normalized_rows[0], "th") + "</thead>"
    if len(normalized_rows) > 1:
        html_table += "<tbody>" + "".join(
            render_cells(row, "td") for row in normalized_rows[1:]
        ) + "</tbody>"
    html_table += "</table>"
    parsed_candidate = _HtmlText()
    parsed_candidate.feed(html_table)
    matching_counts = {
        name: sum(_normalized(cell) in baseline_texts[name] for cell in relevant_cells)
        for name in baseline_texts
    }
    return {
        "page": table.get("page"),
        "detector": table.get("detector"),
        "status": table.get("status"),
        "rows": len(normalized_rows),
        "columns_max": column_count,
        "nonempty_cells": len(cells),
        "multiline_cells": sum("\n" in cell for cell in cells),
        "candidate_cells_matching": matching_counts,
        "candidate_cells_missing": {
            name: len(relevant_cells) - matching_counts[name] for name in baseline_texts
        },
        "serialized_markdown_rows": len(markdown_rows),
        "serialized_html_tables": parsed_candidate.table_count,
        "serialized_html_rows": parsed_candidate.row_count,
        "serialized_html_cells": parsed_candidate.cell_count,
    }


def run(document_public_id: str, timeout: int = 60) -> dict[str, object]:
    _require_qa()
    project_root = Path(__file__).resolve().parents[1]
    for import_root in (project_root / "src", project_root):
        if str(import_root) not in sys.path:
            sys.path.insert(0, str(import_root))

    import django

    django.setup()

    from django.conf import settings

    from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento

    database = settings.DATABASES["default"]
    if database.get("NAME") != "jurix_audit":
        raise RuntimeError("Benchmark recusado: banco não é o QA normativo dedicado.")
    if os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings_normative_container_qa":
        safe_profile = database.get("HOST") == "db" and str(database.get("PORT")) == "5432"
        safe_root = Path(settings.QA_ROOT).resolve() == Path("/app/data/normative-qa")
    else:
        temporary_root = Path(os.environ.get("TEMP") or os.environ.get("TMP") or "").resolve()
        configured_root = Path(settings.QA_ROOT).resolve()
        safe_profile = database.get("HOST") in {"127.0.0.1", "localhost"} and str(
            database.get("PORT")
        ) == "55432"
        safe_root = (
            temporary_root.is_dir()
            and configured_root != temporary_root
            and configured_root.is_relative_to(temporary_root)
        )
    if not safe_profile or not safe_root:
        raise RuntimeError("Benchmark recusado: banco/armazenamento não pertencem ao QA isolado.")

    public_id = UUID(document_public_id)
    document = DocumentoNormativo.objects.get(public_id=public_id)
    if (
        document.source_kind != DocumentoNormativo.SourceKind.ARCHIVE
        or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
        or document.accepted_extraction_id is not None
        or document.norma_id is not None
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise RuntimeError("O benchmark aceita somente PDF candidato isolado e sem vínculo/aceite.")

    extraction = (
        ExtracaoDocumento.objects.filter(
            documento=document,
            quality_json__pipeline_candidate_only=True,
        )
        .order_by("-created_at", "-pk")
        .first()
    )
    if extraction is None:
        raise RuntimeError("Amostra sem extração QA candidata; nenhuma escrita foi feita.")

    qa_root = Path(settings.QA_ROOT).resolve()
    archive_root = (qa_root / "normative-archive").resolve()
    pdf_path = (archive_root / document.storage_key).resolve()
    if not pdf_path.is_relative_to(archive_root) or not pdf_path.is_file():
        raise RuntimeError("PDF QA ausente ou fora da raiz isolada.")
    with pdf_path.open("rb") as pdf_stream:
        digest = hashlib.file_digest(pdf_stream, "sha256").hexdigest()
    if digest != document.content_sha256:
        raise RuntimeError("Hash do PDF difere do registro QA.")

    poppler_text = _run_renderer(["pdftotext", "-layout", str(pdf_path), "-"], timeout)
    poppler_html = _run_renderer(
        ["pdftohtml", "-stdout", "-s", "-i", "-q", str(pdf_path)], timeout
    )
    html_parser = _HtmlText()
    html_parser.feed(poppler_html)
    candidate_texts = {
        "stored_extraction": _normalized(extraction.legal_text),
        "poppler_layout_text": _normalized(poppler_text),
        "poppler_html_text": _normalized(" ".join(html_parser.parts)),
    }
    layout = (extraction.metadata_candidates_json or {}).get("layout_tables") or {}
    candidates = layout.get("candidates") if isinstance(layout.get("candidates"), list) else []
    summaries = [
        summary
        for table in candidates
        if (summary := _table_summary(table, candidate_texts)) is not None
    ]
    return {
        "mode": "read_only_isolated_qa",
        "source": {
            "document_public_id": str(document.public_id),
            "filename": document.original_filename,
            "sha256_verified": True,
            "review_status": document.review_status,
            "accepted_extraction": False,
            "norma_linked": False,
        },
        "current_extraction": {
            "extraction_id": extraction.pk,
            "status": extraction.status,
            "page_count": extraction.page_count,
            "legal_text_chars": len(extraction.legal_text),
            "raw_text_chars": len(extraction.raw_text),
            "layout_table_detection_status": layout.get("status"),
            "layout_table_candidate_count": layout.get("candidate_count", len(summaries)),
            "tables": summaries,
        },
        "poppler": {
            "pdftotext_layout_chars": len(poppler_text),
            "pdftohtml_chars": len(poppler_html),
            "pdftohtml_semantic_table_count": html_parser.table_count,
            "pdftohtml_rows": html_parser.row_count,
            "pdftohtml_cells": html_parser.cell_count,
        },
        "limitations": [
            "A comparação mede preservação textual/estrutural em uma amostra; não valida juridicamente o PDF.",
            "A tabela Markdown/HTML serializada deriva dos candidatos PyMuPDF existentes, não de uma decisão de consolidação.",
            "pdftohtml não é considerado conversor semântico de tabelas apenas por gerar HTML.",
            "Nenhuma extração é criada, aceita, vinculada ou promovida.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--document-public-id", required=True)
    parser.add_argument("--timeout", type=int, default=60)
    options = parser.parse_args()
    if not 1 <= options.timeout <= 180:
        parser.error("--timeout precisa ficar entre 1 e 180 segundos")
    print(json.dumps(run(options.document_public_id, options.timeout), ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
