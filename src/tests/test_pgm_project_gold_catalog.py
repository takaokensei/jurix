"""QA-only browser surface for the frozen project Gold set."""

import json
from pathlib import Path

import pytest
from django.test import Client, override_settings
from django.urls import reverse

from src.apps.legislation.document_models import DocumentoNormativo
from src.apps.legislation.models import Norma

REFERENCE_ROOT = (
    Path(__file__).resolve().parents[2]
    / "benchmarks"
    / "corpus"
    / "municipal_natal"
    / "ai-adjudicated-20261018-v1"
    / "reference"
)


def _gold_hashes():
    rows = [
        json.loads(line)
        for line in (REFERENCE_ROOT / "source-origins.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [row["document_key"].removeprefix("sha256:") for row in rows]


@pytest.mark.django_db
def test_project_gold_catalog_is_only_available_with_archive_qa_enabled():
    with override_settings(NORMATIVE_ARCHIVE_ENABLED=False):
        response = Client().get(reverse("workspace:pgm_project_gold"))

    assert response.status_code == 404


@pytest.mark.django_db
def test_project_gold_catalog_lists_all_cases_and_links_matching_pending_pdfs():
    hashes = _gold_hashes()
    documents = [
        DocumentoNormativo.objects.create(
            document_key=f"gold-catalog-{index:02d}",
            source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
            source_ref=f"qa:gold-catalog:{index:02d}",
            original_filename=f"gold-{index:02d}.pdf",
            content_sha256=digest,
            review_status=DocumentoNormativo.ReviewStatus.PENDING,
        )
        for index, digest in enumerate(hashes, start=1)
    ]
    DocumentoNormativo.objects.create(
        document_key="gold-catalog-link-target",
        source_kind=DocumentoNormativo.SourceKind.ARCHIVE,
        source_ref="qa:gold-catalog:link-target",
        original_filename="unrelated-candidate.pdf",
        content_sha256="f" * 64,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        response = Client().get(reverse("workspace:pgm_project_gold"))
        catalog_response = Client().get(reverse("legislation:norma_list"))

    assert response.status_code == 200
    assert len(response.context["cases"]) == 20
    assert response.context["gold_id"] == "jurix-pgm-gold-v1"
    assert "não certificação jurídica" in response.content.decode().lower()
    assert response.content.decode().count("PDF correspondente no QA · Pendente") == 20
    assert "Lei Complementar nº 258/2024" in response.content.decode()
    assert "Art. 20" in response.content.decode()
    assert all(
        reverse("legislation:document_evidence", kwargs={"document_id": document.public_id})
        in response.content.decode()
        for document in documents
    )
    assert all(document.review_status == DocumentoNormativo.ReviewStatus.PENDING for document in documents)
    assert all(document.norma_id is None for document in documents)

    assert catalog_response.status_code == 200
    assert 'href="/explorar/gold-standard/"' in catalog_response.content.decode()


@pytest.mark.django_db
def test_pending_sapl_gold_source_uses_official_pdf_not_private_candidate_ficha():
    official_url = "https://sapl.natal.rn.leg.br/media/sapl/public/normajuridica/2018/254/lp_562.18.pdf"
    norma = Norma.objects.create(
        tipo="Lei Promulgada",
        numero="562",
        ano=2018,
        sapl_id=254,
        pdf_url=official_url,
        status=Norma.Status.PENDING,
        needs_review=True,
    )
    document = DocumentoNormativo.objects.create(
        document_key="gold-catalog-sapl-lp562",
        norma=norma,
        source_kind=DocumentoNormativo.SourceKind.SAPL,
        source_ref="sapl:254:sha256:079b0967563a670c9c880baee1642239d0d08ce19738f0c3adf83a0c3cecb119",
        original_filename="lp_562.18.pdf",
        content_sha256="079b0967563a670c9c880baee1642239d0d08ce19738f0c3adf83a0c3cecb119",
        official_url=official_url,
        review_status=DocumentoNormativo.ReviewStatus.PENDING,
    )

    with override_settings(NORMATIVE_ARCHIVE_ENABLED=True):
        response = Client().get(reverse("workspace:pgm_project_gold"))

    case = next(item for item in response.context["cases"] if item["unit_id"] == "n11")
    html = response.content.decode()
    assert case["document"] == document
    assert case["evidence_url"] == official_url
    assert case["external_source"] is True
    assert case["source_label"] == "PDF oficial SAPL · candidato não revisado"
    assert official_url in html
    assert "Abrir PDF oficial no SAPL" in html
    assert "target=\"_blank\" rel=\"noopener noreferrer\"" in html
    assert document.review_status == DocumentoNormativo.ReviewStatus.PENDING
    assert document.accepted_extraction_id is None
    norma.refresh_from_db()
    assert norma.status == Norma.Status.PENDING
    assert norma.identity_key is None
    assert norma.documento_base_id is None
    assert not norma.texto_consolidado
