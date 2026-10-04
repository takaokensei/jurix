"""Manually enqueue and dispatch bounded normative work in isolated QA only."""

from __future__ import annotations

import json
import os

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Q
from django.utils import timezone

from src.apps.ingestion.normative_impact import safe_norma_revision
from src.apps.ingestion.normative_tasks import (
    enqueue_normative_impact_task,
    process_normative_work_item_task,
)
from src.apps.legislation.models import Norma
from src.apps.operations.models import NormativeWorkItem


class Command(BaseCommand):
    help = "Enfileira/trabalha no máximo dez itens de impacto normativo na base QA isolada."

    def add_arguments(self, parser):
        source = parser.add_mutually_exclusive_group(required=True)
        source.add_argument("--norma-id", type=int, help="Norma local já existente no banco QA.")
        source.add_argument(
            "--item-id", action="append", type=int, default=[],
            help="ID de item pendente existente; pode ser repetido até dez vezes.",
        )
        parser.add_argument("--max-nodes", type=int, default=10)
        parser.add_argument("--max-items", type=int, default=10)

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ENABLED", False)
        ):
            raise CommandError("Este comando exige o ambiente QA normativo isolado.")

        max_items = options["max_items"]
        if not 1 <= max_items <= 10:
            raise CommandError("--max-items deve ficar entre 1 e 10.")
        norma_id = options["norma_id"]
        item_ids = list(dict.fromkeys(options["item_id"] or []))
        if norma_id:
            max_nodes = options["max_nodes"]
            if not 1 <= max_nodes <= 50:
                raise CommandError("--max-nodes deve ficar entre 1 e 50.")
            norma = Norma.objects.get(pk=norma_id)
            revision = safe_norma_revision(norma)
            if not revision:
                raise CommandError("A norma não possui revisão textual/documental verificável.")
            queued = enqueue_normative_impact_task.apply(
                args=[norma.pk, revision], kwargs={"max_nodes": max_nodes}, throw=True
            ).get()
            dispatchable = set(
                NormativeWorkItem.objects.filter(
                    pk__in=queued["item_ids"], status=NormativeWorkItem.Status.PENDING
                ).values_list("pk", flat=True)
            )
            item_ids = [item_id for item_id in queued["item_ids"] if item_id in dispatchable][:max_items]
            created = queued["created"]
        else:
            if len(item_ids) > 10:
                raise CommandError("Informe no máximo dez --item-id por execução.")
            dispatchable = set(
                NormativeWorkItem.objects.filter(pk__in=item_ids).filter(
                    Q(status=NormativeWorkItem.Status.PENDING)
                    | Q(status=NormativeWorkItem.Status.LEASED, lease_until__lte=timezone.now())
                ).values_list("pk", flat=True)
            )
            missing = sorted(set(item_ids) - dispatchable)
            if missing:
                raise CommandError(f"Itens inexistentes, ativos ou não recuperáveis: {missing}")
            item_ids = item_ids[:max_items]
            created = 0

        if item_ids:
            for item_id in item_ids:
                process_normative_work_item_task.apply_async(
                    args=[item_id], queue="normative_qa"
                )

        remaining = NormativeWorkItem.objects.filter(
            status=NormativeWorkItem.Status.PENDING
        ).count()
        self.stdout.write(json.dumps({
            "created": created,
            "dispatched": len(item_ids),
            "item_ids": item_ids,
            "pending_after_dispatch": remaining,
            "queue": "normative_qa",
            "review_gates_enabled": True,
        }, ensure_ascii=False, sort_keys=True))
