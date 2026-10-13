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
    "version": "normative-pdf-extraction-v6",
    "ocr_useful_characters_below": 40,
    "ocr_replacement_control_ratio_above": 0.02,
    "ocr_timeout_seconds": 90,
    "ocr_psm_fallbacks": [6, 4, 11],
    "ocr_timeout_scope": "shared_per_page",
    "max_pages": 200,
    "text_version": "technical_text_v1",
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
        if page.get_images(full=True):
            return True
    except (AttributeError, RuntimeError, ValueError):
        pass
    try:
        return bool(page.get_image_info(xrefs=True))
    except (AttributeError, RuntimeError, ValueError):
        return False


def page_is_blank(page: Any, native_text: str, has_image: bool) -> bool:
    """Return true only when a page has no text or visible PDF objects."""
    if native_text.strip() or has_image:
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
            if has_visible_fill or has_visible_stroke:
                return False
        if list(page.annots() or ()):
            return False
        if page.get_links():
            return False
    except (AttributeError, RuntimeError, ValueError):
        # Uninspectable content must remain reviewable, not be silently skipped.
        return False
    return True


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
                            page_text = ocr(image, timeout=ocr_timeout_seconds)
                    except Exception as exc:  # OCR errors must not certify partial text.
                        method = "unreadable"
                        status = "timeout" if "timeout" in str(exc).casefold() else "failed"
                        reason = f"ocr_{status}"
                        page_text = ""

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
