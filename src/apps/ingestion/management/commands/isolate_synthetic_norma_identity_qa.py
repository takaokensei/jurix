"""Give one synthetic QA Norma an internal identity without deleting its graph."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from src.apps.legislation.document_models import NormativeSnapshot
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma


def _is_isolated_qa_database() -> bool:
    database = settings.DATABASES.get("default", {})
    host_qa = (
        database.get("ENGINE") == "django.db.backends.postgresql"
        and database.get("HOST") == "127.0.0.1"
        and str(database.get("PORT")) == "55432"
        and database.get("USER") == "jurix_audit"
        and database.get("NAME") == "jurix_audit"
    )
    container_qa = (
        os.environ.get("DJANGO_SETTINGS_MODULE") == "config.settings_normative_container_qa"
        and database.get("ENGINE") == "django.db.backends.postgresql"
        and database.get("HOST") == "db"
        and str(database.get("PORT")) == "5432"
        and database.get("USER") == "jurix_audit"
        and database.get("NAME") == "jurix_audit"
    )
    return os.environ.get("JURIX_QA_ONLY") == "1" and (host_qa or container_qa)


def isolate_synthetic_norma_identity(
    *,
    norma_id: int,
    expected_identity_key: str,
    expected_tipo: str,
    expected_numero: str,
    expected_ano: int,
    apply: bool = False,
) -> dict:
    """Namespace one marked fixture while preserving all its linked rows."""
    if not _is_isolated_qa_database():
        raise ValueError("operação restrita ao banco normativo QA isolado")

    with transaction.atomic():
        norma = (
            Norma.objects.select_for_update(of=("self",))
            .select_related("documento_base")
            .get(pk=norma_id)
        )
        identity_json = norma.identity_json if isinstance(norma.identity_json, dict) else {}
        base_metadata = (
            norma.documento_base.metadata_json
            if norma.documento_base and isinstance(norma.documento_base.metadata_json, dict)
            else {}
        )
        if (
            norma.identity_key != expected_identity_key
            or norma.tipo != expected_tipo
            or norma.numero != expected_numero
            or norma.ano != expected_ano
            or identity_json.get("synthetic_fixture") is not True
            or base_metadata.get("synthetic") is not True
        ):
            raise ValueError("Norma não corresponde à fixture sintética esperada; nenhuma alteração feita")

        new_type = f"QA fixture — {norma.tipo}"
        new_identity_key = f"synthetic-fixture|{norma.pk}|{norma.identity_key}"
        if len(new_type) > Norma._meta.get_field("tipo").max_length:
            raise ValueError("rótulo interno excede o limite do campo")
        if len(new_identity_key) > Norma._meta.get_field("identity_key").max_length:
            raise ValueError("chave interna excede o limite do campo")
        if Norma.objects.filter(identity_key=new_identity_key).exclude(pk=norma.pk).exists():
            raise ValueError("namespace interno já está ocupado")

        result = {
            "mode": "dry-run" if not apply else "applied",
            "norma_id": norma.pk,
            "old_tipo": norma.tipo,
            "new_tipo": new_type,
            "old_identity_key": norma.identity_key,
            "new_identity_key": new_identity_key,
            "identity_json_preserved": True,
            "document_base_id": norma.documento_base_id,
            "device_count": Dispositivo.objects.filter(norma=norma).count(),
            "events_as_source": EventoAlteracao.objects.filter(
                dispositivo_fonte__norma=norma
            ).count(),
            "events_as_target": EventoAlteracao.objects.filter(norma_alvo=norma).count(),
            "snapshot_count": NormativeSnapshot.objects.filter(norma=norma).count(),
            "persisted": False,
        }
        if apply:
            norma.tipo = new_type
            norma.identity_key = new_identity_key
            norma.save(update_fields=["tipo", "identity_key", "updated_at"])
            result["persisted"] = True
        return result


class Command(BaseCommand):
    help = "Planeja ou isola uma fixture sintética sem apagar seus vínculos; somente QA isolado."

    def add_arguments(self, parser):
        parser.add_argument("--norma-id", type=int, required=True)
        parser.add_argument("--expected-identity-key", required=True)
        parser.add_argument("--expected-tipo", required=True)
        parser.add_argument("--expected-numero", required=True)
        parser.add_argument("--expected-ano", type=int, required=True)
        parser.add_argument("--apply", action="store_true")

    def handle(self, *args, **options):
        try:
            result = isolate_synthetic_norma_identity(
                norma_id=options["norma_id"],
                expected_identity_key=options["expected_identity_key"],
                expected_tipo=options["expected_tipo"],
                expected_numero=options["expected_numero"],
                expected_ano=options["expected_ano"],
                apply=options["apply"],
            )
        except (ValueError, Norma.DoesNotExist) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(result, ensure_ascii=False, sort_keys=True))
