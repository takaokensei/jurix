from __future__ import annotations

import hashlib
import re

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.exceptions import ValidationError
from django.test import Client, override_settings
from django.urls import reverse

from src.apps.ingestion.document_promotion import promote_document, promotion_fingerprint
from src.apps.ingestion.document_review import (
    accept_document_extraction,
    extraction_review_fingerprint,
    has_reviewed_document_segmentation,
    review_document_segmentation,
    segmentation_review_fingerprint,
)
from src.apps.ingestion.norma_registry import register_reviewed_identity
from src.apps.legislation.document_models import DocumentoNormativo, ExtracaoDocumento
from src.apps.legislation.models import Norma
from src.apps.legislation.review_models import RevisaoJuridica
from src.processing.document_metadata import build_normative_identity
from src.processing.document_segmentation import segment_document_extraction


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _create_extraction(
    document,
    *,
    status=ExtracaoDocumento.Status.COMPLETE,
    metadata_candidates_json=None,
    quality_json=None,
    page_count=2,
):
    legal_text = "Art. 1º O texto público da norma foi conferido.\nArt. 2º Esta Lei entra em vigor."
    return ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="review-workspace-test-v1",
        policy_fingerprint=_sha("review-workspace-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=page_count,
        metadata_candidates_json=metadata_candidates_json or {},
        quality_json=quality_json or {},
        status=status,
        extraction_sha256="",
    )


def _review_identity(document, identity, reviewer):
    return register_reviewed_identity(
        document_id=str(document.public_id),
        reviewer=reviewer,
        reason="Epígrafe cotejada com PDF público.",
        fingerprint=promotion_fingerprint(document),
        confirmed_identity_key=identity.identity_key,
        confirmed_condition_of_use=DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
    )


@pytest.fixture
def review_candidate(db):
    identity = build_normative_identity(
        jurisdiction="BR-RN-NATAL",
        raw_type="Lei Complementar",
        series="municipal_lc",
        number="742",
        year=2026,
    )
    document = DocumentoNormativo.objects.create(
        document_key=_sha("review-workspace-candidate"),
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="archive:review-workspace-candidate",
        role=DocumentoNormativo.Role.ORIGINAL,
        original_filename="LeiComplementar_2026_742.pdf",
        content_sha256=_sha("review-workspace-pdf"),
        size_bytes=128,
        metadata_json={
            "identity_key": identity.identity_key,
            "identity_candidate": identity.identity_json,
            "synthetic": False,
        },
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )
    return document, identity


@pytest.fixture
def reviewer(db):
    user = get_user_model().objects.create_user(
        username="document-reviewer", is_active=True, is_staff=True, password="qa-only"
    )
    codenames = (
        "view_documentonormativo",
        "change_documentonormativo",
        "add_norma",
        "add_revisaojuridica",
    )
    user.user_permissions.add(*Permission.objects.filter(codename__in=codenames))
    return user


@pytest.mark.django_db(transaction=True)
def test_reviewer_sees_identity_form_and_registration_stays_pending(review_candidate, reviewer):
    document, identity = review_candidate
    client = Client()
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        page = client.get(url)
        assert page.status_code == 200
        html = page.content.decode()
        assert "Conferir identidade normativa" in html
        assert "Texto ainda não consolidado" in html
        assert "Esta ação registra apenas a identidade" in html
        assert "Comparei o tipo, número e ano" in html
        assert 'name="csrfmiddlewaretoken"' in html

        response = client.post(url, {
            "action": "review_identity",
            "confirm_identity": "on",
            "reason": "Epígrafe cotejada com o PDF público original.",
            "confirmed_condition_of_use": DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            "confirmed_identity_key": identity.identity_key,
            "expected_fingerprint": promotion_fingerprint(document),
        })

    assert response.status_code == 303
    document.refresh_from_db()
    assert document.norma_id is not None
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.accepted_extraction_id is None
    norma = Norma.objects.get(pk=document.norma_id)
    assert norma.status == Norma.Status.PENDING
    assert norma.texto_original == norma.texto_consolidado == ""
    assert norma.documento_base_id is None
    assert RevisaoJuridica.objects.filter(documento=document).count() == 1
    history_page = client.get(f"{url}?identity=registered")
    html = history_page.content.decode()
    assert history_page.status_code == 200
    assert "Revisões registradas" in html
    assert "Epígrafe cotejada com o PDF público original." in html
    assert reviewer.username in html
    assert "fingerprint" in html


@pytest.mark.django_db
def test_document_integrity_hash_is_compact_and_expandable(review_candidate, reviewer):
    document, _identity = review_candidate
    client = Client()
    client.force_login(reviewer)
    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        response = client.get(reverse("legislation:document_evidence", args=[document.public_id]))

    assert response.status_code == 200
    html = response.content.decode()
    assert f'class="document-evidence-hash__preview">{document.content_sha256[:12]}…</code>' in html
    assert "<summary>Ver SHA-256 completo</summary>" in html
    assert f'<code>{document.content_sha256}</code></details>' in html


@pytest.mark.django_db(transaction=True)
def test_stale_identity_form_returns_conflict_and_preserves_input(review_candidate, reviewer):
    document, identity = review_candidate
    norma_count_before = Norma.objects.count()
    client = Client()
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])
    stale_fingerprint = promotion_fingerprint(document)
    document.metadata_json = {**document.metadata_json, "review_note": "changed after page load"}
    document.save(update_fields=["metadata_json", "updated_at"])

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        response = client.post(url, {
            "action": "review_identity",
            "confirm_identity": "on",
            "reason": "Minha justificativa ainda deve permanecer no formulário.",
            "confirmed_condition_of_use": DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            "confirmed_identity_key": identity.identity_key,
            "expected_fingerprint": stale_fingerprint,
        })

    assert response.status_code == 409
    assert "O documento mudou desde a abertura" in response.content.decode()
    assert "Minha justificativa ainda deve permanecer no formulário" in response.content.decode()
    assert Norma.objects.count() == norma_count_before
    assert RevisaoJuridica.objects.filter(documento=document).count() == 0


@pytest.mark.django_db
def test_view_only_staff_cannot_register_identity(review_candidate):
    document, identity = review_candidate
    norma_count_before = Norma.objects.count()
    user = get_user_model().objects.create_user(
        username="document-reader", is_active=True, is_staff=True, password="qa-only"
    )
    view_permission = Permission.objects.get(codename="view_documentonormativo")
    user.user_permissions.add(view_permission)
    client = Client(raise_request_exception=False)
    client.force_login(user)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        page = client.get(url)
        response = client.post(url, {
            "action": "review_identity",
            "confirm_identity": "on",
            "reason": "Não deve ser registrado.",
            "confirmed_condition_of_use": DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            "confirmed_identity_key": identity.identity_key,
            "expected_fingerprint": promotion_fingerprint(document),
        })

    assert page.status_code == 200
    assert "Conferir identidade normativa" not in page.content.decode()
    assert "Revisões registradas" not in page.content.decode()
    assert response.status_code == 403
    assert Norma.objects.count() == norma_count_before
    assert RevisaoJuridica.objects.filter(documento=document).count() == 0


@pytest.mark.django_db
def test_identity_registration_requires_csrf(review_candidate, reviewer):
    document, identity = review_candidate
    norma_count_before = Norma.objects.count()
    client = Client(enforce_csrf_checks=True)
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        page = client.get(url)
        response = client.post(url, {
            "action": "review_identity",
            "confirm_identity": "on",
            "reason": "A requisição sem token deve ser recusada.",
            "confirmed_condition_of_use": DocumentoNormativo.ConditionOfUse.PUBLIC_RECORD_REVIEWED,
            "confirmed_identity_key": identity.identity_key,
            "expected_fingerprint": promotion_fingerprint(document),
        })

    assert page.status_code == 200
    assert response.status_code == 403
    assert Norma.objects.count() == norma_count_before
    assert RevisaoJuridica.objects.filter(documento=document).count() == 0


@pytest.mark.django_db(transaction=True)
def test_extraction_acceptance_is_audited_but_does_not_promote_or_segment(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    document.refresh_from_db()
    extraction = _create_extraction(document)
    fingerprint = extraction_review_fingerprint(document, extraction)

    result = accept_document_extraction(
        document_id=str(document.public_id),
        extraction_id=extraction.pk,
        reviewer=reviewer,
        reason="Texto cotejado com as duas páginas do PDF; sem divergência observada.",
        expected_fingerprint=fingerprint,
    )

    document.refresh_from_db()
    norma = Norma.objects.get(pk=document.norma_id)
    assert result["text_promoted"] is False
    assert result["segmented"] is False
    assert document.accepted_extraction_id == extraction.pk
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert norma.documento_base_id is None
    assert norma.texto_original == norma.texto_consolidado == ""
    assert extraction.dispositivos_documentais.count() == 0
    review = RevisaoJuridica.objects.get(
        documento=document,
        target_fingerprint=fingerprint,
        reason__startswith="[extração documental revisada]",
    )
    assert review.actor == reviewer


@pytest.mark.django_db(transaction=True)
def test_segmentation_requires_and_records_a_separate_human_review(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    document.refresh_from_db()
    extraction = _create_extraction(document)
    accept_document_extraction(
        document_id=str(document.public_id),
        extraction_id=extraction.pk,
        reviewer=reviewer,
        reason="Texto conferido antes da etapa de promoção.",
        expected_fingerprint=extraction_review_fingerprint(document, extraction),
    )
    document.refresh_from_db()
    norma = Norma.objects.get(pk=document.norma_id)
    promote_document(
        document_id=str(document.public_id),
        norma_id=norma.pk,
        actor=reviewer,
        reason="Promoção controlada exclusivamente no banco transacional de teste.",
        expected_fingerprint=promotion_fingerprint(document),
        confirm_public_record=True,
        confirmed_identity_key=identity.identity_key,
        confirmed_role=DocumentoNormativo.Role.ORIGINAL,
    )

    segmentation = segment_document_extraction(extraction.pk)
    document.refresh_from_db()
    expected = segmentation_review_fingerprint(document, extraction)
    assert segmentation.devices
    assert has_reviewed_document_segmentation(document, extraction) is False

    first = review_document_segmentation(
        document_id=str(document.public_id),
        extraction_id=extraction.pk,
        reviewer=reviewer,
        reason="Limites e hierarquia cotejados com o PDF original.",
        expected_fingerprint=expected,
    )
    repeated = review_document_segmentation(
        document_id=str(document.public_id),
        extraction_id=extraction.pk,
        reviewer=reviewer,
        reason="Reenvio idempotente da mesma decisão.",
        expected_fingerprint=expected,
    )

    assert first["idempotent"] is False
    assert repeated["idempotent"] is True
    assert repeated["review_id"] == first["review_id"]
    assert has_reviewed_document_segmentation(document, extraction) is True
    review = RevisaoJuridica.objects.get(public_id=first["review_id"])
    assert review.actor == reviewer
    assert review.reason.startswith("[segmentação documental revisada]")
    assert document.accepted_extraction_id == extraction.pk
    norma.refresh_from_db()
    assert norma.documento_base_id == document.pk


@pytest.mark.django_db(transaction=True)
def test_segmentation_workspace_generates_preview_without_accepting_it(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    document.refresh_from_db()
    extraction = _create_extraction(document)
    accept_document_extraction(
        document_id=str(document.public_id),
        extraction_id=extraction.pk,
        reviewer=reviewer,
        reason="Texto cotejado antes da promoção de teste.",
        expected_fingerprint=extraction_review_fingerprint(document, extraction),
    )
    document.refresh_from_db()
    norma = Norma.objects.get(pk=document.norma_id)
    promote_document(
        document_id=str(document.public_id),
        norma_id=norma.pk,
        actor=reviewer,
        reason="Preparação controlada da fixture transacional.",
        expected_fingerprint=promotion_fingerprint(document),
        confirm_public_record=True,
        confirmed_identity_key=identity.identity_key,
        confirmed_role=DocumentoNormativo.Role.ORIGINAL,
    )
    document.refresh_from_db()
    client = Client()
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=False, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        before = client.get(url)
        assert before.status_code == 200
        assert "Gerar prévia de segmentação" in before.content.decode()
        assert "não representa aprovação jurídica" in before.content.decode()
        missing_confirmation = client.post(url, {
            "action": "generate_segmentation",
            "extraction_id": extraction.pk,
            "expected_fingerprint": extraction_review_fingerprint(document, extraction),
        })
        assert missing_confirmation.status_code == 400
        assert 'id="id_confirm_generation"' in missing_confirmation.content.decode()
        assert 'aria-invalid="true"' in missing_confirmation.content.decode()
        response = client.post(url, {
            "action": "generate_segmentation",
            "confirm_generation": "on",
            "extraction_id": extraction.pk,
            "expected_fingerprint": extraction_review_fingerprint(document, extraction),
        })

    assert response.status_code == 303
    assert extraction.dispositivos_documentais.exists()
    assert not has_reviewed_document_segmentation(document, extraction)
    assert "Gerar prévia de segmentação" not in client.get(url).content.decode()
    assert "Confirmar segmentação revisada" in client.get(url).content.decode()


@pytest.mark.django_db(transaction=True)
def test_extraction_acceptance_requires_complete_fresh_text(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    document.refresh_from_db()
    extraction = _create_extraction(document, status=ExtracaoDocumento.Status.PARTIAL)
    fingerprint = extraction_review_fingerprint(document, extraction)

    with pytest.raises(ValidationError, match="Somente uma extração completa"):
        accept_document_extraction(
            document_id=str(document.public_id),
            extraction_id=extraction.pk,
            reviewer=reviewer,
            reason="Tentativa de aceite de extração parcial.",
            expected_fingerprint=fingerprint,
        )
    assert document.revisoes_juridicas.count() == 1
    assert document.accepted_extraction_id is None


@pytest.mark.django_db(transaction=True)
def test_extraction_review_endpoint_preserves_stale_form_and_does_not_write(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    document.refresh_from_db()
    extraction = _create_extraction(document)
    stale_fingerprint = extraction_review_fingerprint(document, extraction)
    document.condition_of_use = DocumentoNormativo.ConditionOfUse.LICENSED
    document.save(update_fields=["condition_of_use", "updated_at"])
    client = Client()
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        response = client.post(url, {
            "action": "accept_extraction",
            "confirm_extraction": "on",
            "reason": "Preservar esta justificativa após conflito de versão.",
            "extraction_id": extraction.pk,
            "expected_fingerprint": stale_fingerprint,
        })

    assert response.status_code == 409
    assert "Fingerprint desatualizado" in response.content.decode()
    assert "Preservar esta justificativa após conflito de versão" in response.content.decode()
    document.refresh_from_db()
    assert document.accepted_extraction_id is None
    assert extraction.dispositivos_documentais.count() == 0
    assert document.revisoes_juridicas.count() == 1


@pytest.mark.django_db(transaction=True)
def test_extraction_review_form_requires_prior_identity_and_is_separate(review_candidate, reviewer):
    document, identity = review_candidate
    extraction = _create_extraction(document)
    client = Client()
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=True, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=True):
        before_identity = client.get(url)
        assert before_identity.status_code == 200
        assert "Conferir identidade normativa" in before_identity.content.decode()
        assert "Conferir extração do texto" not in before_identity.content.decode()

        _review_identity(document, identity, reviewer)
        after_identity = client.get(url)

    html = after_identity.content.decode()
    assert after_identity.status_code == 200
    assert "Conferir identidade normativa" not in html
    assert "Conferir extração do texto" in html
    assert "não promove o documento" in html.casefold()
    assert f'value="{extraction.pk}"' in html
    assert 'name="csrfmiddlewaretoken"' in html


@pytest.mark.django_db(transaction=True)
def test_authenticated_reviewer_can_inspect_candidate_without_qa_preview_flag(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    _create_extraction(document)
    client = Client()
    client.force_login(reviewer)
    url = reverse("legislation:document_evidence", args=[document.public_id])

    with override_settings(DEBUG=False, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        response = client.get(url)

    html = response.content.decode()
    assert response.status_code == 200
    assert "Texto extraído sem segmentação" in html
    assert "Conferir extração do texto" in html
    assert "Texto extraído automaticamente — rascunho não revisado" in html


@pytest.mark.django_db
def test_candidate_extraction_page_exposes_staging_ocr_gaps_and_pdf_page_links(
    review_candidate, reviewer
):
    document, _identity = review_candidate
    document.original_filename = "lc55-codigo-obras-consolidado-julho-2019.pdf"
    document.save(update_fields=["original_filename", "updated_at"])
    _create_extraction(document, status=ExtracaoDocumento.Status.PARTIAL, page_count=47, quality_json={
        "page_methods": {"native": 39, "ocr": 0, "unreadable": 8},
        "unreadable_pages": list(range(40, 48)),
        "ocr_pages_attempted": list(range(40, 48)),
        "ocr_text_is_not_certified_verbatim": False,
        "needs_review": True,
        "staging_only": True,
    })
    client = Client()
    client.force_login(reviewer)

    with override_settings(DEBUG=False, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        response = client.get(reverse("legislation:document_evidence", args=[document.public_id]))

    html = response.content.decode()
    visible_text = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", html))
    assert response.status_code == 200
    assert "Qualidade por página" in html
    assert "Texto nativo: 39 páginas" in visible_text
    assert "OCR automático: 0 páginas" in visible_text
    assert "Sem texto utilizável: 8 páginas" in visible_text
    assert "O staging inicial não executou OCR" in html
    assert 'href="/normas/documentos/' + str(document.public_id) + '/pdf/#page=40"' in html
    assert 'href="/normas/documentos/' + str(document.public_id) + '/pdf/#page=47"' in html


@pytest.mark.django_db(transaction=True)
def test_candidate_review_shows_epigraph_and_publication_date_with_distinct_meaning(
    review_candidate, reviewer
):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    _create_extraction(document, metadata_candidates_json={
        "epigraph": {
            "status": "candidate",
            "issues": [],
            "candidates": [{
                "type_key": "lei_complementar",
                "number": "742",
                "year": 2026,
                "act_date": "2026-03-12",
                "page_index": 0,
                "quote": "LEI COMPLEMENTAR Nº 742, DE 12 DE MARÇO DE 2026",
            }],
        },
        "publication": {
            "data_publicacao": "2026-03-15",
            "vigencia_na_publicacao": True,
        },
    })
    client = Client()
    client.force_login(reviewer)

    with override_settings(DEBUG=False, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        response = client.get(reverse("legislation:document_evidence", args=[document.public_id]))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Lei Complementar nº 742/2026" in html
    assert "data do ato 2026-03-12" in html
    assert "não deve ser tratada automaticamente como publicação" in html
    assert "Possível publicação encontrada no texto:</strong> 2026-03-15" in html
    assert "nem confirma vigência" in html


@pytest.mark.django_db(transaction=True)
def test_candidate_review_warns_when_filename_identity_conflicts_with_epigraph(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    _create_extraction(document, metadata_candidates_json={
        "epigraph": {
            "status": "candidate",
            "issues": [],
            "candidates": [{
                "type_key": "lei_complementar",
                "number": "742",
                "year": 2025,
                "act_date": "2025-03-12",
                "page_index": 0,
                "quote": "LEI COMPLEMENTAR Nº 742, DE 12 DE MARÇO DE 2025",
            }],
        },
    })
    client = Client()
    client.force_login(reviewer)

    with override_settings(DEBUG=False, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        response = client.get(reverse("legislation:document_evidence", args=[document.public_id]))

    html = response.content.decode()
    assert response.status_code == 200
    assert 'role="alert"><strong>Divergência entre nome do arquivo e epígrafe.' in html
    assert "os campos divergentes são year" in html
    assert "O sistema não escolherá um ano automaticamente" in html


@pytest.mark.django_db(transaction=True)
def test_candidate_review_shows_gazette_act_boundaries_as_unverified(review_candidate, reviewer):
    document, identity = review_candidate
    _review_identity(document, identity, reviewer)
    _create_extraction(
        document,
        metadata_candidates_json={
            "gazette_act_boundaries": {
                "status": "candidates_found",
                "source_text_complete": True,
                "candidates": [
                    {
                        "status": "candidate",
                        "review_required": True,
                        "type_key_candidate": "portaria",
                        "number_candidate": "44",
                        "year_candidate": 2026,
                        "heading_page": 2,
                        "spans": [{"page": 2, "start_offset": 0, "end_offset": 80}],
                    },
                    {
                        "status": "candidate",
                        "review_required": True,
                        "type_key_candidate": "edital",
                        "number_candidate": None,
                        "year_candidate": None,
                        "heading_page": 3,
                        "spans": [{"page": 3, "start_offset": 0, "end_offset": 60}],
                    },
                ],
            }
        },
    )
    client = Client()
    client.force_login(reviewer)

    with override_settings(DEBUG=False, NORMATIVE_ARCHIVE_REVIEW_UI_ENABLED=False):
        response = client.get(reverse("legislation:document_evidence", args=[document.public_id]))

    html = response.content.decode()
    assert response.status_code == 200
    assert "Atos candidatos nesta edição" in html
    assert "Portaria nº 44/2026" in html
    assert "Edital · número não identificado" in html
    assert "sugestões tipográficas entre cabeçalhos" in html
    assert "Não confirmam identidade, natureza jurídica" in html
