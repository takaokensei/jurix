from __future__ import annotations

import hashlib
from io import BytesIO

import fitz
from django.core.exceptions import ValidationError
from PIL import Image

from src.apps.legislation.document_models import ExtracaoDocumento
from src.processing.document_extraction import (
    _default_ocr,
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


def test_extraction_emits_page_linked_act_boundary_candidates_without_raw_heading_text(tmp_path):
    path = tmp_path / "gazette.pdf"
    _make_pdf(
        path,
        [
            (
                "PORTARIA N 44/2026\nDesigna comissão.\n"
                "EDITAL DE LICITAÇÃO N 8/2026\nProcedimento público.",
                None,
            ),
            ("LEI N 12/2026\nArt. 1º Objeto.", None),
        ],
    )

    result = extract_pdf_document(str(path))

    candidates = result["metadata_candidates"]["gazette_act_boundaries"]
    assert candidates["status"] == "candidates_found"
    assert candidates["offset_basis"] == "normalized page text; zero-based half-open offsets"
    assert candidates["source_text_complete"] is True
    assert [item["type_key_candidate"] for item in candidates["candidates"]] == [
        "portaria",
        "edital",
        "lei",
    ]
    assert [item["heading_page"] for item in candidates["candidates"]] == [1, 1, 2]
    assert all(item["review_required"] and item["status"] == "candidate" for item in candidates["candidates"])
    assert all("heading_text" not in item for item in candidates["candidates"])


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


def test_document_ocr_page_budget_marks_unprocessed_scans_incomplete(tmp_path):
    path = tmp_path / "ocr-budget.pdf"
    _make_pdf(path, [("", _png_bytes()), ("", _png_bytes())])
    calls = []

    def fake_ocr(_image, *, timeout):
        calls.append(timeout)
        return "Art. 1º Texto reconhecido para revisão humana."

    result = extract_pdf_document(
        str(path), max_ocr_pages=1, ocr_timeout_seconds=15, ocr=fake_ocr
    )

    assert calls == [15]
    assert result["complete"] is False
    assert result["reason"] == "ocr_document_page_budget_exceeded"
    assert result["pages"][0]["method"] == "ocr"
    assert result["pages"][1]["status"] == "ocr_budget_skipped"
    assert result["quality"]["ocr_pages_attempted"] == [1]
    assert result["quality"]["ocr_budget_skipped_pages"] == [2]


def test_incremental_ocr_reuses_verified_pages_and_processes_only_selected_backlog(tmp_path):
    path = tmp_path / "incremental-ocr.pdf"
    _make_pdf(path, [("", _png_bytes()), ("", _png_bytes()), ("Art. 3º Texto nativo suficiente.", None)])
    original = extract_pdf_document(
        str(path),
        max_ocr_pages=1,
        ocr_timeout_seconds=15,
        ocr=lambda *_args, **_kwargs: "Art. 1º OCR anteriormente verificado.",
    )
    assert original["quality"]["ocr_budget_skipped_pages"] == [2]
    original_page = original["pages"][0]["text"]
    original_source_hash = "f" * 64
    calls = []

    def resume_ocr(_image, *, timeout):
        calls.append(timeout)
        return "Art. 2º OCR recuperado nesta execução."

    resumed = extract_pdf_document(
        str(path),
        max_ocr_pages=1,
        ocr_timeout_seconds=15,
        ocr_pages_to_process={2},
        reusable_ocr_pages={1: (original_page, original_source_hash)},
        ocr=resume_ocr,
    )

    assert calls == [15]
    assert resumed["complete"] is True
    assert resumed["quality"]["ocr_pages_attempted"] == [2]
    assert resumed["quality"]["ocr_pages_reused"] == [1]
    assert resumed["quality"]["ocr_budget_skipped_pages"] == []
    assert "Art. 1º OCR anteriormente verificado." in resumed["legal_text"]
    assert "Art. 2º OCR recuperado nesta execução." in resumed["legal_text"]
    assert resumed["source_map"][0]["reused_from_extraction_sha256"] == original_source_hash
    assert resumed["source_map"][1]["method"] == "ocr"


def test_incremental_ocr_rejects_page_selection_outside_pdf(tmp_path):
    path = tmp_path / "one-page.pdf"
    _make_pdf(path, [("Art. 1º Texto nativo.", None)])

    try:
        extract_pdf_document(str(path), ocr_pages_to_process={2})
    except ValueError as exc:
        assert "page count" in str(exc)
    else:
        raise AssertionError("page selection outside the PDF must be rejected")


def test_empty_ocr_output_is_unreadable_not_silently_complete(tmp_path):
    path = tmp_path / "empty-ocr.pdf"
    _make_pdf(path, [("", _png_bytes())])
    result = extract_pdf_document(str(path), ocr=lambda *_args, **_kwargs: " \n ")
    assert result["complete"] is False
    assert result["pages"][0]["method"] == "unreadable"
    assert result["pages"][0]["status"] == "empty_ocr_text"
    assert result["quality"]["ocr_pages_attempted"] == [1]


def test_default_ocr_tries_alternative_layouts_when_primary_result_is_weak(monkeypatch):
    calls = []
    outputs = {
        "--psm 6": "",
        "--psm 4": "Texto OCR alternativo com conteúdo suficiente para revisão jurídica.",
        "--psm 11": (
            "Texto OCR alternativo mais completo que mantém conteúdo suficiente "
            "para revisão jurídica e conferência humana."
        ),
    }

    def fake_image_to_string(_image, *, lang, config, timeout):
        calls.append({"lang": lang, "config": config, "timeout": timeout})
        return outputs[config]

    monkeypatch.setattr(
        "src.processing.document_extraction.pytesseract.image_to_string",
        fake_image_to_string,
    )

    result = _default_ocr(Image.new("RGB", (20, 20), "white"), timeout=15)

    assert result == outputs["--psm 11"]
    assert [call["config"] for call in calls] == ["--psm 6", "--psm 4", "--psm 11"]
    assert all(call["lang"] == "por" for call in calls)
    assert all(0 < call["timeout"] <= 15 for call in calls)


def test_default_ocr_keeps_fast_path_when_primary_result_is_readable(monkeypatch):
    calls = []
    expected = "Texto nativo recuperado pelo primeiro modo OCR para revisão humana."

    def fake_image_to_string(_image, *, lang, config, timeout):
        calls.append((lang, config, timeout))
        return expected

    monkeypatch.setattr(
        "src.processing.document_extraction.pytesseract.image_to_string",
        fake_image_to_string,
    )

    assert _default_ocr(Image.new("RGB", (20, 20), "white"), timeout=15) == expected
    assert calls == [("por", "--psm 6", 15.0)]


def test_page_limit_does_not_return_a_truncated_complete_document(tmp_path):
    path = tmp_path / "two-pages.pdf"
    _make_pdf(path, [("Art. 1º Primeiro.", None), ("Art. 2º Segundo.", None)])
    result = extract_pdf_document(str(path), max_pages=1)
    assert result["complete"] is False
    assert result["reason"] == "page_limit_exceeded"
    assert result["pages"] == []
    assert result["policy_fingerprint"]
    assert result["extractor_version"]
    assert result["extraction_sha256"]
    assert result["quality"]["pages_not_processed"] == 2


def test_empty_or_invalid_pdf_returns_an_explicit_unreadable_candidate(tmp_path):
    path = tmp_path / "empty.pdf"
    path.write_bytes(b"")

    result = extract_pdf_document(str(path))

    assert result["complete"] is False
    assert result["needs_review"] is True
    assert result["reason"] == "unreadable_pdf"
    assert result["quality"]["extraction_error"] == "EmptyFileError"
    assert result["legal_text"] == ""
    assert result["policy_fingerprint"]
    assert result["extraction_sha256"] == hashlib.sha256(b"").hexdigest()


def test_extraction_page_map_accepts_201_pages_but_retains_a_bounded_limit():
    extraction = ExtracaoDocumento(
        page_map_json=[{"page": page} for page in range(1, 202)],
        legal_text="",
        raw_text="",
        policy_fingerprint="a" * 64,
        extraction_sha256="b" * 64,
    )
    extraction.clean()

    extraction.page_map_json = [{"page": page} for page in range(1, 502)]
    try:
        extraction.clean()
    except ValidationError as exc:
        assert "page_map_json" in exc.message_dict
    else:
        raise AssertionError("mapas acima de 500 páginas precisam permanecer limitados")


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
