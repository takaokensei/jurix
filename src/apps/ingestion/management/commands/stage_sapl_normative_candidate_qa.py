"""Stage one explicitly identified, promulgated SAPL act as a QA candidate."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils.dateparse import parse_date

from src.apps.legislation.models import Norma
from src.clients.sapl.sapl_client import SaplAPIClient
from src.processing.document_metadata import build_normative_identity

_ALLOWED_RECORDS = {
    9406: {
        "number": "8219",
        "year": 2026,
        "type_id": 1,
        "identity_type": "lei ordinária",
        "identity_series": "municipal_lo",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2026/9406/lei_no_8.219_2026.pdf",
        "publication_date": date(2026, 10, 14),
        "display_type": "Lei Ordinária",
        "complement_flag": False,
    },
    3666: {
        "number": "1894",
        "year": 1969,
        "type_id": 1,
        "identity_type": "lei ordinária",
        "identity_series": "municipal_lo",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/1969/3666/lei01894-69.pdf",
        "publication_date": None,
        "display_type": "Lei Ordinária",
        "complement_flag": False,
    },
    4052: {
        "number": "258",
        "year": 2024,
        "type_id": 2,
        "identity_type": "lei complementar",
        "identity_series": "municipal_lc",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2024/4052/lei_complementar_no_258_2024.pdf",
        "publication_date": date(2024, 12, 27),
        "display_type": "Lei Complementar",
        "complement_flag": False,
    },
    1160: {
        "number": "208",
        "year": 2022,
        "type_id": 2,
        "identity_type": "lei complementar",
        "identity_series": "municipal_lc",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2022/1160/pdn_-_lc_208_2022.pdf",
        "publication_date": date(2022, 3, 8),
        "display_type": "Lei Complementar",
        "complement_flag": True,
    },
    8823: {
        "number": "261",
        "year": 2025,
        "type_id": 2,
        "identity_type": "lei complementar",
        "identity_series": "municipal_lc",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2025/8823/lei_complementar_no_261_2025.pdf",
        "publication_date": date(2025, 7, 4),
        "display_type": "Lei Complementar",
        "complement_flag": False,
    },
    925: {
        "number": "198",
        "year": 2021,
        "type_id": 2,
        "identity_type": "lei complementar",
        "identity_series": "municipal_lc",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2021/925/plc_006.21-convertido.pdf",
        "publication_date": date(2021, 12, 20),
        "display_type": "Lei Complementar",
        "complement_flag": False,
    },
    254: {
        "number": "562",
        "year": 2018,
        "type_id": 9,
        "identity_type": "lei promulgada",
        "identity_series": "municipal_lp",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2018/254/lp_562.18.pdf",
        "publication_date": date(2018, 9, 18),
        "display_type": "Lei Promulgada",
        "complement_flag": False,
    },
    6817: {
        "number": "4885",
        "year": 1997,
        "type_id": 1,
        "identity_type": "lei ordinária",
        "identity_series": "municipal_lo",
        "official_pdf": "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/1997/6817/lei04885-97.pdf",
        "publication_date": date(1997, 10, 8),
        "display_type": "Lei Ordinária",
        "complement_flag": False,
    },
}


def _validated_record(client: SaplAPIClient, sapl_id: int) -> tuple[dict, str, dict]:
    expected = _ALLOWED_RECORDS.get(sapl_id)
    if expected is None:
        raise ValueError("este comando QA aceita somente atos promulgados explicitamente autorizados")

    record = client.fetch_norma_by_id(sapl_id)
    pdf_url = client._validated_sapl_pdf_url(record.get("texto_integral", ""))
    if (
        record.get("id") != sapl_id
        or str(record.get("numero")) != expected["number"]
        or record.get("ano") != expected["year"]
        or record.get("tipo") != expected["type_id"]
        or record.get("complemento") is not expected["complement_flag"]
        or pdf_url != expected["official_pdf"]
    ):
        raise ValueError("o registro SAPL diverge da identidade promulgada esperada")

    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type=expected["identity_type"],
        series=expected["identity_series"],
        number=expected["number"],
        year=expected["year"],
    )
    if not identity.identity_key:
        raise ValueError("não foi possível construir a identidade normativa candidata")
    raw_publication_date = record.get("data_publicacao")
    if raw_publication_date in (None, ""):
        publication_date = None
    elif isinstance(raw_publication_date, str):
        publication_date = parse_date(raw_publication_date)
        if publication_date is None:
            raise ValueError("data de publicação SAPL tem formato inválido")
    else:
        raise ValueError("data de publicação SAPL tem formato inválido")
    if publication_date != expected["publication_date"]:
        raise ValueError("data de publicação do registro SAPL diverge da evidência conferida")

    # Deliberately omit `materia`, proposal metadata, authors, user IDs and IPs.
    safe_metadata = {
        "id": sapl_id,
        "tipo": expected["type_id"],
        "numero": expected["number"],
        "ano": expected["year"],
        "data": record.get("data"),
        "data_publicacao": publication_date.isoformat() if publication_date else None,
        "veiculo_publicacao": record.get("veiculo_publicacao"),
        "ementa": record.get("ementa", ""),
        "texto_integral": pdf_url,
    }
    return record, pdf_url, {
        "identity": identity,
        "publication_date": publication_date,
        "safe_metadata": safe_metadata,
    }


def _existing_norma_conflicts(norma, *, identity, expected, publication_date, pdf_url) -> list[str]:
    """List mismatching field names only; never expose stored legal text or metadata."""
    conflicts = []
    # A legacy pending Norma row for SAPL 254 predates the stable identity-key
    # migration. Its SAPL ID plus the independently validated type/number/year
    # are sufficient to attach a *pending source document*; never backfill or
    # change the legacy identity here.
    legacy_lp562_identity_missing = norma.sapl_id == 254 and norma.identity_key is None
    if norma.identity_key != identity.identity_key and not legacy_lp562_identity_missing:
        conflicts.append("identity_key")
    if norma.tipo != expected["display_type"]:
        conflicts.append("tipo")
    if norma.numero != identity.identity_json["number"]:
        conflicts.append("numero")
    if norma.ano != identity.identity_json["year"]:
        conflicts.append("ano")
    if norma.data_publicacao != publication_date:
        conflicts.append("data_publicacao")
    if norma.pdf_url != pdf_url:
        conflicts.append("pdf_url")
    metadata = norma.sapl_metadata if isinstance(norma.sapl_metadata, dict) else {}
    if "materia" in metadata:
        conflicts.append("sapl_metadata.materia")
    if norma.status != Norma.Status.PENDING:
        conflicts.append("status")
    if norma.documento_base_id is not None:
        conflicts.append("documento_base")
    if norma.texto_original:
        conflicts.append("texto_original_nao_vazio")
    if norma.texto_consolidado:
        conflicts.append("texto_consolidado_nao_vazio")
    return conflicts


def stage_sapl_normative_candidate(
    *, sapl_id: int, apply: bool = False, inspect_existing: bool = False
) -> dict:
    """Register official identity and PDF as pending; never accept or consolidate it."""
    if (
        os.environ.get("JURIX_QA_ONLY") != "1"
        or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
        or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
    ):
        raise ValueError("operação disponível somente no ambiente QA normativo isolado")

    client = SaplAPIClient(timeout=20, max_retries=1)
    try:
        _record, pdf_url, candidate = _validated_record(client, sapl_id)
        expected = _ALLOWED_RECORDS[sapl_id]
        fingerprint = client.fingerprint_pdf(pdf_url)
        if not fingerprint.startswith(("sha256:", "etag:", "last-modified:")):
            raise ValueError("fingerprint remoto SAPL inválido")
        if not apply:
            existing = Norma.objects.filter(sapl_id=sapl_id).first() if inspect_existing else None
            existing_conflicts = (
                _existing_norma_conflicts(
                    existing,
                    identity=candidate["identity"],
                    expected=expected,
                    publication_date=candidate["publication_date"],
                    pdf_url=pdf_url,
                )
                if existing
                else []
            )
            return {
                "mode": "dry-run",
                "sapl_id": sapl_id,
                "identity_key": candidate["identity"].identity_key,
                "publication_date": (
                    candidate["publication_date"].isoformat()
                    if candidate["publication_date"]
                    else None
                ),
                "remote_fingerprint_kind": fingerprint.split(":", 1)[0],
                "existing_record_inspected": inspect_existing,
                "existing_norma_conflicts": existing_conflicts,
                "will_create_norma": existing is None,
                "will_create_pending_pdf_candidate": not existing_conflicts,
                "eligible_to_stage": not existing_conflicts,
                "will_accept_text": False,
                "will_create_consolidation": False,
                "matter_metadata_imported": False,
            }

        identity = candidate["identity"]
        with transaction.atomic():
            norma, created = Norma.objects.get_or_create(
                sapl_id=sapl_id,
                defaults={
                    "tipo": expected["display_type"],
                    "numero": identity.identity_json["number"],
                    "ano": identity.identity_json["year"],
                    "ementa": candidate["safe_metadata"]["ementa"],
                    "data_publicacao": candidate["publication_date"],
                    "data_norma": parse_date(candidate["safe_metadata"].get("data", "")),
                    "pdf_url": pdf_url,
                    "sapl_url": client.get_public_norma_url(sapl_id),
                    "sapl_metadata": {
                        **candidate["safe_metadata"],
                        "_jurix_type_catalog": {
                            "public_label": expected["display_type"]
                        },
                    },
                    "identity_key": identity.identity_key,
                    "identity_json": identity.identity_json,
                    "status": Norma.Status.PENDING,
                    "needs_review": True,
                },
            )
            conflicts = _existing_norma_conflicts(
                norma,
                identity=identity,
                expected=expected,
                publication_date=candidate["publication_date"],
                pdf_url=pdf_url,
            )
            if conflicts:
                raise ValueError(
                    "registro existente diverge do candidato pendente nos campos: "
                    + ", ".join(conflicts)
                )

            from src.apps.ingestion.sapl_document_sync import stage_sapl_pdf_candidate

            document, document_created = stage_sapl_pdf_candidate(
                client=client,
                norma=norma,
                pdf_url=pdf_url,
                remote_fingerprint=fingerprint,
            )
            if (
                document.review_status != document.ReviewStatus.PENDING
                or document.accepted_extraction_id is not None
                or document.norma_id != norma.pk
            ):
                raise ValueError("PDF não permaneceu como candidato pendente e não aceito")

        return {
            "mode": "applied",
            "sapl_id": sapl_id,
            "norma_id": norma.pk,
            "norma_created": created,
            "document_id": str(document.public_id),
            "document_created": document_created,
            "review_status": document.review_status,
            "norma_status": norma.status,
            "text_accepted": document.accepted_extraction_id is not None,
            "norma_linked_as_base": norma.documento_base_id is not None,
            "matter_metadata_imported": False,
            "remote_fingerprint_sha256": hashlib.sha256(fingerprint.encode()).hexdigest(),
        }
    finally:
        client.close()


class Command(BaseCommand):
    help = "Stage one fixed, promulgated SAPL act as a pending isolated-QA candidate."

    def add_arguments(self, parser):
        parser.add_argument("--sapl-id", required=True, type=int)
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--inspect-existing", action="store_true")

    def handle(self, *args, **options):
        try:
            result = stage_sapl_normative_candidate(
                sapl_id=options["sapl_id"],
                apply=options["apply"],
                inspect_existing=options["inspect_existing"],
            )
        except (OSError, RuntimeError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
