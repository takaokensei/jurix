"""PDF rendering helpers for consolidated municipal legislation."""

from __future__ import annotations

import fitz

PAGE_WIDTH = 595
PAGE_HEIGHT = 842
BODY_RECT = fitz.Rect(48, 120, 547, 790)
BODY_FONT = "cour"
BODY_FONT_SIZE = 9.5
BODY_LINE_HEIGHT = 1.45


def _split_wide_word(word: str, font: fitz.Font, font_size: float, max_width: float) -> list[str]:
    """Split a single long token without exceeding the actual PDF font width."""
    parts = []
    remaining = word
    while remaining:
        low, high, best = 1, len(remaining), 0
        while low <= high:
            middle = (low + high) // 2
            if font.text_length(remaining[:middle], fontsize=font_size) <= max_width:
                best = middle
                low = middle + 1
            else:
                high = middle - 1
        if best == 0:
            raise ValueError("A font cannot render one character inside the PDF text box.")
        parts.append(remaining[:best])
        remaining = remaining[best:]
    return parts


def _wrap_body(text: str, max_width: float) -> list[str]:
    """Wrap source paragraphs using PyMuPDF's measured Courier font width."""
    font = fitz.Font(fontname=BODY_FONT)
    lines: list[str] = []
    for raw_line in text.splitlines():
        if not raw_line.strip():
            lines.append("")
            continue
        wrapped_line = ""
        for raw_word in raw_line.split():
            words = (
                _split_wide_word(raw_word, font, BODY_FONT_SIZE, max_width)
                if font.text_length(raw_word, fontsize=BODY_FONT_SIZE) > max_width
                else [raw_word]
            )
            for word in words:
                candidate = f"{wrapped_line} {word}" if wrapped_line else word
                if font.text_length(candidate, fontsize=BODY_FONT_SIZE) <= max_width:
                    wrapped_line = candidate
                else:
                    lines.append(wrapped_line)
                    wrapped_line = word
        if wrapped_line:
            lines.append(wrapped_line)
    return lines or [""]


def _add_page_header(page: fitz.Page, title: str) -> None:
    page.insert_text(
        (48, 48), "JURIX · NORMA CONSOLIDADA", fontsize=9, color=(0.18, 0.43, 0.78)
    )
    page.insert_text((48, 75), title, fontsize=16, fontname="hebo", color=(0.06, 0.10, 0.18))
    page.insert_text(
        (48, 94), "Exportação do texto consolidado", fontsize=9, color=(0.35, 0.40, 0.48)
    )


def build_consolidated_norma_pdf(title: str, body: str) -> bytes:
    """Paginate all legal text and fail loudly if even one line cannot fit."""
    document = fitz.open()
    lines = _wrap_body(body, BODY_RECT.width)
    line_height = BODY_FONT_SIZE * BODY_LINE_HEIGHT
    page_capacity = max(1, int(BODY_RECT.height // line_height))
    offset = 0
    page_number = 1

    while offset < len(lines):
        end = min(offset + page_capacity, len(lines))
        page = None
        while end > offset:
            candidate = document.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
            _add_page_header(candidate, title)
            remaining_height = candidate.insert_textbox(
                BODY_RECT,
                "\n".join(lines[offset:end]),
                fontsize=BODY_FONT_SIZE,
                lineheight=BODY_LINE_HEIGHT,
                fontname=BODY_FONT,
                color=(0.10, 0.12, 0.16),
            )
            if remaining_height >= 0:
                page = candidate
                break
            document.delete_page(-1)
            end -= 1

        if page is None:
            document.close()
            raise ValueError("A legal text line could not fit on a consolidated PDF page.")

        page.insert_text(
            (48, 818),
            f"Fonte oficial: SAPL · Página {page_number}",
            fontsize=8,
            color=(0.40, 0.44, 0.50),
        )
        offset = end
        page_number += 1

    payload = document.tobytes(garbage=4, deflate=True)
    document.close()
    return payload
