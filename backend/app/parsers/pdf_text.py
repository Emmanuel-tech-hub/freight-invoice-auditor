"""Shared helper for pulling raw text out of a PDF."""
from __future__ import annotations

from pathlib import Path

import pdfplumber


def extract_pdf_text(path: str | Path) -> str:
    """Return the full text content of a PDF, page breaks joined with newlines."""
    pages = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            pages.append(text)
    return "\n".join(pages)
