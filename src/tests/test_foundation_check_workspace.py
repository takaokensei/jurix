import hashlib
import re
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.models import AnonymousUser
from django.core.cache import cache
from django.template.loader import render_to_string
from django.test import Client, RequestFactory
from django.urls import reverse

from src.apps.legislation.document_models import (
    DocumentoNormativo,
    EventoNormativoCandidato,
    ExtracaoDocumento,
)
from src.apps.legislation.foundation_jobs import foundation_payload_key
from src.apps.legislation.tasks import check_foundation_task
from src.apps.legislation.workspace_views import (
    _dedupe_foundation_relation_candidates,
    _foundation_job_key,
    _foundation_relation_candidates,
)

pytestmark = pytest.mark.django_db


def test_relation_candidate_dedupe_prefers_sapl_but_keeps_distinct_targets_and_editions():
    base_key = ("lei complementar nº 258/2024", "revoga", "art. 260, inciso iv")
    archive_copy = {
        "source_label": "Lei Complementar nº 258/2024",
        "_source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
        "_dedupe_key": base_key,
    }
    sapl_copy = {
        "source_label": "Lei Complementar nº 258/2024",
        "_source_kind": DocumentoNormativo.SourceKind.SAPL,
        "_dedupe_key": base_key,
    }
    different_device = {
        "source_label": "Lei Complementar nº 185/2019",
        "target_device": "Art. 87",
        "_source_kind": DocumentoNormativo.SourceKind.SAPL,
        "_dedupe_key": ("lei complementar nº 185/2019", "altera", "art. 87"),
    }
    different_edition = {
        "source_label": "Lei Complementar nº 185/2019",
        "target_device": "Art. 34",
        "_source_kind": DocumentoNormativo.SourceKind.ARCHIVE,
        "_dedupe_key": ("lei complementar nº 185/2019", "altera", "art. 34", "republicação"),
    }

    result = _dedupe_foundation_relation_candidates(
        [archive_copy, sapl_copy, different_device, different_edition]
    )

    assert result == [sapl_copy, different_device, different_edition]
    assert all("_dedupe_key" not in item and "_source_kind" not in item for item in result)


def _user_client(username="foundation-reviewer"):
    user = get_user_model().objects.create_user(username, password="test-only")
    client = Client()
    client.force_login(user)
    return user, client


def test_foundation_relation_lookup_excludes_bill_identities():
    assert _foundation_relation_candidates(
        {"type": "projeto de lei", "number": "55", "year": 2004, "article": "21"},
        user=None,
    ) == []


def test_relation_lookup_surfaces_species_conflict_without_linking_the_acts():
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def sapl_document(key, identity, filename):
        return DocumentoNormativo.objects.create(
            document_key=digest(key),
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            source_ref=f"sapl:{key}",
            official_url=f"https://sapl.natal.rn.leg.br/media/{filename}",
            role=DocumentoNormativo.Role.ORIGINAL,
            original_filename=filename,
            content_sha256=digest(f"pdf:{key}"),
            size_bytes=100,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            metadata_json={"identity_candidate": identity},
        )

    sapl_document(
        "foundation-species-target-lc198",
        {
            "jurisdiction": "BR-RN-NATAL",
            "type": "lei_complementar",
            "number": "198",
            "year": 2021,
        },
        "lc198-2021.pdf",
    )
    source_text = (
        "Art. 260. Ficam revogados:\n"
        "VII - Lei nº 198 de 12 de novembro de 2021.\n"
    )
    source_document = sapl_document(
        "foundation-species-source-lc258",
        {
            "jurisdiction": "BR-RN-NATAL",
            "type": "lei_complementar",
            "number": "258",
            "year": 2024,
        },
        "lc258-2024.pdf",
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=source_document,
        extractor_version="foundation-species-test-v1",
        policy_fingerprint=digest("foundation-species-policy"),
        text_version="legal-text-v1",
        raw_text=source_text,
        legal_text=source_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(source_text), "page": 59}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    target_quote = "Lei nº 198 de 12 de novembro de 2021"
    action_quote = "Ficam revogados"
    action_start = source_text.index(action_quote)
    target_start = source_text.index(target_quote)
    item_start = source_text.index("VII -")
    item_quote = source_text[item_start:].strip()
    EventoNormativoCandidato.objects.create(
        extracao=extraction,
        fingerprint=digest("foundation-species-candidate"),
        source_structural_key="article-260-item-vii",
        source_device_label="Artigo 260, inciso VII",
        action="REVOGA",
        action_quote=action_quote,
        target_text=target_quote,
        target_reference_json={
            "schema_version": 1,
            "resolution_status": "candidate",
            "type_candidate": "Lei",
            "number_candidate": "198",
            "year_candidate": "2021",
            "structural_type": "lei",
            "structural_number": "198/2021",
        },
        evidence_json={
            "schema_version": 1,
            "status": "candidate_unreviewed",
            "source_extraction_sha256": extraction.extraction_sha256,
            "action_quote": action_quote,
            "action_start_offset": action_start,
            "action_end_offset": action_start + len(action_quote),
            "target_quote": target_quote,
            "target_start_offset": target_start,
            "target_end_offset": target_start + len(target_quote),
            "item_quote": item_quote,
            "item_start_offset": item_start,
            "item_end_offset": item_start + len(item_quote),
            "action_page": 59,
            "target_page": 59,
        },
        extraction_confidence=0.8,
        extraction_method="test_fixture",
    )

    complementary_lookup = _foundation_relation_candidates(
        {"type": "lei_complementar", "number": "198", "year": 2021},
        user=None,
    )
    ordinary_lookup = _foundation_relation_candidates(
        {"type": "lei", "number": "198", "year": 2021},
        user=None,
    )

    assert len(complementary_lookup) == 1
    conflict = complementary_lookup[0]
    assert conflict["status"] == "identity_conflict"
    assert conflict["identity_conflict"] is True
    assert conflict["target_text"] == target_quote
    assert conflict["target_catalog_label"] == "Lei Complementar nº 198/2021"
    assert conflict["target_catalog_records"] == [{
        "label": "Lei Complementar nº 198/2021",
        "pdf_url": "https://sapl.natal.rn.leg.br/media/lc198-2021.pdf",
    }]
    assert len(ordinary_lookup) == 1
    assert ordinary_lookup[0]["status"] == "identity_conflict"
    render_request = RequestFactory().get("/conferir/")
    render_request.user = AnonymousUser()
    rendered = render_to_string(
        "legislation/workspace/foundation_check.html",
        {
            "job_id": uuid4(),
            "text": "Lei Complementar nº 198/2021",
            "today": "2026-10-16",
            "references": [{
                "text": "Lei Complementar nº 198/2021",
                "type_key": "lei_complementar",
                "number": "198",
                "year": 2021,
                "status": "inconclusive",
                "identity": {"article": ""},
                "evidence": {},
                "documentary_relation_candidates": complementary_lookup,
            }],
            "result": {
                "comparison": {"from": "2021-01-01", "to": "2024-12-31"},
                "summary": {"inconclusive": 1},
                "references": [{
                    "text": "Lei Complementar nº 198/2021",
                    "status": "inconclusive",
                    "identity": {"article": ""},
                    "evidence": {},
                    "documentary_relation_candidates": complementary_lookup,
                }],
            },
        },
        request=render_request,
    )
    assert "Conflito de espécie" in rendered
    assert "vínculo não realizado" in rendered
    assert "Lei nº 198 de 12 de novembro de 2021" in rendered
    assert "Lei Complementar nº 198/2021" in rendered
    assert "Abrir Lei Complementar nº 198/2021 registrado no SAPL" in rendered


def test_foundation_workspace_compares_exact_pending_amendment_pdfs_without_claiming_effect():
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    def source_document(key, number, year, pdf_name, *, synthetic_fixture=False):
        identity = {
            "jurisdiction": "BR-RN-NATAL",
            "type": "lei_complementar",
            "number": number,
            "year": year,
        }
        if synthetic_fixture:
            identity["synthetic_fixture"] = True
        return DocumentoNormativo.objects.create(
            document_key=digest(key),
            source_kind=DocumentoNormativo.SourceKind.SAPL,
            source_ref=f"sapl:{key}",
            official_url=f"https://sapl.natal.rn.leg.br/media/{pdf_name}",
            role=DocumentoNormativo.Role.ORIGINAL,
            original_filename=pdf_name,
            content_sha256=digest(f"pdf:{key}"),
            size_bytes=100,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
            metadata_json={"identity_candidate": identity},
        )

    old_text = "Art. 14. Redação anterior confirmável.\nArt. 15. Outro artigo.\n"
    old_document = source_document("foundation-old-lc208", "208", 2022, "lc208.pdf")
    source_document(
        "foundation-synthetic-old-lc208",
        "208",
        2022,
        "lc208-synthetic.pdf",
        synthetic_fixture=True,
    )
    ExtracaoDocumento.objects.create(
        documento=old_document,
        extractor_version="foundation-old-test-v1",
        policy_fingerprint=digest("foundation-old-policy"),
        text_version="legal-text-v1",
        raw_text=old_text,
        legal_text=old_text,
        page_count=2,
        page_map_json=[
            {"start": 0, "end": len(old_text), "page": 11},
        ],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    source_text = (
        "Art. 261. O Art. 14 da Lei Complementar nº 208/2022 passa a vigorar "
        "com a seguinte redação: “Art. 14. Redação substitutiva extraída.”\n"
    )
    source_document_record = source_document(
        "foundation-new-lc258", "258", 2024, "lc258.pdf"
    )
    source_extraction = ExtracaoDocumento.objects.create(
        documento=source_document_record,
        extractor_version="foundation-new-test-v1",
        policy_fingerprint=digest("foundation-new-policy"),
        text_version="legal-text-v1",
        raw_text=source_text,
        legal_text=source_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(source_text), "page": 59}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    action_quote = "passa a vigorar com a seguinte redação"
    target_quote = "Art. 14 da Lei Complementar nº 208/2022"
    item_start = source_text.index("Art. 261.")
    action_start = source_text.index(action_quote)
    target_start = source_text.index(target_quote)
    EventoNormativoCandidato.objects.create(
        extracao=source_extraction,
        fingerprint=digest("foundation-pending-amendment"),
        source_structural_key="article-261",
        source_device_label="Artigo 261",
        action="ALTERA",
        action_quote=action_quote,
        target_text=target_quote,
        target_reference_json={
            "schema_version": 1,
            "resolution_status": "candidate",
            "type_candidate": "Lei Complementar",
            "number_candidate": "208",
            "year_candidate": "2022",
            "structural_type": "artigo",
            "structural_number": "14",
            "structural_article_number": "14",
        },
        evidence_json={
            "schema_version": 1,
            "status": "candidate_unreviewed",
            "source_extraction_sha256": source_extraction.extraction_sha256,
            "action_quote": action_quote,
            "action_start_offset": action_start,
            "action_end_offset": action_start + len(action_quote),
            "target_quote": target_quote,
            "target_start_offset": target_start,
            "target_end_offset": target_start + len(target_quote),
            "item_quote": source_text[item_start:].strip(),
            "item_start_offset": item_start,
            "item_end_offset": item_start + len(source_text[item_start:].strip()),
            "item_device": "Artigo 261",
            "action_device": "Artigo 261",
            "action_page": 59,
            "target_page": 59,
        },
        extraction_confidence=0.8,
        extraction_method="test_fixture",
    )

    result = _foundation_relation_candidates(
        {"type": "lei_complementar", "number": "208", "year": 2022, "article": "14"},
        user=None,
    )

    assert len(result) == 1
    comparison = result[0]["amendment_comparison"]
    assert comparison["original_text"].startswith("Art. 14. Redação anterior confirmável.")
    assert comparison["amended_text"].startswith("Art. 14. Redação substitutiva extraída.")
    assert comparison["original_pdf_url"].endswith("lc208.pdf#page=11")
    assert comparison["amended_pdf_url"].endswith("lc258.pdf#page=59")
    assert comparison["status"] == "candidate_unreviewed"
    assert result[0]["target_catalog_records"] == [{
        "label": "Lei Complementar nº 208/2022",
        "pdf_url": "https://sapl.natal.rn.leg.br/media/lc208.pdf",
    }]


def test_foundation_relation_candidate_exposes_exact_repeal_evidence_without_promoting_it():
    legal_text = (
        "Art. 260. Ficam revogados:\n"
        "I - Lei Complementar nº 055 de 27 de janeiro de 2004;\n"
    )
    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    document = DocumentoNormativo.objects.create(
        document_key=digest("foundation-relation-source"),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:foundation-relation-source",
        official_url="https://sapl.natal.rn.leg.br/media/lc258.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        original_filename="lc258.pdf",
        content_sha256=digest("foundation-relation-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={
            "identity_candidate": {
                "jurisdiction": "BR-RN-NATAL",
                "type": "lei_complementar",
                "number": "258",
                "year": 2024,
            }
        },
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="foundation-relation-test-v1",
        policy_fingerprint=digest("foundation-relation-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 59}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    action_quote = "Ficam revogados"
    target_text = "Lei Complementar nº 055 de 27 de janeiro de 2004"
    action_start = legal_text.index(action_quote)
    target_start = legal_text.index(target_text)
    EventoNormativoCandidato.objects.create(
        extracao=extraction,
        fingerprint=digest("foundation-relation-candidate"),
        source_structural_key="art-260",
        source_device_label="Artigo 260",
        action="REVOGA",
        action_quote=action_quote,
        target_text=target_text,
        target_reference_json={
            "schema_version": 1,
            "resolution_status": "candidate",
            "type_candidate": "Lei Complementar",
            "number_candidate": "055",
            "year_candidate": "2004",
            "structural_type": "act",
            "structural_number": "",
        },
        evidence_json={
            "schema_version": 1,
            "status": "candidate_unreviewed",
            "source_extraction_sha256": extraction.extraction_sha256,
            "action_quote": action_quote,
            "action_start_offset": action_start,
            "action_end_offset": action_start + len(action_quote),
            "target_quote": target_text,
            "target_start_offset": target_start,
            "target_end_offset": target_start + len(target_text),
            "item_quote": legal_text,
            "item_start_offset": 0,
            "item_end_offset": len(legal_text),
            "item_device": "Artigo 260",
            "action_device": "Artigo 260",
            "action_page": 59,
            "target_page": 59,
        },
        extraction_confidence=0.8,
        extraction_method="test_fixture",
    )
    candidates = _foundation_relation_candidates(
        {"type": "lei_complementar", "number": "55", "year": 2004, "article": "21"},
        user=None,
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["action"] == "REVOGA"
    assert candidate["source_label"] == "Lei Complementar nº 258/2024"
    assert candidate["source_device"] == "Artigo 260"
    assert candidate["target_scope"] == "act"
    assert candidate["target_text"] == "Lei Complementar nº 055 de 27 de janeiro de 2004"
    assert candidate["action_quote"] == "Ficam revogados"
    assert candidate["status"] == "candidate_unreviewed"
    assert candidate["pdf_url"].startswith("https://sapl.natal.rn.leg.br/media/lc258.pdf#page=59")
    assert candidate["review_url"] is None

    newer_text = "Art. 260. Texto da reextração sem a cláusula revogatória anterior."
    ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="foundation-relation-test-v2",
        policy_fingerprint=digest("foundation-relation-policy-v2"),
        text_version="legal-text-v2",
        raw_text=newer_text,
        legal_text=newer_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(newer_text), "page": 59}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    assert _foundation_relation_candidates(
        {"type": "lei_complementar", "number": "55", "year": 2004, "article": "21"},
        user=None,
    ) == []


def test_relation_candidate_links_exact_bvn_act_and_labels_different_year_sapl_record():
    legal_text = "Art. 260. Ficam revogados: II - Lei nº 4.566, de 1992."

    def digest(value):
        return hashlib.sha256(value.encode()).hexdigest()

    document = DocumentoNormativo.objects.create(
        document_key=digest("foundation-4566-source"),
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:foundation-4566-source",
        official_url="https://sapl.natal.rn.leg.br/media/lc258.pdf",
        role=DocumentoNormativo.Role.ORIGINAL,
        original_filename="lc258.pdf",
        content_sha256=digest("foundation-4566-source-pdf"),
        size_bytes=100,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
        metadata_json={"identity_candidate": {
            "jurisdiction": "BR-RN-NATAL", "type": "lei_complementar",
            "number": "258", "year": 2024,
        }},
    )
    extraction = ExtracaoDocumento.objects.create(
        documento=document,
        extractor_version="foundation-4566-test-v1",
        policy_fingerprint=digest("foundation-4566-policy"),
        text_version="legal-text-v1",
        raw_text=legal_text,
        legal_text=legal_text,
        page_count=1,
        page_map_json=[{"start": 0, "end": len(legal_text), "page": 59}],
        status=ExtracaoDocumento.Status.COMPLETE,
        extraction_sha256="",
    )
    target_quote = "Lei nº 4.566, de 1992"
    target_start = legal_text.index(target_quote)
    action_quote = "Ficam revogados"
    action_start = legal_text.index(action_quote)
    EventoNormativoCandidato.objects.create(
        extracao=extraction,
        fingerprint=digest("foundation-4566-candidate"),
        source_structural_key="art-260-item-ii",
        source_device_label="Artigo 260, inciso II",
        action="REVOGA",
        action_quote=action_quote,
        target_text=target_quote,
        target_reference_json={
            "schema_version": 1,
            "resolution_status": "candidate",
            "type_candidate": "Lei",
            "number_candidate": "4566",
            "year_candidate": "1992",
            "structural_type": "act",
            "structural_number": "",
        },
        evidence_json={
            "schema_version": 1,
            "status": "candidate_unreviewed",
            "source_extraction_sha256": extraction.extraction_sha256,
            "action_quote": action_quote,
            "action_start_offset": action_start,
            "action_end_offset": action_start + len(action_quote),
            "target_quote": target_quote,
            "target_start_offset": target_start,
            "target_end_offset": target_start + len(target_quote),
            "item_quote": legal_text,
            "item_start_offset": 0,
            "item_end_offset": len(legal_text),
            "item_device": "Artigo 260, inciso II",
            "action_device": "Artigo 260",
            "action_page": 59,
            "target_page": 59,
        },
        extraction_confidence=0.8,
        extraction_method="test_fixture",
    )

    candidates = _foundation_relation_candidates(
        {"type": "lei", "number": "4566", "year": 1992}, user=None
    )

    assert len(candidates) == 1
    candidate = candidates[0]
    assert candidate["status"] == "candidate_unreviewed"
    assert candidate["target_catalog_records"] == [{
        "label": "Lei Ordinária nº 4566/1994",
        "pdf_url": "https://sapl.natal.rn.leg.br/norma/6491",
        "year_conflict": True,
    }]
    assert candidate["target_official_sources"][0]["source"] == "Biblioteca Virtual do Natal (BVN)"
    assert candidate["target_identity_conflict"] is True
    assert candidate["target_official_sources"][0]["document_url"] == (
        "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf"
    )
    assert "Conflito documental de identidade" in candidate["target_official_sources"][0]["note"]
    assert "presente Decreto" in candidate["target_official_sources"][0]["note"]
    render_request = RequestFactory().get("/conferir/")
    render_request.user = AnonymousUser()
    rendered = render_to_string(
        "legislation/workspace/foundation_check.html",
        {
            "job_id": uuid4(),
            "text": "Lei nº 4.566/1992",
            "today": "2026-10-16",
            "result": {
                "comparison": {"from": "1992-01-01", "to": "2024-12-31"},
                "summary": {"inconclusive": 1},
                "references": [{
                    "text": "Lei nº 4.566/1992",
                    "status": "inconclusive",
                    "identity": {"article": ""},
                    "evidence": {},
                    "documentary_relation_candidates": [candidate],
                }],
            },
        },
        request=render_request,
    )
    assert "Conferir registro SAPL distinto: Lei Ordinária nº 4566/1994" in rendered
    assert "https://www2.natal.rn.gov.br/bvn/publicacoes/lei_4.566.pdf" in rendered
    assert "identidade do alvo não resolvida" in rendered


def test_foundation_workspace_requires_authentication_and_uses_workspace_shell():
    response = Client().get(reverse("workspace:foundation_check"))
    assert response.status_code == 302
    assert response["Location"].startswith("/conta/entrar/?next=/conferir/")

    user, client = _user_client()
    response = client.get(reverse("workspace:foundation_check"))
    assert response.status_code == 200
    body = response.content.decode()
    assert "Conferir fundamentação" in body
    assert "A escolha das datas aplicáveis aos fatos é do usuário" in body
    assert "O conteúdo integral não é salvo em conversa ou banco" in body
    assert "incluindo os trechos curtos das citações" in body
    assert "cache por até 15 minutos" in body
    assert "Não cole conteúdo reservado sem autorização institucional" in body
    assert "jurix-foundation-check.js" in body
    assert "As datas são necessárias apenas" in body
    assert "name=\"csrfmiddlewaretoken\"" in body
    assert user.is_staff is False


def test_review_step_shows_detected_reference_and_preserves_text_without_persisting():
    user, client = _user_client("foundation-parse")
    text = "Art. 1º da Lei nº 10/2020 deve ser verificado."
    response = client.post(
        reverse("workspace:foundation_check"),
        {"action": "review", "text": text, "from_date": "2020-01-01", "to_date": "2021-01-01"},
    )
    assert response.status_code == 200
    assert "Lei nº 10/2020" in response.content.decode()
    assert "Conferir dispositivos" in response.content.decode()
    assert not user.chat_sessions.exists()


def test_review_step_renders_flat_parser_identity_and_device_metadata():
    _, client = _user_client("foundation-review-metadata")
    response = client.post(
        reverse("workspace:foundation_check"),
        {
            "action": "review",
            "text": "Fundamento: Art. 1º da Lei Complementar nº 198/2021.",
        },
    )

    assert response.status_code == 200
    body = response.content.decode()
    visible_text = " ".join(re.sub(r"<[^>]+>", " ", body).split())
    assert "Lei Complementar nº 198/2021, Art. 1" in visible_text
    assert "Espécie não identificada" not in body


def test_reference_identification_does_not_require_comparison_dates():
    _, client = _user_client("foundation-review-without-dates")
    response = client.post(
        reverse("workspace:foundation_check"),
        {"action": "review", "text": "Art. 1º da Lei nº 10/2020 deve ser verificado."},
    )

    assert response.status_code == 200
    body = response.content.decode()
    assert "Lei nº 10/2020" in body
    assert "As datas são necessárias apenas" in body
    assert "Informe duas datas válidas" not in body


def test_compare_offers_local_pdf_candidate_when_norm_is_not_consolidated():
    _, client = _user_client("foundation-pending-pdf")
    job_id = uuid4()
    document_id = uuid4()
    text = "Art. 260 da Lei Complementar nº 258/2024"
    result = {
        "comparison": {"from": "2020-01-01", "to": "2021-01-01"},
        "references": [{
            "reference_id": "ref_123456789012345678901234",
            "text": text,
            "identity": {"type": "lei_complementar", "number": "258", "year": 2024, "article": "260"},
            "status": "inconclusive",
            "reason": "norma não localizada entre as normas consolidadas",
            "evidence": {"before": [], "after": []},
            "coverage": {},
        }],
        "summary": {"inconclusive": 1},
        "persisted": False,
        "llm_used": False,
        "corpus_revision": None,
        "corpus_coverage": {"coverage_status": "unknown", "sources_checked": []},
    }
    document = SimpleNamespace(
        public_id=document_id,
        original_filename="lc_258_2024.pdf",
        entry_name="lc_258_2024.pdf",
    )
    archive_result = {
        "count": 1,
        "results": [{
            "document": document,
            "identity": {"type": "lei_complementar", "number": "258", "year": 2024},
            "excerpt": "Art. 260. Ficam revogados...",
            "excerpt_page": 60,
            "extraction_status": "partial",
        }],
    }

    with (
        patch("src.apps.legislation.tasks.check_foundation", return_value=result),
        patch(
            "src.apps.legislation.tasks.check_foundation_task.apply_async",
            side_effect=lambda args: check_foundation_task.run(*args),
        ),
        patch("src.apps.legislation.workspace_views.search_archive_documents", return_value=archive_result) as search,
        patch("src.apps.legislation.workspace_views.local_pdf_available", return_value=True),
    ):
        queued_response = client.post(
            reverse("workspace:foundation_check"),
            {
                "action": "compare", "job_id": str(job_id), "text": text,
                "from_date": "2020-01-01", "to_date": "2021-01-01",
            },
        )

        response = client.get(
            reverse("workspace:foundation_check_result", args=(job_id,)), follow=True
        )

    assert queued_response.status_code == 200
    assert "Conferência na fila" in queued_response.content.decode()
    assert response.status_code == 200
    body = response.content.decode()
    assert "PDFs locais para revisão" in body
    assert "não estão consolidados nem confirmam identidade, redação ou vigência" in body
    assert "Lei Complementar nº 258/2024" in body
    assert "lc_258_2024.pdf" in body
    assert f"/normas/documentos/{document_id}/pdf/#page=60" in body
    search.assert_called_once_with(text, page=1, include_results=True)
    cache.delete(_foundation_job_key(job_id))


def test_compare_returns_evidence_links_and_cache_contains_no_pasted_text():
    user, client = _user_client("foundation-compare")
    job_id = uuid4()
    text = "Art. 1º da Lei nº 10/2020 deve ser verificado."
    called = {}
    evidence = {
        "evidence_id": "ev_123456789012345678901234",
        "document_id": str(uuid4()),
        "page": 3,
        "text": "Texto normativo público.",
        "legal_status": "in_force",
        "source_event_id": 7,
        "source_norma_id": 99,
        "effective_on": "2020-06-01",
    }
    result = {
        "comparison": {"from": "2020-01-01", "to": "2021-01-01"},
        "references": [{
            "reference_id": "ref_123456789012345678901234",
            "text": text,
            "identity": {"article": "1"},
            "status": "changed",
            "reason": None,
            "norma": "Lei nº 10/2020",
            "evidence": {"before": [dict(evidence)], "after": [dict(evidence)]},
            "coverage": {"before": {"reason": "verified"}, "after": {"reason": "verified"}},
        }],
        "summary": {"changed": 1, "revoked": 0, "vetoed": 0, "unchanged_in_checked_scope": 0, "inconclusive": 0, "confirmation_required": 0},
        "persisted": False,
        "llm_used": False,
        "corpus_revision": {"revision": 12, "completeness": "partial", "generated_at": "2026-10-08T12:00:00+00:00"},
        "corpus_coverage": {
            "coverage_status": "unknown",
            "checked_until": None,
            "sources_checked": [],
        },
    }

    class SourceNorma:
        pk = 99
        identity_json = {}
        sapl_url = ""
        sapl_id = None

        def __str__(self):
            return "Lei nº 5/2019"

    source_norma = SourceNorma()
    source_device = SimpleNamespace(norma=source_norma, get_caminho_completo=lambda: "Art. 2º")
    event = SimpleNamespace(
        pk=7,
        dispositivo_fonte=source_device,
        effective_on=date(2020, 6, 1),
        target_text="Altera o Art. 1º da Lei nº 10/2020",
        get_acao_display=lambda: "Alteração",
    )
    events_queryset = SimpleNamespace(select_related=lambda *_args: [event])

    def fake_check(*, references, from_date, to_date, should_cancel, on_progress):
        called.update(references=references, from_date=from_date, to_date=to_date)
        on_progress(2, 2)
        assert should_cancel() is False
        return result

    with (
        patch("src.apps.legislation.tasks.check_foundation", side_effect=fake_check),
        patch(
            "src.apps.legislation.tasks.check_foundation_task.apply_async",
            side_effect=lambda args: check_foundation_task.run(*args),
        ),
        patch("src.apps.legislation.workspace_views.EventoAlteracao.objects.filter", return_value=events_queryset),
        patch("src.apps.legislation.workspace_views.event_review_status", return_value="confirmed"),
    ):
        queued_response = client.post(
            reverse("workspace:foundation_check"),
            {
                "action": "compare", "job_id": str(job_id), "text": text,
                "from_date": "2020-01-01", "to_date": "2021-01-01",
            },
        )

        response = client.get(
            reverse("workspace:foundation_check_result", args=(job_id,)), follow=True
        )

    assert queued_response.status_code == 200
    assert response.status_code == 200
    body = response.content.decode()
    assert "Redação diferente" in body
    assert "Corte do corpus" in body and "revisão 12" in body
    assert "Cobertura registrada:</strong> desconhecida" in body
    assert "data de corte não informada" in body
    assert "completude declarada: parcial." in body
    assert "nenhum evento de alteração ou revogação foi aplicado a este trecho neste recorte" in body
    assert "não certifica vigência jurídica nem cobertura integral" in body
    assert "indicado como vigente neste corte" not in body
    assert "A ausência de escopo revisado mantém “sem mudança” inconclusivo." in body
    assert "Evento revisado que explica a redação" in body
    assert "Lei nº 5/2019, Art. 2º" in body
    assert f"/normas/documentos/{evidence['document_id']}/pdf/#page=3" in body
    assert len(called["references"]) == 1
    assert called["references"][0].article == "1"
    assert called["from_date"] == date(2020, 1, 1)
    assert called["to_date"] == date(2021, 1, 1)
    state = cache.get(_foundation_job_key(job_id))
    assert state == {"owner_id": user.pk, "status": "completed", "completed": 2, "total": 2}
    assert text not in repr(state)
    assert cache.get(foundation_payload_key(job_id)) is None
    cache.delete(_foundation_job_key(job_id))

    for status, expected_label, legal_status, expected_legal_label in (
        ("partial", "Cobertura registrada:</strong> parcial", "revoked", "trecho marcado como revogado nesta projeção"),
        (
            "reviewed", "Cobertura registrada:</strong> revisada somente nos escopos listados",
            "unknown", "situação indeterminada por pendência ou conflito",
        ),
        (
            "unknown", "Cobertura registrada:</strong> desconhecida",
            "vetoed", "trecho marcado como vetado nesta projeção",
        ),
    ):
        next_job_id = uuid4()
        result["corpus_coverage"]["coverage_status"] = status
        evidence["legal_status"] = legal_status
        for moment in ("before", "after"):
            result["references"][0]["evidence"][moment][0]["legal_status"] = legal_status
        with (
            patch("src.apps.legislation.tasks.check_foundation", side_effect=fake_check),
            patch(
                "src.apps.legislation.tasks.check_foundation_task.apply_async",
                side_effect=lambda args: check_foundation_task.run(*args),
            ),
            patch("src.apps.legislation.workspace_views.EventoAlteracao.objects.filter", return_value=events_queryset),
            patch("src.apps.legislation.workspace_views.event_review_status", return_value="confirmed"),
        ):
            next_queued_response = client.post(
                reverse("workspace:foundation_check"),
                {
                    "action": "compare", "job_id": str(next_job_id), "text": text,
                    "from_date": "2020-01-01", "to_date": "2021-01-01",
                },
            )
            response = client.get(
                reverse("workspace:foundation_check_result", args=(next_job_id,)), follow=True
            )
        assert next_queued_response.status_code == 200
        assert response.status_code == 200
        body = response.content.decode()
        assert expected_label in body
        assert "data de corte não informada" in body
        assert f"Projeção técnica: {expected_legal_label}" in body
        assert "não certifica vigência jurídica nem cobertura integral" in body
        cache.delete(_foundation_job_key(next_job_id))


def test_compare_queues_only_job_id_and_caches_parsed_references_not_pasted_prose():
    user, client = _user_client("foundation-queued-private")
    job_id = uuid4()
    text = "Diante dos fatos narrados no processo administrativo reservado, observe o Art. 1º da Lei nº 10/2020."

    def inspect_enqueue(*, args):
        assert args == [str(job_id)]
        state = cache.get(_foundation_job_key(job_id))
        payload = cache.get(foundation_payload_key(job_id))
        assert state == {"owner_id": user.pk, "status": "queued", "completed": 0, "total": 0}
        assert payload["owner_id"] == user.pk
        assert payload["references"][0]["number"] == "10"
        assert payload["references"][0]["text"] in repr(payload)
        assert text not in repr(payload)
        return SimpleNamespace(id="qa-task-id")

    with patch(
        "src.apps.legislation.tasks.check_foundation_task.apply_async",
        side_effect=inspect_enqueue,
    ) as enqueue:
        response = client.post(
            reverse("workspace:foundation_check"),
            {
                "action": "compare",
                "job_id": str(job_id),
                "text": text,
                "from_date": "2020-01-01",
                "to_date": "2021-01-01",
            },
        )

    assert response.status_code == 200
    assert "Conferência na fila" in response.content.decode()
    enqueue.assert_called_once()
    cache.delete(_foundation_job_key(job_id))
    cache.delete(foundation_payload_key(job_id))


def test_status_and_cancel_endpoints_are_scoped_to_authenticated_owner():
    owner, client = _user_client("foundation-owner")
    _, other_client = _user_client("foundation-other")
    job_id = uuid4()
    key = _foundation_job_key(job_id)
    cache.set(key, {"owner_id": owner.pk, "status": "running", "completed": 0, "total": 2}, timeout=60)
    try:
        assert client.get(reverse("workspace:foundation_check_status", args=(job_id,))).json()["status"] == "running"
        assert other_client.get(reverse("workspace:foundation_check_status", args=(job_id,))).status_code == 404
        response = client.post(reverse("workspace:foundation_check_cancel", args=(job_id,)))
        assert response.status_code == 200
        assert cache.get(key)["status"] == "cancelling"
    finally:
        cache.delete(key)


def test_duplicate_compare_job_id_is_rejected_without_running_twice():
    user, client = _user_client("foundation-duplicate")
    job_id = uuid4()
    key = _foundation_job_key(job_id)
    cache.set(key, {"owner_id": user.pk, "status": "completed", "completed": 2, "total": 2}, timeout=60)
    try:
        with patch("src.apps.legislation.tasks.check_foundation_task.apply_async") as enqueue:
            response = client.post(
                reverse("workspace:foundation_check"),
                {
                    "action": "compare", "job_id": str(job_id),
                    "text": "Lei nº 10/2020, Art. 1º", "from_date": "2020-01-01", "to_date": "2021-01-01",
                },
            )
        assert response.status_code == 409
        enqueue.assert_not_called()
    finally:
        cache.delete(key)
