"""Mechanically split the legacy ingestion task module into domain modules.

This script is intentionally deterministic: it extracts top-level AST nodes from
`tasks_legacy.py`, preserving task decorators and function bodies verbatim, then
writes explicit domain modules. It is used once during the audit refactor and is
safe to rerun until the legacy module disappears.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src/apps/ingestion"
LEGACY = PKG / "tasks_legacy.py"

GROUPS = {
    "task_support.py": [
        "_normalize_norma_tipo",
        "_configure_tesseract",
        "_invalidate_rag_cache",
        "_mark_norma_failed",
        "_resolve_norma_reference",
    ],
    "core_tasks.py": [
        "cleanup_chat_attachments",
        "ingest_normas_task",
        "_process_norma_data",
        "bulk_ingest_normas_task",
        "ingest_sapl_corpus_task",
    ],
    "download_tasks.py": [
        "download_pdf_task",
        "_sapl_payload_hash",
        "incremental_sync_sapl_task",
        "full_sync_sapl_task",
    ],
    "ocr_tasks.py": ["ocr_pdf_task"],
    "segmentation_tasks.py": ["segment_text_task"],
    "ner_tasks.py": ["extract_entities_task", "generate_embedding_task"],
    "consolidation_tasks.py": ["consolidate_norma_task"],
}

COMMON_IMPORTS = '''from __future__ import annotations

import hashlib
import io
import json
import logging
import os
import time
from pathlib import Path
from typing import Any

import fitz
import pytesseract
from celery import shared_task
from django.conf import settings
from django.db import connection, transaction
from django.utils import timezone
from django.utils.dateparse import parse_date
from PIL import Image

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.clients.sapl.sapl_client import SaplAPIClient
from src.llm_engine.ollama_service import OllamaService
from src.processing.cache_service import get_cache_service
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.legal_parser import LegalTextParser
from src.processing.ner_extractor import LegalNERExtractor

logger = logging.getLogger(__name__)
'''


def extract_nodes(source: str) -> dict[str, str]:
    tree = ast.parse(source)
    lines = source.splitlines()
    nodes: dict[str, str] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            start = node.decorator_list[0].lineno if node.decorator_list else node.lineno
            end = node.end_lineno or node.lineno
            nodes[node.name] = "\n".join(lines[start - 1 : end])
    return nodes


def write_module(filename: str, names: list[str], nodes: dict[str, str]) -> None:
    imports = COMMON_IMPORTS
    extra = {
        "core_tasks.py": "from .download_tasks import download_pdf_task\n",
        "ner_tasks.py": "from .task_support import _invalidate_rag_cache, _mark_norma_failed, _resolve_norma_reference\n",
        "ocr_tasks.py": "from .task_support import _configure_tesseract, _mark_norma_failed\n",
        "segmentation_tasks.py": "from .task_support import _invalidate_rag_cache, _mark_norma_failed\n",
        "consolidation_tasks.py": "from .task_support import _invalidate_rag_cache, _mark_norma_failed\n",
        "download_tasks.py": "from .task_support import _mark_norma_failed\n",
    }.get(filename, "")
    if filename == "task_support.py":
        imports = imports.replace("from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma", "from src.apps.legislation.models import Norma")
    else:
        extra += "\nfrom .task_support import _invalidate_rag_cache\n" if filename in {"core_tasks.py", "download_tasks.py"} else ""
    body = "\n\n".join(nodes[name] for name in names)
    path = PKG / filename
    path.write_text(imports + "\n" + extra + "\n" + body + "\n", encoding="utf-8")


def main() -> None:
    if not LEGACY.exists():
        return
    nodes = extract_nodes(LEGACY.read_text(encoding="utf-8"))
    missing = sorted({name for names in GROUPS.values() for name in names} - nodes.keys())
    if missing:
        raise SystemExit(f"missing legacy functions: {missing}")
    for filename, names in GROUPS.items():
        write_module(filename, names, nodes)

    (PKG / "tasks.py").write_text(
        '''"""Stable public ingestion task API; implementations live by domain."""\n
from .consolidation_tasks import consolidate_norma_task
from .core_tasks import (\n    bulk_ingest_normas_task,\n    cleanup_chat_attachments,\n    ingest_normas_bulk_task,\n    ingest_normas_task,\n    ingest_sapl_corpus_task,\n)\nfrom .download_tasks import download_pdf_task, full_sync_sapl_task, incremental_sync_sapl_task\nfrom .ner_tasks import extract_entities_task, generate_embedding_task\nfrom .ocr_tasks import ocr_pdf_task\nfrom .segmentation_tasks import segment_text_task\n\n__all__ = [\n    "bulk_ingest_normas_task", "cleanup_chat_attachments", "consolidate_norma_task",\n    "download_pdf_task", "extract_entities_task", "full_sync_sapl_task",\n    "generate_embedding_task", "incremental_sync_sapl_task", "ingest_normas_bulk_task",\n    "ingest_normas_task", "ingest_sapl_corpus_task", "ocr_pdf_task", "segment_text_task",\n]\n''',
        encoding="utf-8",
    )
    LEGACY.unlink()


if __name__ == "__main__":
    main()
