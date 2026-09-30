"""Repair already-segmented norms whose final article absorbed the OCR colophon."""

from __future__ import annotations

import re

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.models import Dispositivo, Norma
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.legal_parser import (
    LegalTextParser,
    extract_publication_metadata,
    strip_closing_editorial_metadata,
)


def _normalized_article_number(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(value or "").casefold())


class Command(BaseCommand):
    help = (
        "Repara, sem recriar dispositivos nem apagar eventos, artigos finais que "
        "absorveram assinaturas/metadata editorial do OCR."
    )

    def add_arguments(self, parser):
        parser.add_argument("--norma-id", type=int, action="append", dest="norma_ids")
        parser.add_argument("--all", action="store_true", dest="all_normas")
        parser.add_argument(
            "--apply",
            action="store_true",
            help="Grava as correções. Sem esta opção, apenas mostra o que seria alterado.",
        )

    def handle(self, *args, **options):
        norma_ids = options["norma_ids"] or []
        if not options["all_normas"] and not norma_ids:
            raise CommandError("Informe --norma-id ID (repetível) ou --all.")

        queryset = Norma.objects.filter(texto_original__gt="").order_by("pk")
        if not options["all_normas"]:
            queryset = queryset.filter(pk__in=norma_ids)

        changed = 0
        examined = 0
        for norma_id in queryset.values_list("pk", flat=True).iterator():
            examined += 1
            result = self._repair_one(norma_id, apply=options["apply"])
            if result:
                changed += 1
                action = "Corrigida" if options["apply"] else "Correção disponível"
                self.stdout.write(f"{action}: {result}")

        if options["apply"] and changed:
            from src.apps.ingestion.task_support import _invalidate_rag_cache

            _invalidate_rag_cache()

        mode = "aplicadas" if options["apply"] else "encontradas (dry-run)"
        self.stdout.write(self.style.SUCCESS(f"Normas analisadas: {examined}; correções {mode}: {changed}."))

    @staticmethod
    def _repair_one(norma_id: int, *, apply: bool) -> str | None:
        with transaction.atomic():
            norma = Norma.objects.select_for_update().filter(pk=norma_id).first()
            if not norma or not norma.texto_original:
                return None

            parser = LegalTextParser()
            parsed_articles = [
                item for item in parser.parse_legal_text(norma.texto_original)
                if item["tipo"] == "artigo"
            ]
            dispositivos = list(
                Dispositivo.objects.filter(norma=norma, tipo="artigo").order_by("ordem", "pk")
            )
            if not parsed_articles or not dispositivos:
                return None

            source_article = parsed_articles[-1]
            stored_article = dispositivos[-1]
            if _normalized_article_number(source_article["numero"]) != _normalized_article_number(stored_article.numero):
                return None

            synthetic_article = f"Art. {stored_article.numero}\n{stored_article.texto}"
            cleaned_stored = strip_closing_editorial_metadata(synthetic_article)
            parsed_text = parser.clean_text(source_article["texto"])
            article_needs_repair = (
                cleaned_stored != synthetic_article
                and parser.clean_text(stored_article.texto) != parsed_text
            )

            metadata = extract_publication_metadata(norma.texto_original)
            publication_date = norma.data_publicacao or metadata["data_publicacao"]
            effective_date = norma.data_vigencia
            if not effective_date and metadata["vigencia_na_publicacao"]:
                effective_date = publication_date
            metadata_needs_repair = (
                (not norma.data_publicacao and bool(metadata["data_publicacao"]))
                or (not norma.data_vigencia and bool(effective_date))
            )

            if not article_needs_repair and not metadata_needs_repair:
                return None

            changes = []
            if article_needs_repair:
                changes.append(f"Art. {stored_article.numero} sem fecho editorial")
            if not norma.data_publicacao and metadata["data_publicacao"]:
                changes.append(f"publicação {metadata['data_publicacao']}")
            if not norma.data_vigencia and effective_date:
                changes.append(f"vigência {effective_date}")

            if apply:
                if article_needs_repair:
                    stored_article.texto = parsed_text
                    stored_article.save(update_fields=["texto", "updated_at"])

                update_fields = []
                if not norma.data_publicacao and metadata["data_publicacao"]:
                    norma.data_publicacao = metadata["data_publicacao"]
                    update_fields.append("data_publicacao")
                if not norma.data_vigencia and effective_date:
                    norma.data_vigencia = effective_date
                    update_fields.append("data_vigencia")
                if article_needs_repair or metadata_needs_repair:
                    # Rebuild derived text without recreating Dispositivo rows;
                    # their stable IDs preserve EventoAlteracao references.
                    norma.texto_consolidado = ConsolidationEngine(norma).consolidate()
                    update_fields.append("texto_consolidado")
                if update_fields:
                    norma.updated_at = timezone.now()
                    update_fields.append("updated_at")
                    norma.save(update_fields=update_fields)

        return f"{norma} (ID {norma_id}): " + ", ".join(changes)
