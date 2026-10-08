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
from src.processing.document_segmentation import segment_document_extraction
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


def _ensure_reviewed_document(*, slug, label, number, year, text, published, reviewer, series="municipal_lo"):
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type=label, series=series, number=number, year=year
    )
    norma, _ = Norma.objects.get_or_create(
        identity_key=identity.identity_key,
        defaults={
            "tipo": label,
            "numero": number,
            "ano": year,
            "identity_json": {**identity.identity_json, "synthetic_fixture": True},
            "ementa": "Fixture temporal sintética; não representa norma real.",
            "data_publicacao": published,
            "data_norma": published,
            "data_vigencia": published,
            "texto_original": text,
        },
    )
    missing_dates = []
    identity_json = norma.identity_json if isinstance(norma.identity_json, dict) else {}
    if identity_json.get("synthetic_fixture") is not True:
        norma.identity_json = {**identity_json, "synthetic_fixture": True}
        missing_dates.append("identity_json")
    if norma.data_publicacao is None:
        norma.data_publicacao = published
        missing_dates.append("data_publicacao")
    if norma.data_norma is None:
        norma.data_norma = published
        missing_dates.append("data_norma")
    if norma.data_vigencia is None:
        norma.data_vigencia = published
        missing_dates.append("data_vigencia")
    if missing_dates:
        norma.save(update_fields=[*missing_dates, "updated_at"])
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
        extractor_version="synthetic-temporal-v2",
        policy_fingerprint=_digest("synthetic-temporal-policy-v2"),
        defaults={
            "text_version": "synthetic-temporal-text-v2",
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
    if document.accepted_extraction_id != extraction.pk:
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
    # Seed through the same offset-preserving segmenter used by the pipeline.
    # Older v1 fixtures wrote frozen devices without source offsets, so use a new
    # extraction version above instead of mutating those immutable records.
    existing_devices = extraction.dispositivos_documentais.exists()
    segmented = None if existing_devices else segment_document_extraction(extraction.pk)
    if not existing_devices and segmented and not segmented.devices and text.strip():
        # Some synthetic source fixtures are amendment clauses or short
        # unstructured excerpts rather than complete statute bodies. Preserve
        # their full text as one explicit QA-only source span so projection
        # fixtures still exercise the reviewed-base contract.
        fallback_number = "5º" if slug == "a" else "1º"
        DocumentoDispositivo.objects.create(
            extracao=extraction,
            structural_key=structural_key("root", "artigo", fallback_number),
            tipo="artigo",
            numero=fallback_number,
            ordem=1,
            texto=text,
            start_offset=0,
            end_offset=len(text),
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

    conflict_target, _target_doc, _target_extraction, conflict_target_device = _ensure_reviewed_document(
        slug="same-date-conflict-target-v3",
        label="Lei",
        number="9905",
        year=2022,
        text="Art. 1º O prazo é de trinta dias.",
        published=date(2022, 1, 10),
        reviewer=reviewer,
    )
    _conflict_source_norm, _source_doc, _source_extraction, conflict_source_device = _ensure_reviewed_document(
        slug="same-date-conflict-source-v3",
        label="Lei",
        number="9906",
        year=2023,
        text="Art. 1º [QA SINTÉTICO] Altera e revoga o Art. 1º da Lei 9905/2022. O efeito ocorre em 1º de março de 2023.",
        published=date(2023, 2, 1),
        reviewer=reviewer,
    )
    conflict_quote = "O efeito ocorre em 1º de março de 2023."
    conflict_effective_on = date(2023, 3, 1)
    conflict_event_ids = {}
    for action in ("ALTERA", "REVOGA"):
        conflicting_event, _ = EventoAlteracao.objects.get_or_create(
            dispositivo_fonte=conflict_source_device,
            acao=action,
            target_text="Art. 1º da Lei 9905/2022",
            defaults={
                "norma_alvo": conflict_target,
                "dispositivo_alvo": conflict_target_device,
                "referencia_tipo": "artigo",
                "referencia_numero": "1º",
                "target_reference_json": {"synthetic": True, "target_scope": "device", "same_date_conflict": True},
                "evidence_json": {"synthetic": True, "quote": conflict_quote},
                "revision_fingerprint": _digest(f"synthetic-same-date-conflict-{action.lower()}-v1"),
            },
        )
        if conflicting_event.review_revision_id is None:
            relation_review = RevisaoJuridica.objects.create(
                evento=conflicting_event,
                target_fingerprint=_decision_fingerprint(
                    event_review_fingerprint(conflicting_event),
                    norma_id=conflict_target.pk,
                    dispositivo_id=conflict_target_device.pk,
                ),
                decision=RevisaoJuridica.Decision.APPROVE,
                reason="[QA SINTÉTICO] Efeito conflitante confirmado artificialmente; não é gold humano.",
                actor=reviewer,
            )
            conflicting_event.validado = True
            conflicting_event.review_revision = relation_review
            conflicting_event.effective_on = conflict_effective_on
            conflicting_event.effective_date_status = "confirmed"
            date_review = RevisaoJuridica.objects.create(
                evento=conflicting_event,
                target_fingerprint=temporal_candidate_fingerprint(
                    conflicting_event, conflict_effective_on, conflict_quote
                ),
                decision=RevisaoJuridica.Decision.APPROVE,
                reason="[QA SINTÉTICO] Data do conflito confirmada artificialmente; não é gold humano.",
                actor=reviewer,
            )
            conflicting_event.effective_date_basis = {
                "kind": "synthetic_explicit_date",
                "evidence_quote": conflict_quote,
                "effective_on": conflict_effective_on.isoformat(),
                "review_id": str(date_review.public_id),
                "review_type": "effective_date",
            }
            conflicting_event.save(update_fields=[
                "validado", "review_revision", "effective_on", "effective_date_status",
                "effective_date_basis", "updated_at",
            ])
        conflict_event_ids[action.lower()] = conflicting_event.pk
    conflict_projection = project_norma_as_of(conflict_target, conflict_effective_on)
    if (
        conflict_projection.status != "partial"
        or conflict_projection.coverage["applied_event_ids"]
        or set(conflict_projection.coverage["pending_event_ids"]) != set(conflict_event_ids.values())
        or conflict_projection.devices[0].text != "Art. 1º O prazo é de trinta dias."
    ):
        raise CommandError("A fixture de efeitos conflitantes não permaneceu fail-closed.")

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
    lc198, _source_document, _source_extraction, remittance_source = _ensure_reviewed_document(
        slug="lc198-references",
        label="Lei Complementar",
        series="municipal_lc",
        number="198",
        year=2021,
        text=f"Art. 1º {remittance_text}",
        published=date(2021, 1, 10),
        reviewer=reviewer,
    )
    lc55, _target_document, _target_extraction, _target_article = _ensure_reviewed_document(
        slug="lc55-reference-target",
        label="Lei Complementar",
        series="municipal_lc",
        number="55",
        year=2004,
        text="Fixture sintética da norma citada; dispositivos 21 e 44 existem apenas para testar remissões.",
        published=date(2004, 1, 1),
        reviewer=reviewer,
    )
    target_devices = {}
    for article in ("21", "44"):
        article_number = f"{article}º"
        target_device, _ = Dispositivo.objects.get_or_create(
            norma=lc55,
            structural_key=structural_key("root", "artigo", article_number),
            defaults={
                "tipo": "artigo",
                "numero": article_number,
                "texto": f"Art. {article_number} (QA sintético) — dispositivo usado apenas para validar agrupamento de remissões.",
                "texto_bruto": f"Art. {article_number} (QA sintético) — dispositivo usado apenas para validar agrupamento de remissões.",
                "ordem": int(article),
                "revision_fingerprint": revision_fingerprint(article_number, article_number),
            },
        )
        target_devices[article] = target_device
    remittance_key = structural_key("root", "artigo", "1º")
    assert remittance_source.norma_id == lc198.pk
    assert remittance_source.structural_key == remittance_key
    for article in ("21", "44"):
        ref_event, _ = EventoAlteracao.objects.get_or_create(
            dispositivo_fonte=remittance_source,
            acao="REFERENCIA",
            target_text=f"[QA R04] Art. {article} da Lei Complementar 55/2004",
            defaults={
                "norma_alvo": lc55,
                "dispositivo_alvo": target_devices[article],
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
                    relation_fingerprint,
                    norma_id=lc55.pk,
                    dispositivo_id=target_devices[article].pk,
                ),
                decision=RevisaoJuridica.Decision.APPROVE,
                reason="[QA SINTÉTICO] Remissão confirmada artificialmente para teste, não gold humano.",
                actor=reviewer,
            )
            ref_event.validado = True
            ref_event.review_revision = ref_review
            ref_event.save(update_fields=["validado", "review_revision", "updated_at"])
    partial_projection_event, _ = EventoAlteracao.objects.get_or_create(
        dispositivo_fonte=remittance_source,
        acao="REVOGA",
        target_text="[QA R10] evento pendente para projeção parcial do Art. 21º",
        defaults={
            "norma_alvo": lc55,
            "dispositivo_alvo": target_devices["21"],
            "referencia_tipo": "artigo",
            "referencia_numero": "21º",
            "target_reference_json": {"synthetic": True, "target_scope": "device", "review_state": "pending"},
            "evidence_json": {"synthetic": True, "quote": "Evento não revisado, criado só para validar a cobertura parcial."},
            "revision_fingerprint": _digest("synthetic-r10-pending-partial-projection-v1"),
            "validado": False,
        },
    )
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
        "same_date_conflict": {
            "norma_id": conflict_target.pk,
            "source_norma_id": _conflict_source_norm.pk,
            "as_of": conflict_effective_on.isoformat(),
            "from_as_of": "2023-02-28",
            "expected_projection": "partial",
            "expected_text": "Art. 1º O prazo é de trinta dias.",
            "event_ids": conflict_event_ids,
            "synthetic_only": True,
        },
        "lc55_2004": {"norma_id": lc55.pk, "identity_key": lc55.identity_key},
        "partial_projection": {
            "norma_id": lc55.pk,
            "as_of": "2022-01-01",
            "expected_projection": "partial",
            "pending_event_id": partial_projection_event.pk,
        },
        "lo55_2004": {"norma_id": lo55.pk, "identity_key": lo55.identity_key},
        "lc198_2021": {
            "norma_id": lc198.pk,
            "identity_key": lc198.identity_key,
            "reference_event_ids": list(
                EventoAlteracao.objects.filter(
                    dispositivo_fonte__norma=lc198,
                    acao="REFERENCIA",
                    target_text__startswith="[QA R04]",
                )
                .order_by("referencia_numero")
                .values_list("pk", flat=True)
            ),
        },
        "external_federal_4320_1964": external,
        "date_boundaries": {key: value.isoformat() for key, value in dates.items()},
        "snapshots": snapshot_map,
        "synthetic_only": True,
    }


def _ensure_device(norma, *, tipo, numero, text, order, parent=None):
    parent_key = parent.structural_key if parent else "root"
    key = structural_key(parent_key, tipo, numero)
    device, _ = Dispositivo.objects.get_or_create(
        norma=norma,
        structural_key=key,
        defaults={
            "tipo": tipo,
            "numero": numero,
            "texto": text,
            "texto_bruto": text,
            "ordem": order,
            "dispositivo_pai": parent,
            "revision_fingerprint": revision_fingerprint(text, text),
        },
    )
    return device


def _ensure_pending_event(*, source, action, target_text, target=None, target_device=None,
                          reference_type="", reference_number="", evidence, candidate=None):
    event, _ = EventoAlteracao.objects.get_or_create(
        dispositivo_fonte=source,
        acao=action,
        target_text=target_text,
        defaults={
            "norma_alvo": target,
            "dispositivo_alvo": target_device,
            "referencia_tipo": reference_type,
            "referencia_numero": reference_number,
            "target_reference_json": {"synthetic": True, **(candidate or {})},
            "evidence_json": {"synthetic": True, **evidence},
            "revision_fingerprint": _digest(f"synthetic-edge:{source.pk}:{action}:{target_text}"),
            "validado": False,
        },
    )
    return event


def _ensure_edge_case_fixtures():
    """Persist navigable negative and hard cases without treating them as legal gold."""
    source_norm, source_doc, _, source_article = _ensure_reviewed_document(
        slug="edge-source", label="Lei", number="9910", year=2090,
        text="Art. 1º (QA sintético) contém eventos de alteração apenas para teste.",
        published=date(2090, 1, 1), reviewer=_qa_reviewer(),
    )
    partial_norm, partial_doc, _, partial_article = _ensure_reviewed_document(
        slug="edge-partial-target", label="Lei", number="9911", year=2090,
        text="Art. 2º (QA sintético) contém incisos fictícios.",
        published=date(2090, 1, 2), reviewer=_qa_reviewer(),
    )
    partial_inciso = _ensure_device(
        partial_norm, tipo="inciso", numero="II",
        text="II — conteúdo fictício sujeito a evento pendente de QA.", order=2,
        parent=partial_article,
    )
    total_norm, total_doc, _, _ = _ensure_reviewed_document(
        slug="edge-total-target", label="Lei", number="9912", year=2090,
        text="Art. 1º (QA sintético) norma-alvo fictícia.",
        published=date(2090, 1, 3), reviewer=_qa_reviewer(),
    )
    added_norm, added_doc, _, article_five = _ensure_reviewed_document(
        slug="edge-add-target", label="Lei", number="9913", year=2090,
        text="Art. 5º (QA sintético) artigo anterior fictício.",
        published=date(2090, 1, 4), reviewer=_qa_reviewer(),
    )
    added_device = _ensure_device(
        added_norm, tipo="artigo", numero="5º-A",
        text="Art. 5º-A (QA sintético) dispositivo adicionado para teste.", order=6,
    )
    _review_source_norm, _, _, review_source_article = _ensure_reviewed_document(
        slug="admin-review-source",
        label="Lei",
        number="9916",
        year=2090,
        text="Art. 1º (QA sintético) Altera-se o Art. 2º da Lei 9911/2090 somente para teste de revisão administrativa.",
        published=date(2090, 1, 5),
        reviewer=_qa_reviewer(),
    )
    work_item_norm, work_item_doc, work_item_extraction, _ = _ensure_reviewed_document(
        slug="work-item-review-pipeline",
        label="Lei",
        number="9917",
        year=2090,
        text="Art. 1º (QA sintético) fixture exclusiva para validar checkpoints operacionais.",
        published=date(2090, 1, 6),
        reviewer=_qa_reviewer(),
    )
    worker_runtime_norm, worker_runtime_doc, worker_runtime_extraction, _ = _ensure_reviewed_document(
        slug="worker-runtime-checkpoint",
        label="Lei",
        number="9918",
        year=2090,
        text="Art. 1º (QA sintético) norma exclusiva para validar execução Celery real.",
        published=date(2090, 1, 7),
        reviewer=_qa_reviewer(),
    )

    event_specs = {
        "partial_revocation": _ensure_pending_event(
            source=source_article, action="REVOGA", target_text="Inciso II do Art. 2º da Lei 9911/2090",
            target=partial_norm, target_device=partial_inciso, reference_type="inciso",
            reference_number="II", evidence={"quote": "Revoga-se, em cenário sintético, o inciso II."},
            candidate={"scope": "device", "review_state": "pending"},
        ),
        "total_revocation": _ensure_pending_event(
            source=source_article, action="REVOGA", target_text="Lei 9912/2090 integralmente",
            target=total_norm, reference_type="lei", reference_number="9912/2090",
            evidence={"quote": "Revoga-se, em cenário sintético, a Lei 9912/2090."},
            candidate={"scope": "norma", "review_state": "pending"},
        ),
        "add_article_5_a": _ensure_pending_event(
            source=source_article, action="ADICIONA", target_text="Art. 5º-A da Lei 9913/2090",
            target=added_norm, target_device=added_device, reference_type="artigo",
            reference_number="5º-A", evidence={"quote": "Fica acrescido, em cenário sintético, o Art. 5º-A."},
            candidate={"scope": "device", "preserves_article_5": article_five.numero == "5º", "review_state": "pending"},
        ),
        "generic_revocation": _ensure_pending_event(
            source=source_article, action="REVOGA", target_text="demais disposições em contrário",
            evidence={"quote": "Revogam-se as disposições em contrário."},
            candidate={"scope": "unresolved", "review_state": "pending"},
        ),
        "external_federal": _ensure_pending_event(
            source=source_article, action="REFERENCIA", target_text="Lei Federal 4320/1964",
            reference_type="lei federal", reference_number="4320/1964",
            evidence={"quote": "Referência sintética à Lei Federal 4320/1964."},
            candidate={"scope": "external", "external_identity_key": "BR:federal:lei:4320:1964",
                       "municipal_fk_created": False, "review_state": "pending"},
        ),
        "veto": _ensure_pending_event(
            source=source_article, action="SUBSTITUI", target_text="Art. 9º — texto vetado no fixture QA",
            evidence={"quote": "Art. 9º (VETADO) — marcação sintética."},
            candidate={"scope": "veto", "does_not_infer_current_text": True, "review_state": "pending"},
        ),
        "admin_review_smoke": _ensure_pending_event(
            source=review_source_article,
            action="ALTERA",
            target_text="Art. 2º da Lei 9911/2090 (QA smoke v2)",
            target=partial_norm,
            reference_type="artigo",
            reference_number="2º",
            evidence={"quote": "Altera-se o Art. 2º da Lei 9911/2090 somente para teste de revisão administrativa."},
            candidate={"scope": "device", "review_state": "pending", "admin_smoke": True},
        ),
    }
    admin_review_event = event_specs["admin_review_smoke"]
    if admin_review_event.review_revision_id is None and admin_review_event.dispositivo_alvo_id:
        # This dedicated browser fixture reviews the norm-level candidate. Its
        # extracted reference is Art. 2º, while the source fixture has a
        # differently numbered placeholder device; don't seed a false device link.
        admin_review_event.dispositivo_alvo = None
        admin_review_event.save(update_fields=["dispositivo_alvo", "updated_at"])
    # Two separate actions remain two candidates, even when extracted from one passage.
    multi_quote = "Altera-se o Art. 1º e revoga-se o Art. 2º (texto sintético de teste)."
    event_specs["multi_action_alter"] = _ensure_pending_event(
        source=source_article, action="ALTERA", target_text="Art. 1º — ação 1 do trecho múltiplo",
        target=source_norm, target_device=source_article, reference_type="artigo", reference_number="1º",
        evidence={"quote": multi_quote, "span_start": 0, "span_end": 24},
        candidate={"multi_action_group": "synthetic-multi-action-v1", "review_state": "pending"},
    )
    event_specs["multi_action_revoke"] = _ensure_pending_event(
        source=source_article, action="REVOGA", target_text="Art. 2º — ação 2 do trecho múltiplo",
        target=partial_norm, target_device=partial_article, reference_type="artigo", reference_number="2º",
        evidence={"quote": multi_quote, "span_start": 25, "span_end": len(multi_quote)},
        candidate={"multi_action_group": "synthetic-multi-action-v1", "review_state": "pending"},
    )

    document_ids = {"edge_source": str(source_doc.public_id), "partial_target": str(partial_doc.public_id),
                    "total_target": str(total_doc.public_id), "add_target": str(added_doc.public_id)}
    version_ids = {}
    for role, suffix in ((DocumentoNormativo.Role.REPUBLICATION, "republication"),
                         (DocumentoNormativo.Role.RECTIFICATION, "rectification")):
        source_ref = f"jurix-synthetic-qa:edge-version:{suffix}:v1"
        version, _ = DocumentoNormativo.objects.get_or_create(
            document_key=_digest(source_ref),
            defaults={
                "norma": added_norm, "source_kind": DocumentoNormativo.SourceKind.LEGACY,
                "source_ref": source_ref, "original_filename": f"[SINTÉTICO QA] {suffix}.pdf",
                "role": role, "content_sha256": _digest(f"bytes:{source_ref}"), "size_bytes": 0,
                "metadata_json": {"synthetic": True, "not_human_reviewed": True},
                "condition_of_use": DocumentoNormativo.ConditionOfUse.UNKNOWN,
                "review_status": DocumentoNormativo.ReviewStatus.PENDING,
                "extraction_status": DocumentoNormativo.ExtractionStatus.NEEDS_REVIEW,
            },
        )
        version_ids[suffix] = str(version.public_id)

    missing_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei", series="municipal_lo", number="9914", year=2090
    )
    missing_original, _ = Norma.objects.get_or_create(
        identity_key=missing_identity.identity_key,
        defaults={"tipo": "Lei", "numero": "9914", "ano": 2090,
                  "identity_json": missing_identity.identity_json,
                  "ementa": "[QA SINTÉTICO] Original ausente; não projetar histórico completo."},
    )
    future_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei", series="municipal_lo", number="9915", year=2095
    )
    future_norm, _ = Norma.objects.get_or_create(
        identity_key=future_identity.identity_key,
        defaults={"tipo": "Lei", "numero": "9915", "ano": 2095,
                  "identity_json": future_identity.identity_json,
                  "ementa": "[QA SINTÉTICO] Publicação futura; não afirmar vigência atual.",
                  "data_publicacao": date(2095, 1, 1), "data_vigencia": date(2095, 1, 1)},
    )
    return {
        "synthetic_only": True,
        "documents": document_ids,
        "norma_ids": {
            "edge_source": source_norm.pk,
            "partial_target": partial_norm.pk,
            "total_target": total_norm.pk,
            "add_target": added_norm.pk,
            "admin_review_source": review_source_article.norma_id,
        "work_item_review": {
            "norma_id": work_item_norm.pk,
            "document_id": str(work_item_doc.public_id),
            "extraction_id": work_item_extraction.pk,
            "synthetic_only": True,
            "not_legal_gold": True,
        },
        "worker_runtime": {
            "norma_id": worker_runtime_norm.pk,
            "document_id": str(worker_runtime_doc.public_id),
            "extraction_id": worker_runtime_extraction.pk,
            "synthetic_only": True,
            "not_legal_gold": True,
        },
            "missing_original": missing_original.pk,
            "future_norm": future_norm.pk,
        },
        "events": {key: event.pk for key, event in event_specs.items()},
        "versions": version_ids,
        "missing_original": {"norma_id": missing_original.pk, "documento_base_id": None,
                             "expected_projection": "not_reconstructable"},
        "future_norm": {"norma_id": future_norm.pk, "publication_on": "2095-01-01",
                         "documento_base_id": None, "expected_as_of_2026": "not_yet_published"},
        "all_events_pending": all(not event.validado and event.review_revision_id is None
                                   for event in event_specs.values()),
        "no_real_corpus_mutation": True,
    }


def _qa_reviewer():
    """Return/create the isolated fixture reviewer for helper calls during seeding."""
    User = get_user_model()
    reviewer, created = User.objects.get_or_create(
        username="jurix-qa-reviewer",
        defaults={"email": "", "is_staff": True, "is_superuser": True, "is_active": True},
    )
    password = os.environ.get("JURIX_QA_REVIEWER_PASSWORD")
    if password:
        if os.environ.get("JURIX_QA_ONLY") != "1":
            raise CommandError("credencial de revisor só pode ser ativada em QA isolado")
        if len(password) < 24:
            raise CommandError("credencial temporária do revisor deve ter ao menos 24 caracteres")
        if not reviewer.check_password(password):
            reviewer.set_password(password)
            reviewer.save(update_fields=["password"])
    elif created or reviewer.has_usable_password():
        reviewer.set_unusable_password()
        reviewer.save(update_fields=["password"])
    return reviewer


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

    collection_identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL", raw_type="Lei", series="municipal_lo",
        number="9917", year=2090,
    )
    collection_norma, _ = Norma.objects.get_or_create(
        identity_key=collection_identity.identity_key,
        defaults={
            "tipo": "Lei",
            "numero": "9917",
            "ano": 2090,
            "identity_json": collection_identity.identity_json,
            "ementa": "[QA SINTÉTICO — NÃO É LEGISLAÇÃO REAL] Norma para teste de coleções.",
            "texto_consolidado": "Art. 1º Para fins exclusivos de teste, este texto não representa legislação vigente.",
            "status": Norma.Status.CONSOLIDATED,
        },
    )
    if collection_norma.status != Norma.Status.CONSOLIDATED:
        collection_norma.status = Norma.Status.CONSOLIDATED
        collection_norma.save(update_fields=["status", "updated_at"])
    # Keep this collection-only record addressable by its QA scenarios, but
    # prevent it from looking like part of the municipal legal catalogue.
    collection_identity_json = dict(collection_norma.identity_json or {})
    collection_identity_json["synthetic_fixture"] = True
    if collection_norma.identity_json != collection_identity_json:
        collection_norma.identity_json = collection_identity_json
        collection_norma.save(update_fields=["identity_json", "updated_at"])
    _ensure_device(
        collection_norma,
        tipo="artigo",
        numero="1º",
        text="Para fins exclusivos de teste, este texto não representa legislação vigente.",
        order=1,
    )

    reviewer = _qa_reviewer()
    temporal = _ensure_temporal_fixture(reviewer)
    edge_fixtures = _ensure_edge_case_fixtures()
    payload = {
        "schema_version": 1,
        "dataset": "synthetic_not_gold",
        "scenarios": results,
        "reviewer_username": reviewer.username,
        "credentials_included": False,
        "collection_fixture": {
            "norma_id": collection_norma.pk,
            "synthetic_only": True,
            "not_legal_gold": True,
        },
        "temporal_scenarios": temporal,
        "edge_case_fixtures": edge_fixtures,
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
