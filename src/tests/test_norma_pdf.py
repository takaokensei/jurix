import fitz
import pytest
from django.test import Client

from src.apps.legislation.models import Norma


@pytest.mark.django_db
def test_pdf_export_preserves_every_page_of_long_consolidated_text():
    body = "\n".join(
        f"Art. {number}º Dispositivo QA {number}: texto jurídico integral com condição e acentuação; "
        "não onerar o Município sem autorização expressa."
        for number in range(1, 181)
    )
    norma = Norma.objects.create(
        tipo="Lei",
        numero="99001",
        ano=2026,
        status="consolidated",
        texto_original=body,
        texto_consolidado=body,
    )

    response = Client().get(f"/normas/{norma.pk}/export/pdf/")

    assert response.status_code == 200
    with fitz.open(stream=response.content, filetype="pdf") as document:
        page_texts = [page.get_text() for page in document]
    exported_text = " ".join(" ".join(page_texts).split())

    assert len(page_texts) > 1
    assert all("Art." in page_text for page_text in page_texts)
    for number in (1, 45, 90, 135, 180):
        assert f"Art. {number}º Dispositivo QA {number}" in exported_text
    assert "acentuação" in exported_text
    assert "não onerar o Município" in exported_text
