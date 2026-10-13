"""Inspect one official DOM PDF in memory and print only candidate metadata."""

from __future__ import annotations

import json

import pymupdf
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.dom_sync import DomNatalCandidateError, _require_dom_qa
from src.clients.dom_natal.client import DomNatalClient
from src.processing.gazette_act_candidates import find_gazette_act_candidates
from src.processing.gazette_segmentation import propose_gazette_boundaries


class Command(BaseCommand):
    help = "Read one explicitly selected DOM edition PDF in QA; do not persist it."

    def add_arguments(self, parser):
        parser.add_argument("--year", type=int, required=True)
        parser.add_argument("--month", type=int, required=True)
        parser.add_argument("--edition-number", type=int, required=True)
        parser.add_argument("--kind", choices=("regular", "special"), required=True)
        parser.add_argument("--max-pages", type=int, default=200)

    def handle(self, *args, **options):
        try:
            _require_dom_qa()
        except DomNatalCandidateError as exc:
            raise CommandError(str(exc)) from exc

        year = options["year"]
        month = options["month"]
        edition_number = options["edition_number"]
        max_pages = options["max_pages"]
        if not 2001 <= year <= 2100:
            raise CommandError("year deve estar entre 2001 e 2100")
        if not 1 <= month <= 12:
            raise CommandError("month deve estar entre 1 e 12")
        if not 1 <= edition_number <= 99_999_999:
            raise CommandError("edition-number deve estar entre 1 e 99.999.999")
        if not 1 <= max_pages <= 500:
            raise CommandError("max-pages deve estar entre 1 e 500")

        client = DomNatalClient()
        try:
            editions = client.list_editions(month=month, year=year)
            special = options["kind"] == "special"
            matches = [
                edition
                for edition in editions
                if edition.number == edition_number and edition.special is special
            ]
            if len(matches) != 1:
                raise CommandError(
                    "edição não encontrada de forma única no catálogo oficial consultado"
                )
            edition = matches[0]
            downloaded = client.download_edition(edition)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"consulta ao DOM falhou ({type(exc).__name__})") from exc
        finally:
            client.session.close()

        try:
            pdf = pymupdf.open(stream=downloaded.content, filetype="pdf")
            page_count = len(pdf)
            if page_count > 500:
                raise CommandError("PDF excede o limite de 500 páginas para inspeção")
            pages = [pdf.load_page(index).get_text() for index in range(page_count)]
            proposal = propose_gazette_boundaries(pages, max_pages=max_pages)
            act_spans = find_gazette_act_candidates(pages, max_pages=max_pages)
        except CommandError:
            raise
        except Exception as exc:
            raise CommandError(f"PDF não pôde ser analisado ({type(exc).__name__})") from exc

        classes = sorted({item.document_class for item in proposal.candidates})
        report = {
            "source": "dom_natal",
            "read_only": True,
            "persisted": False,
            "review_status": "pending",
            "edition": {
                "year": edition.year,
                "month": edition.publication_date.month,
                "number": edition.number,
                "publication_date": edition.publication_date.isoformat(),
                "kind": "special" if edition.special else "regular",
            },
            "pdf": {"bytes": downloaded.size_bytes, "sha256": downloaded.sha256},
            "segmentation": {
                "status": proposal.status,
                "page_count": proposal.page_count,
                "processed_page_count": proposal.processed_page_count,
                "candidate_count": len(proposal.candidates),
                "class_counts": {
                    name: sum(item.document_class == name for item in proposal.candidates)
                    for name in classes
                },
                "issues": list(proposal.issues),
                "candidates": [
                    {
                        "instrument_type": item.instrument_type,
                        "number": item.number,
                        "year": item.year,
                        "publication_date": item.publication_date,
                        "document_class": item.document_class,
                        "page": item.page_index + 1,
                        "heading_start_offset": item.heading_start_offset,
                        "heading_end_offset": item.heading_end_offset,
                        "review_status": item.review_status,
                    }
                    for item in proposal.candidates
                ],
            },
            "act_span_candidates": act_spans.as_dict(),
        }
        # Keep the machine-readable diagnostic valid in Windows consoles with
        # legacy code pages; JSON escapes preserve all Unicode metadata.
        self.stdout.write(json.dumps(report, ensure_ascii=True, sort_keys=True))
