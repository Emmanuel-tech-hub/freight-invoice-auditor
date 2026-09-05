"""Page-aware PDF extraction: text, tables, and a best-effort OCR fallback
for image-only (scanned) pages. This is the shared foundation both the
contract and invoice extractors build on, so every extracted value can cite
its source page.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import pdfplumber

MIN_TEXT_CHARS_BEFORE_OCR = 20


@dataclass
class PageContent:
    page_number: int  # 1-indexed
    text: str
    tables: list[list[list[str | None]]] = field(default_factory=list)
    from_ocr: bool = False


@dataclass
class PdfSource:
    pages: list[PageContent]
    ocr_attempted: bool = False
    ocr_used: bool = False
    ocr_unavailable: bool = False
    # ocr_unavailable is True only if OCR was attempted (a page had ~no
    # extractable text) and failed because the environment lacks the
    # tesseract/Pillow support needed to run it - not because a page was
    # legitimately blank.

    @property
    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)

    @property
    def has_meaningful_text(self) -> bool:
        return len(self.full_text.strip()) >= 40


def _try_ocr_page(page) -> tuple[str, bool]:
    """Best-effort OCR for one page. Returns (text, available) - available is
    False only when OCR itself couldn't run here (missing pytesseract or the
    system tesseract binary), not when it ran and found nothing.
    """
    try:
        import pytesseract
    except ImportError:
        return "", False

    try:
        image = page.to_image(resolution=200).original
        text = pytesseract.image_to_string(image)
        return text, True
    except Exception:
        return "", False


def extract_pdf_source(path: str | Path) -> PdfSource:
    pages: list[PageContent] = []
    ocr_attempted = False
    ocr_used = False
    ocr_unavailable = False

    with pdfplumber.open(path) as pdf:
        for i, page in enumerate(pdf.pages, start=1):
            text = page.extract_text() or ""
            try:
                tables = page.extract_tables() or []
            except Exception:
                tables = []

            from_ocr = False
            if len(text.strip()) < MIN_TEXT_CHARS_BEFORE_OCR and not tables:
                ocr_attempted = True
                ocr_text, available = _try_ocr_page(page)
                if not available:
                    ocr_unavailable = True
                elif ocr_text.strip():
                    text = ocr_text
                    from_ocr = True
                    ocr_used = True

            pages.append(PageContent(page_number=i, text=text, tables=tables, from_ocr=from_ocr))

    return PdfSource(
        pages=pages,
        ocr_attempted=ocr_attempted,
        ocr_used=ocr_used,
        ocr_unavailable=ocr_unavailable and not ocr_used,
    )


def extract_pdf_text(path: str | Path) -> str:
    """Plain-text extraction, for callers that don't need page/table detail."""
    return extract_pdf_source(path).full_text


def source_from_text(text: str) -> PdfSource:
    """Wrap plain text (no page/table info available) as a single-page
    PdfSource, so text-only callers can still use the heuristic extractors.
    """
    return PdfSource(pages=[PageContent(page_number=1, text=text, tables=[])])
