"""Plan and, only with explicit approval, repair legacy OCR colophons."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.processing.consolidation_engine import ConsolidationEngine
from src.processing.device_revision import revision_fingerprint
from src.processing.legal_parser import (
    LegalTextParser,
    extract_publication_metadata,
    strip_closing_editorial_metadata,
)


def _normalized_article_number(value: str) -> str:
    return re.sub(r"[^0-9a-z]", "", str(value or "").casefold())


def _digest(value: str) -> str:
    return hashlib.sha256((value or "").encode("utf-8")).hexdigest()


def _manifest_digest(schema_version: int, entries: list[dict]) -> str:
    payload = json.dumps(
        {"schema_version": schema_version, "entries": entries},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return _digest(payload)


class Command(BaseCommand):
    help = (
        "Gera plano reversível para reparar colofões OCR. Apply exige manifesto aprovado, "
        "hash explícito e confirmação de backup verificado."
    )

    def add_arguments(self, parser):
        parser.add_argument("--norma-id", type=int, action="append", dest="norma_ids")
        parser.add_argument("--all", action="store_true", dest="all_normas")
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--manifest-out", type=Path)
        parser.add_argument("--approved-manifest", type=Path)
        parser.add_argument("--expected-manifest-sha256")
        parser.add_argument("--backup-verified", action="store_true")

    def handle(self, *args, **options):
        norma_ids = options["norma_ids"] or []
        if not options["all_normas"] and not norma_ids:
            raise CommandError("Informe --norma-id ID (repetível) ou --all.")
        applying = options["apply"]
        if applying and not (
            options["approved_manifest"]
            and options["expected_manifest_sha256"]
            and options["backup_verified"]
        ):
            raise CommandError(
                "--apply exige --approved-manifest, --expected-manifest-sha256 e "
                "--backup-verified. Nenhuma norma foi alterada."
            )
        if not applying and any(
            (
                options["approved_manifest"],
                options["expected_manifest_sha256"],
                options["backup_verified"],
            )
        ):
            raise CommandError("Opções de aprovação/backup só podem ser usadas junto com --apply.")

        queryset = Norma.objects.filter(texto_original__gt="").order_by("pk")
        if not options["all_normas"]:
            queryset = queryset.filter(pk__in=norma_ids)
        proposals = [
            proposal
            for norma_id in queryset.values_list("pk", flat=True).iterator()
            if (proposal := self._proposal(norma_id)) is not None
        ]
        manifest = {
            "schema_version": 1,
            "entries": proposals,
            "sha256": _manifest_digest(1, proposals),
        }

        if applying:
            manifest_path = options["approved_manifest"]
            try:
                approved = json.loads(manifest_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise CommandError(
                    "Manifesto aprovado não pôde ser lido como JSON válido."
                ) from exc
            expected = str(options["expected_manifest_sha256"]).lower()
            if approved.get("schema_version") != 1 or not isinstance(approved.get("entries"), list):
                raise CommandError("Schema do manifesto aprovado não é suportado.")
            actual_approved_hash = _manifest_digest(1, approved["entries"])
            if actual_approved_hash != expected or approved.get("sha256") != actual_approved_hash:
                raise CommandError(
                    "Hash do manifesto aprovado não confere; nenhuma alteração feita."
                )
            if manifest["sha256"] != actual_approved_hash:
                raise CommandError(
                    "O estado atual diverge do manifesto aprovado (stale); nenhuma alteração feita."
                )
            conflicts_without_text_fix = [
                entry
                for entry in proposals
                if entry["publication_date_divergence"] and not entry["article_changes"]
            ]
            if conflicts_without_text_fix:
                ids = ", ".join(str(entry["norma_id"]) for entry in conflicts_without_text_fix)
                raise CommandError(
                    "Datas SAPL/OCR divergem e não há correção de texto legal independente "
                    f"para as normas {ids}; nenhuma alteração feita."
                )
            self._apply_proposals(proposals)
            from src.apps.ingestion.task_support import _invalidate_rag_cache

            if proposals:
                _invalidate_rag_cache()
            message = f"Correções aplicadas: {len(proposals)}. Manifesto: {actual_approved_hash}."
            self.stdout.write(self.style.SUCCESS(message))
            conflict_count = sum(entry["publication_date_divergence"] for entry in proposals)
            if conflict_count:
                self.stdout.write(
                    self.style.WARNING(
                        f"Datas SAPL/OCR divergentes preservadas sem alteração: {conflict_count}. "
                        "As normas permanecem marcadas para revisão."
                    )
                )
            return

        if options["manifest_out"]:
            path = options["manifest_out"].resolve()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
            )
            self.stdout.write(f"Manifesto dry-run gravado: {path}")
        for proposal in proposals:
            self.stdout.write(
                f"Correção disponível: Norma ID {proposal['norma_id']}, "
                f"Art. {proposal['article_number']} — "
                f"publicação OCR: {proposal['ocr_publication_date'] or 'não identificada'}"
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Normas analisadas: {queryset.count()}; correções encontradas (dry-run): "
                f"{len(proposals)}; sha256: {manifest['sha256']}."
            )
        )

    @classmethod
    def _proposal(cls, norma_id: int) -> dict | None:
        norma = Norma.objects.filter(pk=norma_id).first()
        if not norma or not norma.texto_original:
            return None
        parser = LegalTextParser()
        parsed_articles = [
            item
            for item in parser.parse_legal_text(norma.texto_original)
            if item["tipo"] == "artigo"
        ]
        devices = list(
            Dispositivo.objects.filter(norma=norma, tipo="artigo", is_active=True).order_by(
                "ordem", "pk"
            )
        )
        if not parsed_articles or not devices:
            return None
        source_article = parsed_articles[-1]
        stored_article = devices[-1]
        if _normalized_article_number(source_article["numero"]) != _normalized_article_number(
            stored_article.numero
        ):
            return None

        synthetic_article = f"Art. {stored_article.numero}\n{stored_article.texto}"
        cleaned_stored = strip_closing_editorial_metadata(synthetic_article)
        proposed_text = parser.clean_text(source_article["texto"])
        article_changes = (
            cleaned_stored != synthetic_article
            and parser.clean_text(stored_article.texto) != proposed_text
        )
        metadata = extract_publication_metadata(norma.texto_original)
        proposed_publication = norma.data_publicacao or metadata["data_publicacao"]
        proposed_effective = norma.data_vigencia
        if not proposed_effective and metadata["vigencia_na_publicacao"]:
            proposed_effective = proposed_publication
        publication_changes = not norma.data_publicacao and bool(metadata["data_publicacao"])
        effective_changes = not norma.data_vigencia and bool(proposed_effective)
        if not (article_changes or publication_changes or effective_changes):
            return None

        return {
            "norma_id": norma.pk,
            "sapl_url": norma.sapl_url or "",
            "article_id": stored_article.pk,
            "article_number": stored_article.numero,
            "article_before_sha256": _digest(stored_article.texto),
            "article_after_sha256": _digest(proposed_text)
            if article_changes
            else _digest(stored_article.texto),
            "article_changes": article_changes,
            "source_ocr_sha256": _digest(norma.texto_original),
            "sapl_publication_date": norma.data_publicacao.isoformat()
            if norma.data_publicacao
            else None,
            "ocr_publication_date": metadata["data_publicacao"].isoformat()
            if metadata["data_publicacao"]
            else None,
            "publication_date_divergence": bool(
                norma.data_publicacao
                and metadata["data_publicacao"]
                and norma.data_publicacao != metadata["data_publicacao"]
            ),
            "publication_before": norma.data_publicacao.isoformat()
            if norma.data_publicacao
            else None,
            "publication_after": proposed_publication.isoformat() if proposed_publication else None,
            "effective_before": norma.data_vigencia.isoformat() if norma.data_vigencia else None,
            "effective_after": proposed_effective.isoformat() if proposed_effective else None,
            "consolidated_before_sha256": _digest(norma.texto_consolidado),
        }

    @classmethod
    def _apply_proposals(cls, proposals: list[dict]) -> None:
        for approved in proposals:
            with transaction.atomic():
                norma = Norma.objects.select_for_update().get(pk=approved["norma_id"])
                current = cls._proposal(norma.pk)
                if current != approved:
                    raise CommandError(
                        f"Proposta para Norma ID {norma.pk} mudou após aprovação; "
                        "transação cancelada."
                    )
                article = Dispositivo.objects.select_for_update().get(pk=approved["article_id"])
                parser = LegalTextParser()
                parsed_articles = [
                    item
                    for item in parser.parse_legal_text(norma.texto_original)
                    if item["tipo"] == "artigo"
                ]
                if approved["article_changes"]:
                    article.texto = parser.clean_text(parsed_articles[-1]["texto"])
                    article.revision_fingerprint = revision_fingerprint(
                        article.texto, article.texto_bruto
                    )
                    article.embedding = None
                    article.embedding_model = ""
                    article.embedding_generated_at = None
                    article.embedding_revision_fingerprint = ""
                    article.save(
                        update_fields=[
                            "texto",
                            "revision_fingerprint",
                            "embedding",
                            "embedding_model",
                            "embedding_generated_at",
                            "embedding_revision_fingerprint",
                            "updated_at",
                        ]
                    )
                    EventoAlteracao.objects.filter(
                        dispositivo_fonte=article, is_active=True
                    ).update(is_active=False)
                    norma.needs_review = True
                    update_fields = ["needs_review"]
                else:
                    update_fields = []
                if not approved["publication_date_divergence"]:
                    if approved["publication_before"] is None and approved["publication_after"]:
                        norma.data_publicacao = approved["publication_after"]
                        update_fields.append("data_publicacao")
                    if approved["effective_before"] is None and approved["effective_after"]:
                        norma.data_vigencia = approved["effective_after"]
                        update_fields.append("data_vigencia")
                if approved["article_changes"]:
                    norma.texto_consolidado = ConsolidationEngine(norma).consolidate()
                    update_fields.append("texto_consolidado")
                if update_fields:
                    norma.updated_at = timezone.now()
                    update_fields.append("updated_at")
                    norma.save(update_fields=update_fields)
