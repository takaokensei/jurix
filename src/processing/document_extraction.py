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
from src.processing.legal_parser import (
    classify_closing_segments,
    extract_publication_metadata,
)

EXTRACTION_POLICY = {
    "version": "normative-pdf-extraction-v1",
    "ocr_useful_characters_below": 40,
    "ocr_replacement_control_ratio_above": 0.02,
    "ocr_timeout_seconds": 90,
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
    return pytesseract.image_to_string(
        image,
        lang="por",
        config="--psm 6",
        timeout=timeout,
    )


def extract_pdf_document(
    pdf_path: str,
    *,
    max_pages: int = 200,
    ocr_timeout_seconds: int = 90,
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
    }
    document = fitz.open(pdf_path)
    try:
        page_count = len(document)
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
            }

        pages: list[PageExtraction] = []
        raw_page_texts: list[str] = []
        for index in range(page_count):
            page_started = time.monotonic()
            page = document[index]
            raw_native = page.get_text("text") or ""
            has_image = page_has_image(page)
            run_ocr, reason = should_ocr_page(raw_native, has_image)
            ocr_attempted = False
            method, status, page_text = "native", "complete", raw_native
            if run_ocr:
                ocr_attempted = True
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
            source_map.append(
                {
                    "text_version": EXTRACTION_POLICY["text_version"],
                    "start": start,
                    "end": cursor,
                    "page": page_result.page,
                    "method": page_result.method,
                    "status": page_result.status,
                    "quote_hash": hashlib.sha256(page_result.text.encode("utf-8")).hexdigest(),
                }
            )
        technical_text = "".join(technical_parts)
        segments = classify_closing_segments(technical_text)
        epigraph = parse_initial_epigraphs([page.text for page in pages[:3]])
        publication_metadata = extract_publication_metadata(technical_text)
        unreadable = [page.page for page in pages if page.method == "unreadable"]
        policy_fingerprint = hashlib.sha256(
            json.dumps(run_policy, sort_keys=True).encode()
        ).hexdigest()
        extractor_version = f"pymupdf-{fitz.VersionBind}/pytesseract-{pytesseract.__version__}"
        extraction_hash = hashlib.sha256(technical_text.encode("utf-8")).hexdigest()
        complete = not unreadable and bool(technical_text.strip())
        return {
            "complete": complete,
            "needs_review": not complete or any(page.ocr_attempted for page in pages),
            "reason": "unreadable_pages" if unreadable else None,
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
            },
            "text_version": EXTRACTION_POLICY["text_version"],
            "policy_fingerprint": policy_fingerprint,
            "extractor_version": extractor_version,
            "extraction_sha256": extraction_hash,
            "duration_seconds": round(time.monotonic() - started, 6),
            "quality": {
                "page_methods": {
                    method: sum(page.method == method for page in pages)
                    for method in ("native", "ocr", "unreadable")
                },
                "unreadable_pages": unreadable,
                "ocr_pages_attempted": [page.page for page in pages if page.ocr_attempted],
                "ocr_text_is_not_certified_verbatim": any(
                    page.method == "ocr" for page in pages
                ),
            },
        }
    finally:
        document.close()
