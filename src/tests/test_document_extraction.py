from __future__ import annotations

from io import BytesIO

import fitz
from PIL import Image

from src.processing.document_extraction import (
    extract_pdf_document,
    should_ocr_page,
)


def _make_pdf(path, pages):
    document = fitz.open()
    for text, image_bytes in pages:
        page = document.new_page()
        if text:
            page.insert_text((72, 72), text)
        if image_bytes:
            page.insert_image(fitz.Rect(72, 100, 240, 220), stream=image_bytes)
    document.save(path)
    document.close()


def _png_bytes():
    image = Image.new("RGB", (120, 80), "white")
    stream = BytesIO()
    image.save(stream, format="PNG")
    return stream.getvalue()


def test_native_text_pdf_does_not_call_ocr_and_has_verifiable_offsets(tmp_path):
    path = tmp_path / "native.pdf"
    source = "Art. 1º Esta norma municipal estabelece regras de interesse público."
    _make_pdf(path, [(source, None)])

    def forbidden_ocr(*args, **kwargs):
        raise AssertionError("OCR não deve rodar para página com texto nativo suficiente")

    result = extract_pdf_document(str(path), ocr=forbidden_ocr)

    assert result["complete"] is True
    assert result["quality"]["page_methods"] == {"native": 1, "ocr": 0, "unreadable": 0}
    assert result["raw_text"]
    assert not result["raw_text"].startswith("--- Página")
    span = result["source_map"][0]
    quote = result["legal_text"][span["start"] : span["end"]]
    assert quote == result["pages"][0]["text"]
    assert result["text_version"] == span["text_version"]


def test_short_legitimate_page_without_image_is_not_sent_to_ocr(tmp_path):
    path = tmp_path / "short-native.pdf"
    _make_pdf(path, [("Art. 4º Vigência na publicação.", None)])
    result = extract_pdf_document(str(path), ocr=lambda *_args, **_kwargs: "não esperado")
    assert result["pages"][0]["method"] == "native"
    assert result["complete"] is True


def test_extracts_epigraph_and_publication_as_candidates_without_promoting_dates(tmp_path):
    path = tmp_path / "metadata.pdf"
    _make_pdf(
        path,
        [
            (
                "Lei nº 123, de 4 de abril de 2020.\nArt. 1º Objeto.\n"
                "Art. 2º Esta Lei entra em vigor na data de sua publicação.\n"
                "Publicada no Diário Oficial do Município em: 10/4/2020 Autoria: Câmara.",
                None,
            )
        ],
    )
    result = extract_pdf_document(str(path))
    candidates = result["metadata_candidates"]
    assert candidates["epigraph"]["status"] == "candidate"
    assert candidates["epigraph"]["candidates"][0]["number"] == "123"
    assert candidates["publication"]["data_publicacao"] == "2020-04-10"
    assert candidates["publication"]["vigencia_na_publicacao"] is True
    assert result["segments"][0]["kind"] == "legal_body"


def test_mixed_pdf_only_ocr_processes_image_page_below_threshold(tmp_path):
    path = tmp_path / "mixed.pdf"
    native = "Art. 1º Esta página tem texto nativo suficiente para leitura jurídica."
    _make_pdf(path, [(native, None), ("", _png_bytes())])
    calls = []

    def fake_ocr(_image, *, timeout):
        calls.append(timeout)
        return "Art. 2º Texto reconhecido da página escaneada."

    result = extract_pdf_document(str(path), ocr=fake_ocr)
    assert calls == [90]
    assert [page["method"] for page in result["pages"]] == ["native", "ocr"]
    assert result["complete"] is True
    assert result["needs_review"] is True
    assert result["quality"]["ocr_text_is_not_certified_verbatim"] is True
    assert result["quality"]["ocr_pages_attempted"] == [2]
    assert "Art. 2º Texto reconhecido" in result["legal_text"]


def test_ocr_timeout_leaves_document_incomplete_and_page_unreadable(tmp_path):
    path = tmp_path / "timeout.pdf"
    _make_pdf(path, [("Art. 1º", _png_bytes())])

    def timeout(_image, *, timeout):
        raise TimeoutError(f"timeout after {timeout}s")

    result = extract_pdf_document(str(path), ocr=timeout)
    assert result["complete"] is False
    assert result["needs_review"] is True
    assert result["pages"][0]["method"] == "unreadable"
    assert result["pages"][0]["status"] == "timeout"
    assert result["quality"]["unreadable_pages"] == [1]
    assert result["quality"]["ocr_pages_attempted"] == [1]
    assert "Art. 1º" in result["raw_text"]


def test_empty_ocr_output_is_unreadable_not_silently_complete(tmp_path):
    path = tmp_path / "empty-ocr.pdf"
    _make_pdf(path, [("", _png_bytes())])
    result = extract_pdf_document(str(path), ocr=lambda *_args, **_kwargs: " \n ")
    assert result["complete"] is False
    assert result["pages"][0]["method"] == "unreadable"
    assert result["pages"][0]["status"] == "empty_ocr_text"
    assert result["quality"]["ocr_pages_attempted"] == [1]


def test_page_limit_does_not_return_a_truncated_complete_document(tmp_path):
    path = tmp_path / "two-pages.pdf"
    _make_pdf(path, [("Art. 1º Primeiro.", None), ("Art. 2º Segundo.", None)])
    result = extract_pdf_document(str(path), max_pages=1)
    assert result["complete"] is False
    assert result["reason"] == "page_limit_exceeded"
    assert result["pages"] == []


def test_ocr_policy_uses_both_image_and_objective_text_quality():
    assert should_ocr_page("Art. 4º", False) == (False, "no_image_native_text_preserved")
    assert should_ocr_page("Art. 4º", True) == (True, "image_with_insufficient_native_text")
    assert should_ocr_page(
        "Art. 1º Texto nativo suficientemente longo para preservar a leitura normativa.", True
    ) == (
        False,
        "native_text_sufficient",
    )
    corrupt = (
        "Art. 1º texto nativo suficientemente longo para esta verificação objetiva "
        + "\ufffd" * 3
    )
    assert should_ocr_page(corrupt, True) == (True, "image_with_corrupt_native_text")
