"""Dry-run or materialize unreviewed relation candidates for the public PGM law chain in QA."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.document_relation_candidates import (
    extract_document_relation_candidates,
    persist_document_relation_candidates,
)
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento

ALLOWED_EXTRACTIONS = {
    7114: ("lei_complementar", "217", "2022"),
    7115: ("lei_complementar", "217", "2022"),
    7141: ("lei_complementar", "258", "2024"),
    7135: ("lei_complementar", "261", "2025"),
    7144: ("lei_complementar", "198", "2021"),
    7149: ("lei_complementar", "271", "2025"),
    7150: ("lei_complementar", "271", "2025"),
    7151: ("lei_complementar", "271", "2025"),
}


class Command(BaseCommand):
    help = "Gera candidatos imutáveis para atos promulgados allowlisted no QA isolado."

    def add_arguments(self, parser):
        parser.add_argument("--extraction-id", type=int, action="append", required=True)
        parser.add_argument(
            "--source-article",
            help="Limita o cálculo à relação citada em um artigo-fonte específico.",
        )
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Persiste somente candidatos não revisados; sem esta flag, apenas calcula.",
        )

    def handle(self, *args, **options):
        database = settings.DATABASES.get("default", {})
        profile = os.environ.get("DJANGO_SETTINGS_MODULE")
        host_qa = (
            profile == "config.settings_normative_qa"
            and database.get("NAME") == "jurix_audit"
            and database.get("HOST") == "127.0.0.1"
            and str(database.get("PORT")) == "55432"
        )
        container_qa = (
            profile == "config.settings_normative_container_qa"
            and database.get("NAME") == "jurix_audit"
            and database.get("HOST") == "db"
        )
        if os.environ.get("JURIX_QA_ONLY") != "1" or not (host_qa or container_qa):
            raise CommandError("Este comando exige exclusivamente o PostgreSQL QA isolado.")
        extraction_ids = list(dict.fromkeys(options["extraction_id"]))
        if not extraction_ids or len(extraction_ids) > 5:
            raise CommandError("Informe até cinco extrações da cadeia promulgada QA permitida.")
        if any(value not in ALLOWED_EXTRACTIONS for value in extraction_ids):
            raise CommandError("Extração fora da allowlist de atos promulgados PGM.")
        source_article = options.get("source_article")
        if source_article is not None and (
            extraction_ids not in ([7135], [7114], [7115], [7141], [7149], [7151])
            or (extraction_ids == [7135] and source_article != "118")
            or (extraction_ids in ([7114], [7115]) and source_article != "1")
            or (extraction_ids == [7141] and source_article != "261")
            or (extraction_ids in ([7149], [7151]) and source_article not in {"1", "2", "3", "5"})
        ):
            raise CommandError(
                "O recorte está restrito aos dispositivos promulgados allowlisted da cadeia PGM QA."
            )

        results = []
        for extraction_id in extraction_ids:
            try:
                extraction = ExtracaoDocumento.objects.select_related("documento").get(
                    pk=extraction_id
                )
            except ExtracaoDocumento.DoesNotExist as exc:
                raise CommandError(f"Extração QA {extraction_id} não encontrada.") from exc
            expected_type, expected_number, expected_year = ALLOWED_EXTRACTIONS[extraction_id]
            document = extraction.documento
            identity = (document.metadata_json or {}).get("identity_candidate") or {}
            if (
                document.source_kind not in {
                    DocumentoNormativo.SourceKind.ARCHIVE,
                    DocumentoNormativo.SourceKind.SAPL,
                }
                or document.review_status != DocumentoNormativo.ReviewStatus.PENDING
                or document.accepted_extraction_id is not None
                or document.role != DocumentoNormativo.Role.UNDETERMINED
                or identity.get("type") != expected_type
                or str(identity.get("number")) != expected_number
                or str(identity.get("year")) != expected_year
                or extraction.status != ExtracaoDocumento.Status.COMPLETE
            ):
                raise CommandError(
                    f"Extração {extraction_id} não corresponde ao PDF promulgado pendente esperado."
                )

            if options["apply"]:
                result = persist_document_relation_candidates(
                    extraction, source_article=source_article
                )
            else:
                candidates = extract_document_relation_candidates(
                    extraction, source_article=source_article
                )
                result = {
                    "extraction_id": extraction_id,
                    "found": len(candidates),
                    "would_create": len(candidates),
                    "preview": [
                        {
                            "action": item["action"],
                            "source_device": item["item_device"],
                            "target": item["target_reference_json"],
                            "literal_target_quote": item["target_quote"],
                            "fingerprint": item["fingerprint"],
                        }
                        for item in candidates
                    ],
                }
            results.append(result)
        self.stdout.write(
            json.dumps(
                {"applied": bool(options["apply"]), "results": results},
                ensure_ascii=False,
                sort_keys=True,
            )
        )
