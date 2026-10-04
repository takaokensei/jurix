"""Create an isolated, deterministic synthetic fixture for product QA."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import date
from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from src.apps.ingestion.document_promotion import promotion_fingerprint
from src.apps.legislation.document_models import (
    DocumentoDispositivo,
    DocumentoNormativo,
    ExtracaoDocumento,
    NormativeSnapshot,
)
from src.apps.legislation.event_review import _decision_fingerprint, event_review_fingerprint
from src.apps.legislation.models import Dispositivo, EventoAlteracao, Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.device_revision import revision_fingerprint, structural_key
from src.processing.document_metadata import build_normative_identity
from src.processing.event_temporal_policy import temporal_candidate_fingerprint
from src.processing.normative_projection import persist_projection, project_norma_as_of

NORMATIVE_EDGE_CASES = (
    ("lc_reference", "Lei Complementar remete para outra Lei Complementar"),
    ("homonymous_ordinary_law", "Lei ordinária homônima não colide com a complementar"),
    ("dated_amendment", "ALTERA com publicação e efeito em datas distintas"),
    ("partial_revocation", "REVOGA apenas um inciso"),
    ("total_revocation", "REVOGA total"),
    ("add_article_5_a", "ADICIONA Art. 5º-A sem reordenar a chave estrutural"),
    ("generic_revocation", "cláusula genérica sem alvo explícito"),
    ("external_federal", "referência à Lei Federal não resolve como municipal"),
    ("veto", "dispositivo vetado sem texto vigente inferido"),
    ("multi_action", "um trecho contém ações jurídicas distintas"),
    ("republication_rectification", "republicação ou retificação com proveniência própria"),
    ("missing_original", "redação original ausente impede projeção histórica"),
    ("future_norm", "publicação futura em relação a as_of deve ser recusada"),
    ("conflicting_candidate", "conflito de identidade ou data permanece pendente"),
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _ensure_reviewed_document(*, slug, label, number, year, text, published, reviewer):
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type=label, series="municipal_lo", number=number, year=year
    )
    norma, _ = Norma.objects.get_or_create(
        identity_key=identity.identity_key,
        defaults={
            "tipo": label,
            "numero": number,
            "ano": year,
            "identity_json": identity.identity_json,
            "ementa": "Fixture temporal sintética; não representa norma real.",
            "data_publicacao": published,
            "data_norma": published,
            "data_vigencia": published,
            "texto_original": text,
        },
    )
    source_ref = f"jurix-synthetic-qa:temporal:{slug}:v1"
    document, _ = DocumentoNormativo.objects.get_or_create(
        document_key=_digest(source_ref),
        defaults={
            "norma": norma,
            "source_kind": DocumentoNormativo.SourceKind.LEGACY,
            "source_ref": source_ref,
            "original_filename": f"[SINTÉTICO QA] {label} {number}/{year}.pdf",
            "role": DocumentoNormativo.Role.ORIGINAL,
            "content_sha256": _digest(f"bytes:{source_ref}"),
            "size_bytes": 0,
            "metadata_json": {"synthetic": True, "identity_key": identity.identity_key},
            "condition_of_use": DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            "review_status": DocumentoNormativo.ReviewStatus.APPROVED,
            "extraction_status": DocumentoNormativo.ExtractionStatus.EXTRACTED,
        },
    )
    extraction, _ = ExtracaoDocumento.objects.get_or_create(
        documento=document,
        extractor_version="synthetic-temporal-v1",
        policy_fingerprint=_digest("synthetic-temporal-policy-v1"),
        defaults={
            "text_version": "synthetic-temporal-text-v1",
            "raw_text": text,
            "legal_text": text,
            "raw_text_sha256": _digest(text),
            "legal_text_sha256": _digest(text),
            "page_count": 1,
            "quality_json": {"synthetic": True, "not_human_reviewed": True},
            "metadata_candidates_json": {"synthetic": True},
            "status": ExtracaoDocumento.Status.COMPLETE,
            "extraction_sha256": _digest(f"extraction:{source_ref}"),
        },
    )
    if document.accepted_extraction_id is None:
        document.accepted_extraction = extraction
        document.save(update_fields=["accepted_extraction", "updated_at"])
    if not RevisaoJuridica.objects.filter(
        documento=document,
        decision=RevisaoJuridica.Decision.APPROVE,
        target_fingerprint=promotion_fingerprint(document),
    ).exists():
        RevisaoJuridica.objects.create(
            documento=document,
            target_fingerprint=promotion_fingerprint(document),
            decision=RevisaoJuridica.Decision.APPROVE,
            reason="[QA SINTÉTICO] Estado aprovado artificialmente apenas para testar projeção.",
            actor=reviewer,
        )
    if norma.documento_base_id is None:
        norma.documento_base = document
        norma.save(update_fields=["documento_base", "updated_at"])
    if not extraction.dispositivos_documentais.exists():
        device_key = structural_key("root", "artigo", "5º" if slug == "a" else "1º")
        DocumentoDispositivo.objects.create(
            extracao=extraction,
            structural_key=device_key,
            tipo="artigo",
            numero="5º" if slug == "a" else "1º",
            ordem=1,
            texto=text,
        )
    legacy, _ = Dispositivo.objects.get_or_create(
        norma=norma,
        structural_key=structural_key("root", "artigo", "5º" if slug == "a" else "1º"),
        defaults={
            "tipo": "artigo",
            "numero": "5º" if slug == "a" else "1º",
            "texto": text,
            "texto_bruto": text,
            "ordem": 1,
            "revision_fingerprint": revision_fingerprint(text, text),
        },
    )
    return norma, document, extraction, legacy


def _ensure_temporal_fixture(reviewer):
    norma_a, doc_a, extraction_a, article_a = _ensure_reviewed_document(
        slug="a",
        label="Lei",
        number="9001",
        year=2020,
        text="Art. 5º O prazo é de dez dias.",
        published=date(2020, 1, 10),
        reviewer=reviewer,
    )
    amendment_text = (
        'Dê-se nova redação ao Art. 5º da Lei 9001/2020: '
        '“Art. 5º O prazo é de vinte dias.” O efeito ocorre em 1º de março de 2021.'
    )
    norma_b, doc_b, extraction_b, source_device = _ensure_reviewed_document(
        slug="b",
        label="Lei",
        number="9002",
        year=2021,
        text=amendment_text,
        published=date(2021, 1, 10),
        reviewer=reviewer,
    )
    relation, _ = EventoAlteracao.objects.get_or_create(
        dispositivo_fonte=source_device,
        acao="ALTERA",
        target_text="Art. 5º da Lei 9001/2020",
        defaults={
            "norma_alvo": norma_a,
            "dispositivo_alvo": article_a,
            "referencia_tipo": "artigo",
            "referencia_numero": "5º",
            "target_reference_json": {"kind": "synthetic_exact_reference", "synthetic": True},
            "evidence_json": {"synthetic": True, "quote": "Art. 5º da Lei 9001/2020"},
            "revision_fingerprint": _digest("synthetic-event-a-b-v1"),
        },
    )
    if relation.review_revision_id is None:
        relation_fingerprint = event_review_fingerprint(relation)
        review = RevisaoJuridica.objects.create(
            evento=relation,
            target_fingerprint=_decision_fingerprint(
                relation_fingerprint, norma_id=norma_a.pk, dispositivo_id=article_a.pk
            ),
            decision=RevisaoJuridica.Decision.APPROVE,
            reason="[QA SINTÉTICO] Relação aprovada artificialmente para teste, não é adjudicação humana.",
            actor=reviewer,
        )
        relation.validado = True
        relation.review_revision = review
        relation.save(update_fields=["validado", "review_revision", "updated_at"])
    date_quote = "O efeito ocorre em 1º de março de 2021."
    effective = date(2021, 3, 1)
    if relation.effective_date_status != "confirmed":
        date_fingerprint = temporal_candidate_fingerprint(relation, effective, date_quote)
        date_review = RevisaoJuridica.objects.create(
            evento=relation,
            target_fingerprint=date_fingerprint,
            decision=RevisaoJuridica.Decision.APPROVE,
            reason="[QA SINTÉTICO] Data confirmada artificialmente para teste temporal.",
            actor=reviewer,
        )
        relation.effective_on = effective
        relation.effective_date_status = "confirmed"
        relation.effective_date_basis = {
            "kind": "synthetic_explicit_date",
            "evidence_quote": date_quote,
            "effective_on": effective.isoformat(),
            "review_id": str(date_review.public_id),
            "review_type": "effective_date",
        }
        relation.save(update_fields=["effective_on", "effective_date_status", "effective_date_basis", "updated_at"])

    # Separate municipal LC/LO number collision and an external federal identity.
    lc_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei Complementar", series="municipal_lc", number="55", year=2004
    )
    lc55, _ = Norma.objects.get_or_create(
        identity_key=lc_identity.identity_key,
        defaults={"tipo": "Lei Complementar", "numero": "55", "ano": 2004, "identity_json": lc_identity.identity_json, "ementa": "Fixture de remissão sintética."},
    )
    lo_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei", series="municipal_lo", number="55", year=2004
    )
    lo55, _ = Norma.objects.get_or_create(
        identity_key=lo_identity.identity_key,
        defaults={"tipo": "Lei", "numero": "55", "ano": 2004, "identity_json": lo_identity.identity_json, "ementa": "Fixture de colisão tipada sintética."},
    )
    lc198_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei Complementar", series="municipal_lc", number="198", year=2021
    )
    lc198, _ = Norma.objects.get_or_create(
        identity_key=lc198_identity.identity_key,
        defaults={"tipo": "Lei Complementar", "numero": "198", "ano": 2021, "identity_json": lc198_identity.identity_json, "ementa": "Fixture sintética de relações normativas."},
    )
    remittance_text = "Esta Lei faz referência aos arts. 21 e 44 da Lei Complementar 55/2004."
    remittance_key = structural_key("root", "artigo", "1º")
    remittance_source, _ = Dispositivo.objects.get_or_create(
        norma=lc198,
        structural_key=remittance_key,
        defaults={
            "tipo": "artigo", "numero": "1º", "texto": remittance_text,
            "texto_bruto": remittance_text, "ordem": 1,
            "revision_fingerprint": revision_fingerprint(remittance_text, remittance_text),
        },
    )
    for article in ("21", "44"):
        ref_event, _ = EventoAlteracao.objects.get_or_create(
            dispositivo_fonte=remittance_source,
            acao="REFERENCIA",
            target_text=f"Art. {article} da Lei Complementar 55/2004",
            defaults={
                "norma_alvo": lc55,
                "referencia_tipo": "artigo",
                "referencia_numero": article,
                "target_reference_json": {"synthetic": True, "target_scope": "device"},
                "evidence_json": {"synthetic": True, "quote": remittance_text},
                "revision_fingerprint": _digest(f"synthetic-reference-{article}"),
            },
        )
        if ref_event.review_revision_id is None:
            relation_fingerprint = event_review_fingerprint(ref_event)
            ref_review = RevisaoJuridica.objects.create(
                evento=ref_event,
                target_fingerprint=_decision_fingerprint(
                    relation_fingerprint, norma_id=lc55.pk, dispositivo_id=None
                ),
                decision=RevisaoJuridica.Decision.APPROVE,
                reason="[QA SINTÉTICO] Remissão confirmada artificialmente para teste, não gold humano.",
                actor=reviewer,
            )
            ref_event.validado = True
            ref_event.review_revision = ref_review
            ref_event.save(update_fields=["validado", "review_revision", "updated_at"])
    external = {"jurisdiction": "BR", "type": "Lei", "number": "4320", "year": 1964, "synthetic": True}
    # Snapshots are append-only and limited to the three required boundary dates.
    dates = {
        "d_minus_1": date(2021, 2, 28),
        "d": date(2021, 3, 1),
        "d_plus_1": date(2021, 3, 2),
    }
    snapshot_map = {}
    for label, as_of in dates.items():
        snapshot_map[label] = {}
        for norm in (norma_a,):
            projection = project_norma_as_of(norm, as_of)
            record = persist_projection(projection)
            snapshot_map[label] = {
                "snapshot_id": record.pk,
                "status": projection.status,
                "input_sha256": projection.input_sha256,
                "content_sha256": projection.content_sha256,
                "article_5_text": next((row.text for row in projection.devices if row.source.numero == "5º"), None),
            }
    return {
        "norma_a": {"norma_id": norma_a.pk, "identity_key": norma_a.identity_key, "document_id": str(doc_a.public_id), "extraction_id": extraction_a.pk, "publication_on": "2020-01-10"},
        "norma_b": {"norma_id": norma_b.pk, "identity_key": norma_b.identity_key, "document_id": str(doc_b.public_id), "extraction_id": extraction_b.pk, "publication_on": "2021-01-10", "effective_on": "2021-03-01", "event_id": relation.pk},
        "lc55_2004": {"norma_id": lc55.pk, "identity_key": lc55.identity_key},
        "lo55_2004": {"norma_id": lo55.pk, "identity_key": lo55.identity_key},
        "lc198_2021": {
            "norma_id": lc198.pk,
            "identity_key": lc198.identity_key,
            "reference_event_ids": list(
                EventoAlteracao.objects.filter(dispositivo_fonte__norma=lc198, acao="REFERENCIA")
                .order_by("referencia_numero")
                .values_list("pk", flat=True)
            ),
        },
        "external_federal_4320_1964": external,
        "date_boundaries": {key: value.isoformat() for key, value in dates.items()},
        "snapshots": snapshot_map,
        "synthetic_only": True,
    }


@transaction.atomic
def seed_fixture(output: Path) -> dict:
    if os.environ.get("JURIX_QA_ONLY") != "1":
        raise CommandError("seed sintético só pode rodar com JURIX_QA_ONLY=1")
    root = Path(os.environ.get("JURIX_QA_ROOT", "")).resolve()
    output = output.resolve()
    if not root.is_dir() or not output.is_relative_to(root) or output == root:
        raise CommandError("mapfile deve ficar dentro da raiz QA isolada")
    if output.exists():
        raise CommandError("recusando sobrescrever mapfile existente")

    scenarios = [
        ("lei", "Lei", "municipal_lo", "9901", 2090, False),
        ("lei-complementar", "Lei Complementar", "municipal_lc", "9901", 2090, False),
        ("conflito", "Lei", "municipal_lo", "9902", 2090, True),
    ]
    results = {}
    for slug, label, series, number, year, conflict in scenarios:
        identity = build_normative_identity(
            jurisdiction="BR-RN-NATAL", raw_type=label, series=series, number=number, year=year
        )
        norma = None
        if not conflict:
            norma, _ = Norma.objects.get_or_create(
                identity_key=identity.identity_key,
                defaults={
                    "tipo": label, "numero": number, "ano": year,
                    "identity_json": identity.identity_json,
                    "ementa": "Fixture sintética isolada para testes de produto.",
                },
            )
        source = f"jurix-synthetic-qa:{slug}:v1"
        key = _digest(source)
        text = f"Conteúdo sintético de teste {slug}. Art. 1º. Texto fictício, não é legislação vigente."
        document, _ = DocumentoNormativo.objects.get_or_create(
            document_key=key,
            defaults={
                "norma": None,
                "source_kind": DocumentoNormativo.SourceKind.LEGACY,
                "source_ref": source,
                "original_filename": f"[SINTÉTICO] {label} {number}/{year}.pdf",
                "role": DocumentoNormativo.Role.ORIGINAL,
                "content_sha256": _digest(f"pdf-bytes:{slug}"),
                "size_bytes": 0,
                "metadata_json": {
                    "synthetic": True,
                    "identity_key": identity.identity_key if not conflict else None,
                    "identity_candidate": identity.identity_json,
                    "candidate_status": "conflict" if conflict else "synthetic_candidate",
                },
                "conflicts_json": [{"field": "ano", "candidate_values": [2090, 2091]}] if conflict else [],
                "review_status": DocumentoNormativo.ReviewStatus.PENDING,
                "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
                "extraction_status": DocumentoNormativo.ExtractionStatus.NEEDS_REVIEW,
            },
        )
        extraction, _ = ExtracaoDocumento.objects.get_or_create(
            documento=document,
            extractor_version="synthetic-fixture-v1",
            policy_fingerprint=_digest("jurix-synthetic-policy-v1"),
            defaults={
                "text_version": "synthetic_text_v1", "raw_text": text, "legal_text": text,
                "raw_text_sha256": _digest(text), "legal_text_sha256": _digest(text),
                "page_count": 1, "page_map_json": [],
                "metadata_candidates_json": {"synthetic": True},
                "quality_json": {"synthetic": True, "not_human_reviewed": True},
                "status": ExtracaoDocumento.Status.COMPLETE,
                "extraction_sha256": _digest(f"extraction:{slug}"),
            },
        )
        if document.accepted_extraction_id is None:
            document.accepted_extraction = extraction
            document.save(update_fields=["accepted_extraction", "updated_at"])
        results[slug] = {
            "document_id": str(document.public_id),
            "document_key": document.document_key,
            "norma_id": norma.pk if norma else None,
            "identity_key": identity.identity_key if not conflict else None,
            "conflict": conflict,
        }

    User = get_user_model()
    reviewer, created = User.objects.get_or_create(
        username="jurix-qa-reviewer",
        defaults={"email": "", "is_staff": True, "is_superuser": True, "is_active": True},
    )
    if created:
        password = os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
        reviewer.set_password(password) if password else reviewer.set_unusable_password()
        reviewer.save(update_fields=["password"])
    temporal = _ensure_temporal_fixture(reviewer)
    payload = {
        "schema_version": 1,
        "dataset": "synthetic_not_gold",
        "scenarios": results,
        "reviewer_username": reviewer.username,
        "credentials_included": False,
        "temporal_scenarios": temporal,
        "normative_edge_cases": [
            {"case_id": case_id, "description": description, "synthetic_only": True,
             "human_review_required": True}
            for case_id, description in NORMATIVE_EDGE_CASES
        ],
        "snapshot_count": NormativeSnapshot.objects.filter(
            norma_id=temporal["norma_a"]["norma_id"]
        ).count(),
    }
    with output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(payload, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write("\n")
    return payload


class Command(BaseCommand):
    help = "Cria fixtures sintéticas sem credenciais e sem alterar evidência jurídica real."

    def add_arguments(self, parser):
        parser.add_argument("--output", required=True, type=Path)

    def handle(self, *args, **options):
        try:
            payload = seed_fixture(options["output"])
        except (OSError, ValueError) as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(json.dumps(payload, ensure_ascii=False, sort_keys=True))
