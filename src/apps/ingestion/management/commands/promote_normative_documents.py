"""Promote one explicitly reviewed document to an existing matching Norma."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from src.apps.ingestion.document_promotion import PromotionBlocked, promote_document
from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma


class Command(BaseCommand):
    help = "QA-only promotion; requires staff actor, current fingerprint, reason and explicit confirmations."

    def add_arguments(self, parser):
        parser.add_argument("--plan-legacy", action="store_true", help="Emite plano de leitura, sem escrever no banco.")
        parser.add_argument("--output", type=Path)
        parser.add_argument("--document")
        parser.add_argument("--norma-id", type=int)
        parser.add_argument("--actor")
        parser.add_argument("--reason")
        parser.add_argument("--fingerprint")
        parser.add_argument("--identity-key")
        parser.add_argument("--role", choices=[DocumentoNormativo.Role.ORIGINAL])
        parser.add_argument("--confirm-public-record", action="store_true")

    def handle(self, *args, **options):
        if not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False):
            raise CommandError("promoção desabilitada fora do QA")
        if options["plan_legacy"]:
            qa_root = Path(os.environ.get("JURIX_QA_ROOT", "")).resolve()
            output = options["output"]
            if output is None or not qa_root.is_dir() or not output.resolve().is_relative_to(qa_root):
                raise CommandError("--plan-legacy exige --output dentro da raiz QA")
            if output.exists():
                raise CommandError("recusando sobrescrever relatório legado existente")
            rows = []
            for norma in Norma.objects.filter(documento_base__isnull=True).exclude(texto_original="").order_by("pk"):
                encoded = norma.texto_original.encode("utf-8")
                rows.append({
                    "norma_id": norma.pk,
                    "sapl_id": norma.sapl_id,
                    "tipo": norma.tipo,
                    "numero": norma.numero,
                    "ano": norma.ano,
                    "legacy_text_sha256": hashlib.sha256(encoded).hexdigest(),
                    "legacy_text_bytes": len(encoded),
                    "status": "candidate_unverified_origin",
                })
            payload = {"schema_version": 1, "mode": "read_only_plan", "count": len(rows), "candidates": rows}
            with output.open("x", encoding="utf-8", newline="\n") as stream:
                json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
                stream.write("\n")
            self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
            return
        required = ("document", "norma_id", "actor", "reason", "fingerprint", "identity_key", "role")
        if any(options[name] in (None, "") for name in required):
            raise CommandError("promoção exige documento, norma, revisor, motivo, fingerprint, identidade e papel")
        try:
            actor = get_user_model().objects.get(username=options["actor"])
            result = promote_document(
                document_id=options["document"], norma_id=options["norma_id"], actor=actor,
                reason=options["reason"], expected_fingerprint=options["fingerprint"],
                confirmed_identity_key=options["identity_key"], confirmed_role=options["role"],
                confirm_public_record=options["confirm_public_record"],
            )
        except (get_user_model().DoesNotExist, DocumentoNormativo.DoesNotExist, ValueError, PromotionBlocked) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
