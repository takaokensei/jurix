from __future__ import annotations

import hashlib
from io import BytesIO

import fitz
from django.core.exceptions import ValidationError
from PIL import Image, ImageDraw

from src.apps.legislation.document_models import ExtracaoDocumento
from src.processing.document_extraction import (
    EXTRACTION_POLICY,
    _default_ocr,
    extract_layout_table_candidate,
    extract_pdf_document,
    extract_raster_table_candidate,
    page_has_image,
    page_is_blank,
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
    assert result["quality"]["page_methods"] == {
        "native": 1,
        "ocr": 0,
        "blank": 0,
        "unreadable": 0,
    }
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


def test_trailing_blank_page_does_not_make_document_unreadable(tmp_path):
    path = tmp_path / "trailing-blank-page.pdf"
    _make_pdf(path, [("Decreto nº 10.850/2015. Art. 1º Conteúdo normativo.", None), ("", None)])

    def forbidden_ocr(*args, **kwargs):
        raise AssertionError("página realmente vazia não deve disparar OCR")

    result = extract_pdf_document(str(path), ocr=forbidden_ocr)

    assert result["complete"] is True
    assert result["needs_review"] is False
    assert [page["method"] for page in result["pages"]] == ["native", "blank"]
    assert [page["status"] for page in result["pages"]] == ["complete", "blank"]
    assert result["quality"]["blank_pages"] == [2]
    assert result["quality"]["unreadable_pages"] == []
    assert "Conteúdo normativo" in result["technical_text"]


def test_white_page_background_drawing_is_blank_but_visible_vector_ink_is_not(tmp_path):
    path = tmp_path / "vector-blank-and-ink.pdf"
    document = fitz.open()
    white_page = document.new_page()
    white_page.draw_rect(white_page.rect, fill=(1, 1, 1), color=None)
    ink_page = document.new_page()
    ink_page.draw_line((40, 40), (120, 120), color=(0, 0, 0), width=1)
    document.save(path)
    document.close()

    with fitz.open(path) as saved:
        assert page_is_blank(saved[0], saved[0].get_text("text") or "", False)
        assert not page_is_blank(saved[1], saved[1].get_text("text") or "", False)


def test_invisible_native_text_with_thin_footer_rule_is_blank(tmp_path):
    path = tmp_path / "invisible-text-footer-rule.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((120, 120), "conteudo invisivel sem texto normativo", render_mode=3)
    footer_y = page.rect.height * 0.94
    page.draw_line(
        (page.rect.width * 0.15, footer_y),
        (page.rect.width * 0.95, footer_y),
        color=(0.72, 0.72, 0.72),
        width=1.5,
    )
    document.save(path)
    document.close()

    with fitz.open(path) as saved:
        native_text = saved[0].get_text("text") or ""
        assert native_text.strip()
        assert page_is_blank(saved[0], native_text, False)


def test_visible_short_text_with_footer_rule_is_not_blank(tmp_path):
    path = tmp_path / "visible-short-text-footer-rule.pdf"
    document = fitz.open()
    page = document.new_page()
    page.insert_text((72, 72), "Art. 4º Vigência na publicação.")
    footer_y = page.rect.height * 0.94
    page.draw_line(
        (page.rect.width * 0.15, footer_y),
        (page.rect.width * 0.95, footer_y),
        color=(0.72, 0.72, 0.72),
        width=1.5,
    )
    document.save(path)
    document.close()

    with fitz.open(path) as saved:
        native_text = saved[0].get_text("text") or ""
        assert not page_is_blank(saved[0], native_text, False)


def test_page_has_image_ignores_unplaced_image_resources():
    class PageWithOrphanedImageResource:
        @staticmethod
        def get_image_info(*, xrefs):
            assert xrefs is True
            return []

        @staticmethod
        def get_images(*, full):
            assert full is True
            return [(10, 0, 120, 80, 8, "DeviceRGB", "", "Im0", "FlateDecode", 0)]

    assert page_has_image(PageWithOrphanedImageResource()) is False


def test_page_has_image_detects_placed_image_even_without_resource_inventory():
    class PageWithPlacedImage:
        @staticmethod
        def get_image_info(*, xrefs):
            assert xrefs is True
            return [{"bbox": (10, 10, 110, 80)}]

        @staticmethod
        def get_images(*, full):
            assert full is True
            return []

    assert page_has_image(PageWithPlacedImage()) is True


def test_table_layout_candidates_are_separate_from_legal_text(tmp_path, monkeypatch):
    path = tmp_path / "ruled-table.pdf"
    document = fitz.open()
    page = document.new_page()
    for y in (50, 80, 110):
        page.draw_line((50, y), (250, y), color=(0, 0, 0), width=0.7)
    for x in (50, 150, 250):
        page.draw_line((x, 50), (x, 110), color=(0, 0, 0), width=0.7)
    for point, text in (
        ((60, 70), "Código"),
        ((160, 70), "Valor"),
        ((60, 100), "COSIP"),
        ((160, 100), "2,5%"),
    ):
        page.insert_text(point, text)
    document.save(path)
    document.close()

    monkeypatch.setitem(EXTRACTION_POLICY, "layout_table_candidates", False)
    without_candidates = extract_pdf_document(str(path), ocr=lambda *_args, **_kwargs: "")
    monkeypatch.setitem(EXTRACTION_POLICY, "layout_table_candidates", True)
    with_candidates = extract_pdf_document(str(path), ocr=lambda *_args, **_kwargs: "")

    tables = with_candidates["metadata_candidates"]["layout_tables"]["candidates"]
    assert without_candidates["legal_text"] == with_candidates["legal_text"]
    assert with_candidates["metadata_candidates"]["layout_tables"]["status"] == "unreviewed_candidates"
    assert len(tables) == 1
    assert tables[0]["status"] == "unreviewed_candidate"
    assert tables[0]["page"] == 1
    assert tables[0]["rows"] == [["Código", "Valor"], ["COSIP", "2,5%"]]
    assert "não integra o texto legal" in tables[0]["review_note"].casefold()


def test_table_candidate_payload_obeys_row_column_and_character_limits():
    class Table:
        bbox = (1, 2, 3, 4)

        @staticmethod
        def extract():
            return [["x" * 1000 for _ in range(20)] for _ in range(60)]

    class Page:
        @staticmethod
        def find_tables():
            return type("Finder", (), {"tables": [Table()]})()

    candidate = extract_layout_table_candidate(Page(), 3)[0]
    assert len(candidate["rows"]) == 40
    assert all(len(row) == 16 for row in candidate["rows"])
    assert sum(len(cell) for row in candidate["rows"] for cell in row) <= 24_000
    assert candidate["truncated"] is True


def test_raster_table_candidate_uses_grid_and_word_boxes_without_certifying_text():
    image = Image.new("RGB", (400, 240), "white")
    draw = ImageDraw.Draw(image)
    for y in (20, 70, 130, 200):
        draw.line((20, y, 380, y), fill="black", width=2)
    for x in (20, 120, 300, 380):
        draw.line((x, 20, x, 200), fill="black", width=2)
    data = {
        "text": ["Item", "Descrição", "Valor", "A", "Taxa", "2%"],
        "left": [35, 135, 315, 35, 135, 315],
        "top": [35, 35, 35, 85, 85, 85],
        "width": [30, 55, 25, 18, 40, 20],
        "height": [12] * 6,
        "conf": [90] * 6,
    }

    candidate = extract_raster_table_candidate(image, 69, data)

    assert len(candidate) == 1
    assert candidate[0]["status"] == "unreviewed_candidate"
    assert candidate[0]["detector"] == "raster_grid+tesseract_word_boxes"
    assert candidate[0]["rows"][:2] == [
        ["Item", "Descrição", "Valor"],
        ["A", "Taxa", "2%"],
    ]
    assert "não integra o texto legal" in candidate[0]["review_note"].casefold()


def test_raster_table_candidate_character_limit_truncates_without_negative_slicing(monkeypatch):
    image = Image.new("RGB", (400, 240), "white")
    draw = ImageDraw.Draw(image)
    for y in (20, 70, 130, 200):
        draw.line((20, y, 380, y), fill="black", width=2)
    for x in (20, 120, 300, 380):
        draw.line((x, 20, x, 200), fill="black", width=2)
    monkeypatch.setitem(EXTRACTION_POLICY, "max_layout_table_chars", 5)
    data = {
        "text": ["abc", "de", "fg"],
        "left": [30, 130, 310],
        "top": [30, 30, 30],
        "width": [20, 20, 20],
        "height": [12] * 3,
        "conf": [90] * 3,
    }

    candidate = extract_raster_table_candidate(image, 69, data)

    assert candidate[0]["truncated"] is True
    assert sum(len(cell) for row in candidate[0]["rows"] for cell in row) <= 5
    assert candidate[0]["rows"][0] == ["abc", "de", ""]


def test_default_ocr_raster_grid_candidate_stays_separate_from_legal_text(tmp_path, monkeypatch):
    image = Image.new("RGB", (400, 240), "white")
    draw = ImageDraw.Draw(image)
    for y in (20, 70, 130, 200):
        draw.line((20, y, 380, y), fill="black", width=2)
    for x in (20, 120, 300, 380):
        draw.line((x, 20, x, 200), fill="black", width=2)
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    path = tmp_path / "raster-ruled-table.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_image(fitz.Rect(0, 0, 200, 120), stream=image_bytes.getvalue())
    document.save(path)
    document.close()

    monkeypatch.setattr(
        "src.processing.document_extraction.pytesseract.image_to_string",
        lambda *_args, **_kwargs: "Texto OCR independente da prévia tabular.",
    )

    def fake_image_to_data(rendered, **_kwargs):
        width, height = rendered.size
        return {
            "text": ["Item", "Descrição", "Valor", "A", "Taxa", "2%"],
            "left": [int(width * r) for r in (0.08, 0.35, 0.80, 0.08, 0.35, 0.80)],
            "top": [int(height * r) for r in (0.18, 0.18, 0.18, 0.40, 0.40, 0.40)],
            "width": [20] * 6,
            "height": [12] * 6,
            "conf": [90] * 6,
        }

    monkeypatch.setattr(
        "src.processing.document_extraction.pytesseract.image_to_data", fake_image_to_data
    )

    result = extract_pdf_document(str(path))
    layout = result["metadata_candidates"]["layout_tables"]

    assert result["legal_text"].endswith("Texto OCR independente da prévia tabular.")
    assert layout["candidate_count"] == 1
    assert layout["candidates"][0]["page"] == 1
    assert layout["raster_image_pages_not_analyzed"] == []


def test_reused_ocr_can_create_only_bounded_raster_table_preview(tmp_path, monkeypatch):
    image = Image.new("RGB", (400, 240), "white")
    draw = ImageDraw.Draw(image)
    for y in (20, 70, 130, 200):
        draw.line((20, y, 380, y), fill="black", width=2)
    for x in (20, 120, 300, 380):
        draw.line((x, 20, x, 200), fill="black", width=2)
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    path = tmp_path / "reused-raster-table.pdf"
    document = fitz.open()
    page = document.new_page(width=200, height=120)
    page.insert_image(fitz.Rect(0, 0, 200, 120), stream=image_bytes.getvalue())
    document.save(path)
    document.close()

    def fake_image_to_data(rendered, **_kwargs):
        width, height = rendered.size
        return {
            "text": ["Cabeçalho", "Linha", "2%"],
            "left": [int(width * ratio) for ratio in (0.08, 0.35, 0.80)],
            "top": [int(height * ratio) for ratio in (0.18, 0.40, 0.40)],
            "width": [24] * 3,
            "height": [12] * 3,
            "conf": [90] * 3,
        }

    monkeypatch.setattr(
        "src.processing.document_extraction.pytesseract.image_to_data", fake_image_to_data
    )
    source_text = "OCR anterior verificado, preservado sem alteração."
    result = extract_pdf_document(
        str(path),
        max_ocr_pages=0,
        raster_table_pages_to_process={1},
        reusable_ocr_pages={1: (source_text, "source-extraction-hash")},
    )

    layout = result["metadata_candidates"]["layout_tables"]
    assert result["legal_text"].endswith(source_text)
    assert result["quality"]["ocr_pages_attempted"] == []
    assert result["quality"]["ocr_pages_reused"] == [1]
    assert layout["candidate_count"] == 1
    assert layout["raster_image_pages_not_analyzed"] == []


def test_extraction_flags_raster_pages_for_visual_table_review(tmp_path):
    path = tmp_path / "raster-page.pdf"
    image = Image.new("RGB", (120, 80), "white")
    image_bytes = BytesIO()
    image.save(image_bytes, format="PNG")
    document = fitz.open()
    page = document.new_page()
    page.insert_image(fitz.Rect(20, 20, 140, 100), stream=image_bytes.getvalue())
    document.save(path)
    document.close()

    result = extract_pdf_document(
        str(path),
        max_ocr_pages=0,
        ocr=lambda *_args, **_kwargs: "",
    )

    layout = result["metadata_candidates"]["layout_tables"]
    assert layout["raster_image_pages_not_analyzed"] == [1]
    assert "Ausência de candidatos não significa ausência de tabelas" in layout["detection_scope"]


def test_table_detector_failure_does_not_fail_pdf_text_extraction():
    class Page:
        @staticmethod
        def find_tables():
            raise RuntimeError("layout detector unavailable")

    assert extract_layout_table_candidate(Page(), 4) == []


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


def test_explicit_ocr_retry_can_process_unreadable_page_without_detected_image(tmp_path):
    path = tmp_path / "unreadable-vector-page.pdf"
    _make_pdf(path, [("", None)])
    calls = []

    def retry_ocr(_image, *, timeout):
        calls.append(timeout)
        return "Art. 7º Texto recuperado por OCR sob revisão humana."

    result = extract_pdf_document(
        str(path),
        max_ocr_pages=1,
        ocr_timeout_seconds=15,
        ocr_pages_to_process={1},
        ocr=retry_ocr,
    )

    assert calls == [15]
    assert result["complete"] is True
    assert result["quality"]["ocr_pages_attempted"] == [1]
    assert result["pages"][0]["method"] == "ocr"
    assert result["pages"][0]["reason"] == "explicit_ocr_retry"
    assert result["quality"]["ocr_text_is_not_certified_verbatim"] is True


def test_extraction_policy_revision_changes_fingerprint(tmp_path, monkeypatch):
    path = tmp_path / "policy-version.pdf"
    _make_pdf(path, [("Art. 1º Texto nativo.", None)])
    original = extract_pdf_document(str(path))
    monkeypatch.setitem(EXTRACTION_POLICY, "version", "normative-pdf-extraction-test-vnext")
    updated = extract_pdf_document(str(path))

    assert original["policy_fingerprint"] != updated["policy_fingerprint"]


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
    assert len(calls) == 1
    assert calls[0][:2] == ("por", "--psm 6")
    assert 0 < calls[0][2] <= 15.0
    assert 15.0 - calls[0][2] < 0.01


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
