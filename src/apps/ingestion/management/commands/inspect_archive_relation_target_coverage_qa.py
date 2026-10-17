"""Read-only identity coverage for extracted archive relation candidates in QA."""

from __future__ import annotations

import json
import os
from collections import Counter, defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from src.apps.legislation.document_models import (
    DocumentoNormativo,
    EventoNormativoCandidato,
)
from src.apps.legislation.models import Norma
from src.processing.document_metadata import (
    is_natal_municipal_jurisdiction,
    normalize_document_number,
)
from src.processing.normative_reference import canonical_type


def _is_synthetic(metadata: dict) -> bool:
    identity = metadata.get("identity_candidate")
    identity = identity if isinstance(identity, dict) else {}
    return any(
        value is True
        for value in (
            metadata.get("synthetic"),
            metadata.get("synthetic_fixture"),
            identity.get("synthetic"),
            identity.get("synthetic_fixture"),
        )
    )


def _is_synthetic_norma(norma: Norma) -> bool:
    identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    return identity.get("synthetic") is True or identity.get("synthetic_fixture") is True


def relation_target_coverage(candidates, documents, normas=()) -> dict:
    """Summarize exact metadata matches without resolving a legal relationship."""
    document_index = defaultdict(list)
    for document in documents:
        metadata = document.metadata_json if isinstance(document.metadata_json, dict) else {}
        identity = metadata.get("identity_candidate")
        if not isinstance(identity, dict) or _is_synthetic(metadata):
            continue
        if not is_natal_municipal_jurisdiction(str(identity.get("jurisdiction") or "")):
            continue
        try:
            year = int(identity.get("year"))
        except (TypeError, ValueError):
            continue
        number = normalize_document_number(str(identity.get("number") or ""))
        if not number:
            continue
        edition = metadata.get("edition_candidate")
        edition = edition if isinstance(edition, dict) else {}
        document_index[(year, number)].append(
            (
                canonical_type(str(identity.get("type") or "")),
                document.source_kind,
                edition.get("kind"),
                edition.get("declared_value_year"),
            )
        )

    overall = Counter()
    registry_overall = Counter()
    by_action = defaultdict(Counter)
    registry_by_action = defaultdict(Counter)
    source_documents = defaultdict(set)
    missing_registry_targets = Counter()
    norma_index = defaultdict(list)
    for norma in normas:
        if _is_synthetic_norma(norma):
            continue
        identity = norma.identity_json if isinstance(norma.identity_json, dict) else {}
        if not is_natal_municipal_jurisdiction(
            str(identity.get("jurisdiction") or "")
        ):
            continue
        try:
            year = int(norma.ano)
        except (TypeError, ValueError):
            continue
        number = normalize_document_number(str(norma.numero or ""))
        if not number:
            continue
        type_key = canonical_type(str(identity.get("type") or norma.tipo or ""))
        norma_index[(year, number)].append(type_key)

    for candidate in candidates:
        source_document = candidate.extracao.documento
        source_metadata = (
            source_document.metadata_json
            if isinstance(source_document.metadata_json, dict)
            else {}
        )
        source_identity = source_metadata.get("identity_candidate")
        if (
            source_document.source_kind
            not in {
                DocumentoNormativo.SourceKind.ARCHIVE,
                DocumentoNormativo.SourceKind.SAPL,
            }
            or _is_synthetic(source_metadata)
            or not isinstance(source_identity, dict)
            or not is_natal_municipal_jurisdiction(
                str(source_identity.get("jurisdiction") or "")
            )
        ):
            continue
        reference = candidate.target_reference_json
        if not isinstance(reference, dict):
            reference = {}
        year = None
        number = ""
        type_key = ""
        try:
            year = int(reference.get("year_candidate"))
        except (TypeError, ValueError):
            category = "missing_target_identity"
            registry_category = "missing_target_identity"
        else:
            number = normalize_document_number(str(reference.get("number_candidate") or ""))
            type_key = canonical_type(str(reference.get("type_candidate") or ""))
            matches = document_index.get((year, number), []) if number and type_key else []
            exact = [match for match in matches if match[0] == type_key]
            norma_matches = norma_index.get((year, number), []) if number and type_key else []
            exact_normas = [match for match in norma_matches if match == type_key]
            if not matches:
                category = "target_document_absent"
            elif not exact:
                category = "species_conflict_only"
            elif len(exact) == 1:
                category = "one_exact_document_identity"
            elif (
                all(match[2] == "official_consolidated_text" for match in exact)
                and all(isinstance(match[3], int) for match in exact)
                and len({match[3] for match in exact}) == len(exact)
            ):
                # Distinct official consolidated editions are multiple temporal
                # evidence snapshots of one cited legal identity, not competing
                # identities. They remain unreviewed documents and do not prove
                # the current wording or legal effect.
                category = "multiple_official_consolidated_editions"
            else:
                category = "multiple_exact_document_identities"
            if not norma_matches:
                registry_category = "target_norma_identity_absent"
            elif not exact_normas:
                registry_category = "species_conflict_only"
            elif len(exact_normas) == 1:
                registry_category = "one_exact_norma_identity"
            else:
                registry_category = "multiple_exact_norma_identities"
        overall[category] += 1
        registry_overall[registry_category] += 1
        by_action[candidate.action][category] += 1
        registry_by_action[candidate.action][registry_category] += 1
        source_documents[candidate.action].add(candidate.extracao.documento_id)
        if registry_category in {
            "target_norma_identity_absent",
            "species_conflict_only",
        } and year is not None and number and type_key:
            missing_registry_targets[
                (type_key, number, year, category, registry_category)
            ] += 1

    return {
        "candidate_count": sum(overall.values()),
        "source_document_count": len(
            {document_id for values in source_documents.values() for document_id in values}
        ),
        "target_identity_categories": dict(sorted(overall.items())),
        "target_norma_registry_categories": dict(sorted(registry_overall.items())),
        "most_repeated_registry_gaps": [
            {
                "type": identity[0],
                "number": identity[1],
                "year": identity[2],
                "document_match_status": identity[3],
                "registry_match_status": identity[4],
                "candidate_count": count,
            }
            for identity, count in missing_registry_targets.most_common(25)
        ],
        "by_action": {
            action: {
                "candidate_count": sum(counts.values()),
                "source_document_count": len(source_documents[action]),
                "target_identity_categories": dict(sorted(counts.items())),
                "target_norma_registry_categories": dict(
                    sorted(registry_by_action[action].items())
                ),
            }
            for action, counts in sorted(by_action.items())
        },
        "interpretation": (
            "Identity matches are document-discovery leads only. They do not verify the quote, "
            "relation, legal effect, text in force, or effective dates. No records were changed."
        ),
    }


class Command(BaseCommand):
    help = "Mede cobertura de identidade dos alvos candidatos, sem alterar dados QA."

    def handle(self, *args, **options):
        if (
            os.environ.get("JURIX_QA_ONLY") != "1"
            or os.environ.get("DJANGO_SETTINGS_MODULE") != "config.settings_normative_qa"
            or not getattr(settings, "NORMATIVE_ARCHIVE_ASSISTANT_ENABLED", False)
        ):
            raise CommandError("Este diagnóstico exige o ambiente QA normativo isolado.")

        candidates = list(
            EventoNormativoCandidato.objects.select_related("extracao")
            .select_related("extracao__documento")
            .only(
                "id",
                "action",
                "target_reference_json",
                "extracao__documento_id",
                "extracao__documento__source_kind",
                "extracao__documento__metadata_json",
            )
            .order_by("pk")
        )
        documents = list(
            DocumentoNormativo.objects.filter(
                source_kind__in=(
                    DocumentoNormativo.SourceKind.ARCHIVE,
                    DocumentoNormativo.SourceKind.SAPL,
                )
            ).only("source_kind", "metadata_json")
        )
        candidate_years = {
            int(candidate.target_reference_json["year_candidate"])
            for candidate in candidates
            if isinstance(candidate.target_reference_json, dict)
            and str(candidate.target_reference_json.get("year_candidate") or "").isdecimal()
        }
        normas = list(
            Norma.objects.filter(ano__in=candidate_years).only(
                "tipo", "numero", "ano", "identity_json"
            )
        )
        self.stdout.write(json.dumps(
            relation_target_coverage(candidates, documents, normas),
            ensure_ascii=False,
            sort_keys=True,
        ))
