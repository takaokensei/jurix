"""Page-oriented, auditable text extraction for normative PDF documents."""

from __future__ import annotations

import hashlib
import io
import json
import time
import unicodedata
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Any

import fitz
import pytesseract
from PIL import Image

from src.processing.document_metadata import parse_initial_epigraphs
from src.processing.gazette_act_candidates import find_gazette_act_candidates
from src.processing.legal_parser import (
    classify_closing_segments,
    extract_publication_metadata,
)

EXTRACTION_POLICY = {
    "version": "normative-pdf-extraction-v13",
    "blank_page_visibility_check": "visible_text_and_footer_rule_v1",
    "ocr_useful_characters_below": 40,
    "ocr_replacement_control_ratio_above": 0.02,
    "ocr_timeout_seconds": 90,
    "ocr_psm_fallbacks": [6, 4, 11],
    "ocr_timeout_scope": "shared_per_page",
    "max_pages": 200,
    "text_version": "technical_text_v1",
    "layout_table_candidates": True,
    "max_layout_tables": 12,
    "max_layout_table_rows": 40,
    "max_layout_table_columns": 16,
    "max_layout_table_chars": 24000,
    "raster_table_projection_threshold": 150,
    "raster_table_ocr_psm": 4,
}


@dataclass(frozen=True)
class PageExtraction:
    page: int
    method: str
    text: str
    useful_characters: int
    replacement_control_ratio: float
    has_image: bool
    ocr_attempted: bool
    duration_seconds: float
    status: str
    reason: str | None = None


def normalize_extracted_text(text: str) -> str:
    """Normalize line endings and unsafe controls without rewriting legal words."""
    text = (text or "").replace("\r\n", "\n").replace("\r", "\n")
    return "".join(
        char
        for char in text
        if char in "\n\t" or unicodedata.category(char) not in {"Cc", "Cs"}
    ).strip()


def text_quality(text: str) -> tuple[int, float]:
    useful = sum(char.isalnum() for char in text)
    suspicious = sum(
        char == "\ufffd"
        or (unicodedata.category(char) == "Cc" and char not in "\n\r\t")
        for char in text
    )
    return useful, suspicious / max(1, len(text))


def page_has_image(page: Any) -> bool:
    """Detect placed and inline images; inaccessible image metadata is not fatal."""
    try:
        image_info = page.get_image_info(xrefs=True)
    except (AttributeError, RuntimeError, TypeError, ValueError):
        image_info = None
    if image_info is not None:
        # get_images() also lists orphaned XObjects that are not painted on the
        # page. Only use that resource inventory when placement info is absent.
        return bool(image_info)
    try:
        return bool(page.get_images(full=True))
    except (AttributeError, RuntimeError, TypeError, ValueError):
        return False


def _native_text_has_visible_ink(page: Any) -> bool | None:
    """Check short native text spans by rendering their bounds; None means unknown."""
    try:
        blocks = page.get_text("dict").get("blocks", ())
        found_text_span = False
        for block in blocks:
            for line in block.get("lines", ()):
                for span in line.get("spans", ()):
                    if not (span.get("text") or "").strip():
                        continue
                    found_text_span = True
                    bounds = fitz.Rect(span["bbox"]) & page.rect
                    if bounds.is_empty or bounds.is_infinite:
                        return None
                    pixmap = page.get_pixmap(
                        matrix=fitz.Matrix(2, 2),
                        clip=bounds,
                        colorspace=fitz.csGRAY,
                        alpha=False,
                    )
                    if sum(value < 250 for value in pixmap.samples) >= 2:
                        return True
        return False if found_text_span else None
    except (AttributeError, KeyError, RuntimeError, TypeError, ValueError):
        # If visibility cannot be established, retain the page for human review.
        return None


def _is_thin_light_footer_rule(drawing: dict[str, Any], page: Any) -> bool:
    """Recognize only a single pale, thin horizontal rule in the bottom margin."""
    try:
        color = drawing.get("color")
        if (
            drawing.get("fill") is not None
            or color is None
            or len(color) < 3
            or min(color[:3]) < 0.65
            or max(color[:3]) > 0.97
            or (drawing.get("stroke_opacity") or 0) <= 0
            or float(drawing.get("width") or 0) > 2
        ):
            return False
        items = drawing.get("items") or ()
        if len(items) != 1 or items[0][0] != "l":
            return False
        start, end = items[0][1], items[0][2]
        page_rect = page.rect
        return (
            abs(start.y - end.y) <= 0.5
            and min(start.y, end.y) >= page_rect.y0 + page_rect.height * 0.88
            and abs(end.x - start.x) >= page_rect.width * 0.70
        )
    except (AttributeError, IndexError, TypeError, ValueError):
        return False


def page_is_blank(page: Any, native_text: str, has_image: bool) -> bool:
    """Return true only when a page has no legible text or meaningful PDF objects."""
    if has_image:
        return False
    if native_text.strip():
        if text_quality(native_text)[0] >= EXTRACTION_POLICY["ocr_useful_characters_below"]:
            return False
        text_is_visible = _native_text_has_visible_ink(page)
        if text_is_visible is not False:
            return False
    try:
        for drawing in page.get_drawings():
            fill = drawing.get("fill")
            color = drawing.get("color")
            fill_opacity = drawing.get("fill_opacity", 1.0)
            stroke_opacity = drawing.get("stroke_opacity", 1.0)
            has_visible_fill = (
                fill is not None
                and (fill_opacity is None or fill_opacity > 0)
                and any(channel < 0.98 for channel in fill)
            )
            has_visible_stroke = (
                color is not None
                and (stroke_opacity is None or stroke_opacity > 0)
                and any(channel < 0.98 for channel in color)
            )
            if has_visible_fill or (
                has_visible_stroke and not _is_thin_light_footer_rule(drawing, page)
            ):
                return False
        if list(page.annots() or ()):
            return False
        if page.get_links():
            return False
    except (AttributeError, RuntimeError, ValueError):
        # Uninspectable content must remain reviewable, not be silently skipped.
        return False
    return True


def extract_layout_table_candidate(page: Any, page_number: int) -> list[dict[str, Any]]:
    """Return bounded, unreviewed table-layout candidates without changing legal text."""
    find_tables = getattr(page, "find_tables", None)
    if not callable(find_tables):
        return []
    try:
        found = find_tables()
        tables = getattr(found, "tables", ()) or ()
    except Exception:
        # Layout detection is supplemental. A detector failure must never turn a
        # readable PDF into a failed text extraction or imply no table exists.
        return []

    candidates = []
    remaining_chars = EXTRACTION_POLICY["max_layout_table_chars"]
    for table in tables[: EXTRACTION_POLICY["max_layout_tables"]]:
        try:
            extracted_rows = table.extract()
        except Exception:
            continue
        if not isinstance(extracted_rows, list) or len(extracted_rows) < 2:
            continue
        column_count = max(
            (len(row) for row in extracted_rows if isinstance(row, list | tuple)),
            default=0,
        )
        if column_count < 2:
            continue
        row_limit = EXTRACTION_POLICY["max_layout_table_rows"]
        column_limit = EXTRACTION_POLICY["max_layout_table_columns"]
        display_columns = min(column_count, column_limit)
        rows = []
        was_truncated = len(extracted_rows) > row_limit or column_count > column_limit
        for row in extracted_rows[:row_limit]:
            if not isinstance(row, list | tuple):
                continue
            normalized_row = []
            for cell in row[:display_columns]:
                value = str(cell or "").strip()
                if remaining_chars <= 0:
                    was_truncated = was_truncated or bool(value)
                    value = ""
                else:
                    was_truncated = was_truncated or len(value) > remaining_chars
                    value = value[:remaining_chars]
                    remaining_chars -= len(value)
                normalized_row.append(value)
            normalized_row.extend([""] * (display_columns - len(normalized_row)))
            rows.append(normalized_row)
        if len(rows) < 2:
            continue
        cell_count = sum(len(row) for row in rows)
        nonempty_count = sum(bool(cell) for row in rows for cell in row)
        bbox = getattr(table, "bbox", None)
        try:
            bounds = [round(float(value), 2) for value in bbox[:4]]
        except (TypeError, ValueError, IndexError):
            bounds = []
        candidates.append(
            {
                "page": page_number,
                "status": "unreviewed_candidate",
                "detector": "pymupdf_find_tables",
                "bbox": bounds,
                "row_count": len(extracted_rows),
                "column_count": column_count,
                "cell_occupancy": round(nonempty_count / max(1, cell_count), 4),
                "rows": rows,
                "truncated": was_truncated,
                "review_note": (
                    "Candidato geométrico; compare células, alinhamento e conteúdo com o PDF. "
                    "Não integra o texto legal nem comprova fidelidade."
                ),
            }
        )
        if remaining_chars <= 0:
            break
    return candidates


def _projection_runs(values: list[int], *, max_gap: int = 3) -> list[tuple[int, int]]:
    runs: list[list[int]] = []
    for value in values:
        if not runs or value > runs[-1][-1] + max_gap:
            runs.append([value])
        else:
            runs[-1].append(value)
    return [(run[0], run[-1]) for run in runs if len(run) >= 2]


def _raster_grid_bounds(image: Image.Image) -> tuple[list[int], list[int]]:
    """Find strong, repeated raster rules; this only locates cells, not their text."""
    grayscale = image.convert("L")
    threshold = EXTRACTION_POLICY["raster_table_projection_threshold"]
    binary = grayscale.point(lambda value: 0 if value <= threshold else 255)
    width, height = binary.size
    pixels = binary.tobytes()

    horizontal_rows = [
        y
        for y in range(height)
        if pixels[y * width : (y + 1) * width].count(0) / max(1, width) >= 0.45
    ]
    horizontal = _projection_runs(horizontal_rows)

    transposed = binary.transpose(Image.Transpose.ROTATE_90)
    transposed_width = height
    transposed_pixels = transposed.tobytes()
    vertical_columns = sorted(
        width - 1 - x
        for x in range(width)
        if transposed_pixels[x * transposed_width : (x + 1) * transposed_width].count(0)
        / max(1, height)
        >= 0.25
    )
    vertical_runs = _projection_runs(vertical_columns, max_gap=4)
    vertical_lines: list[tuple[int, int, int]] = []
    for left, right in vertical_runs:
        dark_rows = []
        for y in range(height):
            row = pixels[y * width + left : y * width + right + 1]
            if row.count(0) / max(1, right - left + 1) >= 0.5:
                dark_rows.append(y)
        spans = _projection_runs(dark_rows, max_gap=10)
        if spans:
            top, bottom = max(spans, key=lambda span: span[1] - span[0])
            if bottom - top >= height * 0.18:
                vertical_lines.append(((left + right) // 2, top, bottom))

    best_group: list[tuple[int, int, int]] = []
    best_overlap: tuple[int, int] | None = None
    for _x, top, bottom in vertical_lines:
        group = [
            line
            for line in vertical_lines
            if min(bottom, line[2]) - max(top, line[1]) >= height * 0.12
        ]
        overlap = (
            max((line[1] for line in group), default=0),
            min((line[2] for line in group), default=0),
        )
        if len(group) > len(best_group) or (
            len(group) == len(best_group)
            and overlap[1] - overlap[0] > (best_overlap[1] - best_overlap[0] if best_overlap else 0)
        ):
            best_group, best_overlap = group, overlap

    if len(best_group) < 3 or best_overlap is None or best_overlap[1] <= best_overlap[0]:
        return [], []
    x_lines = sorted({line[0] for line in best_group})
    table_left, table_right = x_lines[0], x_lines[-1]
    table_width = table_right - table_left
    if table_width < width * 0.2:
        return [], []
    y_lines = [
        (top + bottom) // 2
        for top, bottom in horizontal
        if best_overlap[0] - 8 <= (top + bottom) // 2 <= best_overlap[1] + 8
        and pixels[((top + bottom) // 2) * width + table_left : ((top + bottom) // 2) * width + table_right + 1].count(0)
        / max(1, table_width)
        >= 0.65
    ]
    y_lines = sorted(set(y_lines))
    return (x_lines, y_lines) if len(y_lines) >= 3 else ([], [])


def extract_raster_table_candidate(
    image: Image.Image,
    page_number: int,
    ocr_data: dict[str, Any],
    *,
    grid: tuple[list[int], list[int]] | None = None,
) -> list[dict[str, Any]]:
    """Build a review-only table candidate from raster rules and word boxes."""
    x_lines, y_lines = grid if grid is not None else _raster_grid_bounds(image)
    if len(x_lines) < 3 or len(y_lines) < 3:
        return []

    row_count, column_count = len(y_lines) - 1, len(x_lines) - 1
    row_limit = EXTRACTION_POLICY["max_layout_table_rows"]
    column_limit = EXTRACTION_POLICY["max_layout_table_columns"]
    display_rows = min(row_count, row_limit)
    display_columns = min(column_count, column_limit)
    cells: list[list[list[tuple[int, int, str]]]] = [
        [[] for _ in range(display_columns)] for _ in range(display_rows)
    ]
    for index, raw_text in enumerate(ocr_data.get("text", [])):
        text = str(raw_text or "").strip()
        try:
            left = int(ocr_data["left"][index])
            top = int(ocr_data["top"][index])
            width = int(ocr_data["width"][index])
            height = int(ocr_data["height"][index])
            confidence = float(ocr_data.get("conf", [100] * len(ocr_data["text"]))[index])
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        center_x, center_y = left + width / 2, top + height / 2
        if not text or confidence < 0 or not (x_lines[0] < center_x < x_lines[-1]):
            continue
        row_index = next(
            (row for row in range(display_rows) if y_lines[row] < center_y < y_lines[row + 1]),
            None,
        )
        column_index = next(
            (
                column
                for column in range(display_columns)
                if x_lines[column] < center_x < x_lines[column + 1]
            ),
            None,
        )
        if row_index is not None and column_index is not None:
            cells[row_index][column_index].append((top, left, text))

    nonempty_source_cells = sum(bool(cell) for row in cells for cell in row)
    occupancy = nonempty_source_cells / max(1, display_rows * display_columns)
    remaining_chars = EXTRACTION_POLICY["max_layout_table_chars"]
    was_truncated = row_count > row_limit or column_count > column_limit
    rows: list[list[str]] = []
    for row in cells:
        normalized_row = []
        for cell in row:
            value = " ".join(word for _top, _left, word in sorted(cell)).strip()
            if remaining_chars <= 0:
                was_truncated = was_truncated or bool(value)
                value = ""
            else:
                was_truncated = was_truncated or len(value) > remaining_chars
                value = value[:remaining_chars]
                remaining_chars -= len(value)
            normalized_row.append(value)
        rows.append(normalized_row)
    if nonempty_source_cells < 3 or occupancy < 0.1:
        return []
    return [
        {
            "page": page_number,
            "status": "unreviewed_candidate",
            "detector": "raster_grid+tesseract_word_boxes",
            "bbox_pixels": [x_lines[0], y_lines[0], x_lines[-1], y_lines[-1]],
            "row_count": row_count,
            "column_count": column_count,
            "cell_occupancy": round(occupancy, 4),
            "rows": rows,
            "truncated": was_truncated,
            "review_note": (
                "Prévia de OCR segmentada por linhas raster; confira cada célula no PDF. "
                "Não integra o texto legal, não é citação certificada nem substitui revisão humana."
            ),
        }
    ]


def _extract_raster_table_candidate_from_image(
    image: Image.Image,
    page_number: int,
    *,
    timeout: float,
    grid: tuple[list[int], list[int]] | None = None,
) -> list[dict[str, Any]]:
    grid = grid if grid is not None else _raster_grid_bounds(image)
    if not grid[0] or not grid[1] or timeout <= 0:
        return []
    ocr_data = pytesseract.image_to_data(
        image,
        lang="por",
        config=f"--psm {EXTRACTION_POLICY['raster_table_ocr_psm']}",
        output_type=pytesseract.Output.DICT,
        timeout=timeout,
    )
    return extract_raster_table_candidate(image, page_number, ocr_data, grid=grid)


def should_ocr_page(text: str, has_image: bool) -> tuple[bool, str]:
    useful, suspicious_ratio = text_quality(text)
    if not has_image:
        return False, "no_image_native_text_preserved"
    if useful < EXTRACTION_POLICY["ocr_useful_characters_below"]:
        return True, "image_with_insufficient_native_text"
    if suspicious_ratio > EXTRACTION_POLICY["ocr_replacement_control_ratio_above"]:
        return True, "image_with_corrupt_native_text"
    return False, "native_text_sufficient"


def _default_ocr(image: Image.Image, *, timeout: int) -> str:
    deadline = time.monotonic() + max(0.0, float(timeout))
    candidates: list[tuple[int, float, int, str]] = []
    failures: list[Exception] = []
    psm_values = EXTRACTION_POLICY["ocr_psm_fallbacks"]

    for index, psm in enumerate(psm_values):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        attempts_left = len(psm_values) - index
        call_timeout = remaining if index == 0 else remaining / attempts_left
        try:
            text = pytesseract.image_to_string(
                image,
                lang="por",
                config=f"--psm {psm}",
                timeout=call_timeout,
            )
        except Exception as exc:
            failures.append(exc)
            if "timeout" in str(exc).casefold():
                break
            continue

        useful, suspicious_ratio = text_quality(text)
        normalized_length = len(normalize_extracted_text(text))
        candidates.append((useful, -suspicious_ratio, normalized_length, text))
        # Preserve the fast path for a readable first pass. Alternative page
        # segmentation is only attempted when the primary OCR result is weak.
        if index == 0 and useful >= EXTRACTION_POLICY["ocr_useful_characters_below"] and (
            suspicious_ratio <= EXTRACTION_POLICY["ocr_replacement_control_ratio_above"]
        ):
            return text

    if candidates:
        return max(candidates, key=lambda candidate: candidate[:3])[3]
    if failures:
        raise failures[-1]
    return ""


def extract_pdf_document(
    pdf_path: str,
    *,
    max_pages: int = 200,
    ocr_timeout_seconds: int = 90,
    max_ocr_pages: int | None = None,
    ocr_pages_to_process: set[int] | None = None,
    raster_table_pages_to_process: set[int] | None = None,
    reusable_ocr_pages: dict[int, tuple[str, str]] | None = None,
    ocr: Callable[..., str] = _default_ocr,
) -> dict[str, Any]:
    """Extract one page at a time and return versioned text and provenance spans.

    Span offsets address only ``technical_text_v1``; they are not PDF byte or
    visual coordinates. An OCR timeout leaves the document incomplete.
    """
    started = time.monotonic()
    run_policy = {
        **EXTRACTION_POLICY,
        "max_pages": max_pages,
        "ocr_timeout_seconds": ocr_timeout_seconds,
        "max_ocr_pages": max_ocr_pages,
    }
    if ocr_pages_to_process is not None:
        if any(not isinstance(page, int) or page < 1 for page in ocr_pages_to_process):
            raise ValueError("OCR page selection must contain positive one-based page numbers")
        run_policy["ocr_pages_to_process"] = sorted(ocr_pages_to_process)
    if raster_table_pages_to_process is not None:
        if (
            len(raster_table_pages_to_process) > 10
            or any(
                not isinstance(page, int) or page < 1
                for page in raster_table_pages_to_process
            )
        ):
            raise ValueError("Raster table page selection must contain up to 10 positive pages")
        run_policy["raster_table_pages_to_process"] = sorted(raster_table_pages_to_process)
    reusable_ocr_pages = reusable_ocr_pages or {}
    if reusable_ocr_pages:
        if any(
            not isinstance(page, int)
            or page < 1
            or not isinstance(value, tuple)
            or len(value) != 2
            or not isinstance(value[0], str)
            or not isinstance(value[1], str)
            or not value[1]
            for page, value in reusable_ocr_pages.items()
        ):
            raise ValueError("Reusable OCR pages require text and an extraction hash")
        run_policy["reusable_ocr_sources"] = sorted(
            {value[1] for value in reusable_ocr_pages.values()}
        )
    extractor_version = f"pymupdf-{fitz.VersionBind}/pytesseract-{pytesseract.__version__}"
    try:
        document = fitz.open(pdf_path)
    except fitz.FileDataError as exc:
        empty_hash = hashlib.sha256(b"").hexdigest()
        return {
            "complete": False,
            "needs_review": True,
            "reason": "unreadable_pdf",
            "page_count": 0,
            "pages": [],
            "raw_text": "",
            "technical_text": "",
            "legal_text": "",
            "source_map": [],
            "segments": [],
            "metadata_candidates": {},
            "text_version": EXTRACTION_POLICY["text_version"],
            "policy_fingerprint": hashlib.sha256(
                json.dumps(run_policy, sort_keys=True).encode()
            ).hexdigest(),
            "extractor_version": extractor_version,
            "extraction_sha256": empty_hash,
            "duration_seconds": round(time.monotonic() - started, 6),
            "quality": {
                "page_methods": {"native": 0, "ocr": 0, "unreadable": 0},
                "unreadable_pages": [],
                "pages_not_processed": 0,
                "ocr_pages_attempted": [],
                "ocr_budget_skipped_pages": [],
                "ocr_text_is_not_certified_verbatim": False,
                "extraction_error": type(exc).__name__,
            },
        }
    try:
        page_count = len(document)
        if any(page > page_count for page in ocr_pages_to_process or set()):
            raise ValueError("OCR page selection exceeds the PDF page count")
        if any(page > page_count for page in raster_table_pages_to_process or set()):
            raise ValueError("Raster table page selection exceeds the PDF page count")
        if any(page > page_count for page in reusable_ocr_pages):
            raise ValueError("Reusable OCR page exceeds the PDF page count")
        if page_count > max_pages:
            return {
                "complete": False,
                "needs_review": True,
                "reason": "page_limit_exceeded",
                "page_count": page_count,
                "pages": [],
                "raw_text": "",
                "technical_text": "",
                "legal_text": "",
                "source_map": [],
                "segments": [],
                "metadata_candidates": {},
                "text_version": EXTRACTION_POLICY["text_version"],
                "policy_fingerprint": hashlib.sha256(
                    json.dumps(run_policy, sort_keys=True).encode()
                ).hexdigest(),
                "extractor_version": extractor_version,
                "extraction_sha256": hashlib.sha256(b"").hexdigest(),
                "duration_seconds": round(time.monotonic() - started, 6),
                "quality": {
                    "page_methods": {"native": 0, "ocr": 0, "unreadable": 0},
                    "unreadable_pages": [],
                    "pages_not_processed": page_count,
                    "ocr_pages_attempted": [],
                    "ocr_budget_skipped_pages": [],
                    "ocr_text_is_not_certified_verbatim": False,
                },
            }

        pages: list[PageExtraction] = []
        layout_table_candidates: list[dict[str, Any]] = []
        raster_image_pages_not_analyzed_for_tables: list[int] = []
        raw_page_texts: list[str] = []
        ocr_pages_attempted = 0
        ocr_pages_reused: list[int] = []
        ocr_budget_skipped_pages: list[int] = []
        reused_source_by_page: dict[int, str] = {}
        for index in range(page_count):
            page_started = time.monotonic()
            page = document[index]
            raw_native = page.get_text("text") or ""
            has_image = page_has_image(page)
            page_number = index + 1
            if (
                raster_table_pages_to_process is not None
                and page_number in raster_table_pages_to_process
                and not has_image
            ):
                raise ValueError("Raster table page selection includes a page without an image")
            if (
                EXTRACTION_POLICY["layout_table_candidates"]
                and len(layout_table_candidates) < EXTRACTION_POLICY["max_layout_tables"]
            ):
                layout_table_candidates.extend(
                    extract_layout_table_candidate(page, page_number)[
                        : EXTRACTION_POLICY["max_layout_tables"] - len(layout_table_candidates)
                    ]
                )
            blank = page_is_blank(page, raw_native, has_image)
            run_ocr, reason = should_ocr_page(raw_native, has_image)
            explicitly_selected = (
                ocr_pages_to_process is not None and page_number in ocr_pages_to_process
            )
            if blank and not explicitly_selected:
                method, status, page_text = "blank", "blank", ""
                reason = "page_has_no_text_or_visible_objects"
            elif explicitly_selected:
                # A reviewer-requested retry must be able to recover scans that
                # PyMuPDF does not expose as image XObjects (for example, vector
                # outlines or malformed embedded text). Automatic extraction
                # still follows should_ocr_page(); only a bounded explicit retry
                # overrides that detection decision.
                run_ocr = True
                reason = "explicit_ocr_retry"
            ocr_attempted = False
            if not blank or explicitly_selected:
                method, status, page_text = "native", "complete", raw_native
            if run_ocr and (not blank or explicitly_selected):
                reusable_page = reusable_ocr_pages.get(page_number)
                if reusable_page and normalize_extracted_text(reusable_page[0]):
                    page_text = reusable_page[0]
                    method = "ocr"
                    status = "reused"
                    ocr_pages_reused.append(page_number)
                    reused_source_by_page[page_number] = reusable_page[1]
                    if (
                        has_image
                        and raster_table_pages_to_process is not None
                        and page_number in raster_table_pages_to_process
                        and len(layout_table_candidates)
                        < EXTRACTION_POLICY["max_layout_tables"]
                    ):
                        pixmap = page.get_pixmap(dpi=300)
                        try:
                            image_bytes = pixmap.tobytes("png")
                        finally:
                            pixmap = None
                        try:
                            with Image.open(io.BytesIO(image_bytes)) as image:
                                layout_table_candidates.extend(
                                    _extract_raster_table_candidate_from_image(
                                        image,
                                        page_number,
                                        timeout=ocr_timeout_seconds,
                                    )[
                                        : EXTRACTION_POLICY["max_layout_tables"]
                                        - len(layout_table_candidates)
                                    ]
                                )
                        except Exception:
                            # The reused text remains valid; failed layout OCR stays
                            # explicitly unreviewed and cannot invalidate that text.
                            pass
                elif (
                    ocr_pages_to_process is not None
                    and page_number not in ocr_pages_to_process
                ):
                    method = "unreadable"
                    status = "ocr_budget_skipped"
                    reason = "ocr_page_not_selected_for_batch"
                    ocr_budget_skipped_pages.append(page_number)
                    page_text = raw_native
                elif max_ocr_pages is not None and ocr_pages_attempted >= max_ocr_pages:
                    method = "unreadable"
                    status = "ocr_budget_skipped"
                    reason = "ocr_document_page_budget_exceeded"
                    ocr_budget_skipped_pages.append(page_number)
                    page_text = raw_native
                else:
                    ocr_attempted = True
                    ocr_pages_attempted += 1
                    method = "ocr"
                    pixmap = page.get_pixmap(dpi=300)
                    try:
                        image_bytes = pixmap.tobytes("png")
                    finally:
                        pixmap = None
                    try:
                        with Image.open(io.BytesIO(image_bytes)) as image:
                            raster_grid = (
                                _raster_grid_bounds(image)
                                if has_image
                                and ocr is _default_ocr
                                and len(layout_table_candidates)
                                < EXTRACTION_POLICY["max_layout_tables"]
                                else ([], [])
                            )
                            ocr_started = time.monotonic()
                            page_text = ocr(image, timeout=ocr_timeout_seconds)
                            if raster_grid[0] and raster_grid[1] and ocr is _default_ocr:
                                remaining_timeout = ocr_timeout_seconds - (
                                    time.monotonic() - ocr_started
                                )
                                if remaining_timeout > 0.1:
                                    try:
                                        layout_table_candidates.extend(
                                            _extract_raster_table_candidate_from_image(
                                            image,
                                                page_number,
                                                timeout=remaining_timeout,
                                                grid=raster_grid,
                                            )[
                                                : EXTRACTION_POLICY["max_layout_tables"]
                                                - len(layout_table_candidates)
                                            ]
                                        )
                                    except Exception:
                                        # OCR layout is supplemental. Preserve text extraction
                                        # and surface the page for visual review if it fails.
                                        pass
                    except Exception as exc:  # OCR errors must not certify partial text.
                        method = "unreadable"
                        status = "timeout" if "timeout" in str(exc).casefold() else "failed"
                        reason = f"ocr_{status}"
                        page_text = ""

            if has_image and not any(
                candidate.get("page") == page_number
                and candidate.get("detector") == "raster_grid+tesseract_word_boxes"
                for candidate in layout_table_candidates
            ):
                # find_tables inspects PDF text/vector geometry, not raster pixels.
                # Keep undetected scans visible to reviewers rather than implying
                # that no table exists because the structural detector found none.
                raster_image_pages_not_analyzed_for_tables.append(page_number)

            raw_page_texts.append(page_text or raw_native)
            normalized = normalize_extracted_text(page_text)
            useful, suspicious_ratio = text_quality(page_text)
            if method == "native" and not normalized:
                method = "unreadable"
                status = "empty_native_text"
                reason = "no_image_native_text_empty"
            elif method == "ocr" and not normalized:
                method = "unreadable"
                status = "empty_ocr_text"
                reason = "ocr_empty_text"
            pages.append(
                PageExtraction(
                    page=index + 1,
                    method=method,
                    text=normalized,
                    useful_characters=useful,
                    replacement_control_ratio=round(suspicious_ratio, 6),
                    has_image=has_image,
                    ocr_attempted=ocr_attempted,
                    duration_seconds=round(time.monotonic() - page_started, 6),
                    status=status,
                    reason=reason,
                )
            )
        technical_parts: list[str] = []
        source_map: list[dict[str, Any]] = []
        cursor = 0
        for page_result in pages:
            if not page_result.text:
                continue
            marker = f"--- Página {page_result.page} ---\n"
            part = marker + page_result.text
            if technical_parts:
                technical_parts.append("\n\n")
                cursor += 2
            start = cursor + len(marker)
            technical_parts.append(part)
            cursor += len(part)
            page_span = {
                "text_version": EXTRACTION_POLICY["text_version"],
                "start": start,
                "end": cursor,
                "page": page_result.page,
                "method": page_result.method,
                "status": page_result.status,
                "quote_hash": hashlib.sha256(page_result.text.encode("utf-8")).hexdigest(),
            }
            if page_result.page in reused_source_by_page:
                page_span["reused_from_extraction_sha256"] = reused_source_by_page[
                    page_result.page
                ]
            source_map.append(page_span)
        technical_text = "".join(technical_parts)
        segments = classify_closing_segments(technical_text)
        epigraph = parse_initial_epigraphs([page.text for page in pages[:3]])
        unreadable = [page.page for page in pages if page.method == "unreadable"]
        act_boundaries = find_gazette_act_candidates(
            (page.text for page in pages), max_pages=max_pages
        ).as_dict()
        act_boundaries["source_text_complete"] = not unreadable and bool(technical_text.strip())
        publication_metadata = extract_publication_metadata(technical_text)
        policy_fingerprint = hashlib.sha256(
            json.dumps(run_policy, sort_keys=True).encode()
        ).hexdigest()
        extractor_version = f"pymupdf-{fitz.VersionBind}/pytesseract-{pytesseract.__version__}"
        extraction_hash = hashlib.sha256(technical_text.encode("utf-8")).hexdigest()
        complete = not unreadable and bool(technical_text.strip())
        return {
            "complete": complete,
            "needs_review": not complete or any(page.ocr_attempted for page in pages),
            "reason": (
                "ocr_document_page_budget_exceeded"
                if ocr_budget_skipped_pages
                else "unreadable_pages" if unreadable else None
            ),
            "page_count": page_count,
            "pages": [asdict(page) for page in pages],
            "raw_text": "\f".join(raw_page_texts),
            "technical_text": technical_text,
            # Kept at the exact same offsets as technical_text; parser classifies
            # colophon/annex segments before device extraction.
            "legal_text": technical_text,
            "source_map": source_map,
            "segments": segments,
            "metadata_candidates": {
                "epigraph": asdict(epigraph),
                "publication": {
                    **publication_metadata,
                    "data_publicacao": (
                        publication_metadata["data_publicacao"].isoformat()
                        if publication_metadata["data_publicacao"]
                        else None
                    ),
                },
                "gazette_act_boundaries": act_boundaries,
                "layout_tables": {
                    "status": (
                        "unreviewed_candidates"
                        if layout_table_candidates
                        else "no_candidates_detected"
                    ),
                    "candidate_count": len(layout_table_candidates),
                    "detection_scope": (
                        "Geometria textual detectável no PDF; tabelas em imagem/OCR podem não ser "
                        "detectadas. Ausência de candidatos não significa ausência de tabelas."
                    ),
                    "raster_image_pages_not_analyzed": raster_image_pages_not_analyzed_for_tables,
                    "candidates": layout_table_candidates,
                },
            },
            "text_version": EXTRACTION_POLICY["text_version"],
            "policy_fingerprint": policy_fingerprint,
            "extractor_version": extractor_version,
            "extraction_sha256": extraction_hash,
            "duration_seconds": round(time.monotonic() - started, 6),
            "quality": {
                "page_methods": {
                    method: sum(page.method == method for page in pages)
                    for method in ("native", "ocr", "blank", "unreadable")
                },
                "blank_pages": [page.page for page in pages if page.method == "blank"],
                "unreadable_pages": unreadable,
                "ocr_pages_attempted": [page.page for page in pages if page.ocr_attempted],
                "ocr_pages_reused": ocr_pages_reused,
                "ocr_budget_skipped_pages": ocr_budget_skipped_pages,
                "ocr_text_is_not_certified_verbatim": any(
                    page.method == "ocr" for page in pages
                ),
            },
        }
    finally:
        document.close()
