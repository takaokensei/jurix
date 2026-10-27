"""Read-only export of public sources for the 2026-10-18 AI adjudication."""

import hashlib
import json
import os
from pathlib import Path
from zipfile import ZipFile

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings_normative_container_qa")
import django

django.setup()

from django.db import connection, transaction  # noqa: E402

from src.apps.legislation.document_models import DocumentoNormativo  # noqa: E402
from src.apps.legislation.document_views import _document_path  # noqa: E402

assert os.environ.get("JURIX_QA_ONLY") == "1"

FILENAMES = [
    "LeiComplementar_20140829_141_.pdf",
    "LeiOrdinaria_20250110_7805_.pdf",
    "LeiOrdinaria_20250110_7806_.pdf",
    "LeiOrdinaria_20250110_7807_.pdf",
    "LeiOrdinaria_20250110_7808_.pdf",
    "LeiOrdinaria_20250110_7810_.pdf",
    "LeiOrdinaria_20250116_7811_.pdf",
]

output = Path("/tmp/jurix-ai-review-sources-20261018.zip")
with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
    documents = list(
        DocumentoNormativo.objects.filter(
            source_kind="archive",
            original_filename__in=FILENAMES,
        ).order_by("original_filename", "pk")
    )
    assert len({document.original_filename for document in documents}) == 7
    with ZipFile(output, "w") as bundle:
        for document in documents:
            extraction = document.extracoes.filter(status="complete").order_by("-pk").first()
            assert extraction is not None, document.original_filename
            pdf = _document_path(document).read_bytes()
            assert hashlib.sha256(pdf).hexdigest() == document.content_sha256
            key = document.original_filename.removesuffix(".pdf")
            bundle.writestr(key + ".pdf", pdf)
            bundle.writestr(key + ".txt", extraction.legal_text.encode("utf-8"))
            metadata = {
                "document_public_id": str(document.public_id),
                "document_key": document.document_key,
                "filename": document.original_filename,
                "sha256": document.content_sha256,
                "source_ref": document.source_ref,
                "official_url": document.official_url,
                "archive_sha256": document.archive_sha256,
                "entry_index": document.entry_index,
                "metadata": document.metadata_json,
                "text_sha256": extraction.legal_text_sha256,
                "extractor_version": extraction.extractor_version,
                "text_version": extraction.text_version,
                "extraction_sha256": extraction.extraction_sha256,
                "page_map": extraction.page_map_json,
                "page_count": extraction.page_count,
            }
            bundle.writestr(key + ".json", json.dumps(metadata, ensure_ascii=False))
print(json.dumps({"archive": str(output), "documents": len(documents)}))
