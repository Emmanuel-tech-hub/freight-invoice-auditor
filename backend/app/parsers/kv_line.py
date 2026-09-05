"""Parser for the pipe-delimited `KEY: value | KEY: value` line format used by
the V1 structured document template (see README for the full spec).

Real-world carrier PDFs come in wildly inconsistent layouts, so V1 defines a
normalized intermediate schema and expects contracts/invoices to already be
in (or be pre-processed into) this line format. A future revision can plug an
LLM/OCR extraction step in front of this parser to translate arbitrary PDF
layouts into the same key/value lines without touching the matching engine.
"""
from __future__ import annotations


def parse_kv_line(line: str) -> dict[str, str]:
    """Split a `KEY: value | KEY: value` line into an upper-cased key dict."""
    fields: dict[str, str] = {}
    for part in line.split("|"):
        part = part.strip()
        if not part or ":" not in part:
            continue
        key, value = part.split(":", 1)
        fields[key.strip().upper()] = value.strip()
    return fields
