"""Tier-2 invoice extraction: used only when the exact structured templates
find no line items. Same philosophy as contract_heuristics.py - synonym-
driven table and line scanning with per-item confidence, rather than one
more format-specific regex.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import InvoiceLineItem
from app.parsers.numbers import find_amounts, find_first_amount, find_percent
from app.parsers.pdf_source import PdfSource
from app.parsers.synonyms import (
    BASE_RATE_RE,
    FUEL_RE,
    TOTAL_RE,
    find_accessorial_code,
)

# A shipment/reference id: a mix of letters, digits, and dashes, at least one
# digit, 4-18 chars - matches SHP-1001, PRO123456, 88421-A, etc. Gated by
# also finding a recognized dollar label on the same line, so we don't treat
# every alphanumeric token in a document as a shipment id.
_ID_RE = re.compile(r"\b(?=[A-Za-z0-9-]*\d)[A-Za-z0-9]{2,8}(?:-[A-Za-z0-9]{2,10}){0,2}\b")
_ID_LABEL_RE = re.compile(r"(shipment|pro\s*#?|bol\s*#?|reference|ref\s*#?)\s*[:#]?\s*", re.IGNORECASE)

MAX_LOOKAHEAD_CHARS = 40


@dataclass
class HeuristicInvoiceResult:
    line_items: list[InvoiceLineItem] = field(default_factory=list)
    invoice_number: str = ""


def _amount_after(text: str, label_match: re.Match) -> float | None:
    window = text[label_match.end() : label_match.end() + MAX_LOOKAHEAD_CHARS]
    return find_first_amount(window)


def _find_invoice_number(text: str) -> str:
    m = re.search(r"invoice\s*(?:#|no\.?|number)?\s*[:#]?\s*([A-Za-z0-9-]{3,20})", text, re.IGNORECASE)
    return m.group(1) if m else ""


def _extract_id(line: str) -> str | None:
    label_m = _ID_LABEL_RE.search(line)
    search_from = label_m.end() if label_m else 0
    m = _ID_RE.search(line, search_from)
    return m.group(0) if m else None


def _scan_line_for_charges(line: str, page_number: int) -> InvoiceLineItem | None:
    total_match = TOTAL_RE.search(line)
    if not total_match:
        return None
    total_amount = _amount_after(line, total_match)
    if total_amount is None:
        return None

    shipment_id = _extract_id(line)
    if not shipment_id:
        return None

    base_match = BASE_RATE_RE.search(line)
    base_amount = _amount_after(line, base_match) if base_match else None

    fuel_match = FUEL_RE.search(line)
    fuel_amount = None
    if fuel_match:
        window = line[fuel_match.end() : fuel_match.end() + MAX_LOOKAHEAD_CHARS]
        fuel_amount = find_first_amount(window)
        if fuel_amount is None:
            pct = find_percent(window)
            if pct is not None and base_amount:
                fuel_amount = round(base_amount * pct / 100.0, 2)

    accessorial_charges: dict[str, float] = {}
    for m in re.finditer(r"[A-Za-z][A-Za-z ]{2,30}?(?=\s*\$)", line):
        code = find_accessorial_code(m.group(0))
        if code:
            amount = find_first_amount(line[m.end() : m.end() + 20])
            if amount is not None:
                accessorial_charges[code] = amount

    matched_signals = sum(x is not None for x in (base_amount, fuel_amount)) + bool(accessorial_charges)
    confidence = 0.55 + 0.12 * matched_signals
    confidence = min(confidence, 0.9)

    return InvoiceLineItem(
        invoice_number="",  # filled in by caller once known
        shipment_id=shipment_id,
        description=line.strip()[:120],
        base_freight=base_amount or 0.0,
        fuel_surcharge=fuel_amount or 0.0,
        accessorial_charges=accessorial_charges,
        billed_total=total_amount,
        source_text=line.strip(),
        source_page=page_number,
        confidence=round(confidence, 2),
        extraction_method="heuristic",
    )


def _line_scan_strategy(source: PdfSource) -> list[InvoiceLineItem]:
    items = []
    for page in source.pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            item = _scan_line_for_charges(line, page.page_number)
            if item:
                items.append(item)
    return items


def _looks_like_header_row(row: list[str | None]) -> bool:
    cells = [c for c in row if c]
    if not cells:
        return False
    numeric_like = sum(1 for c in cells if re.fullmatch(r"[\d.,$%\s-]+", c))
    return numeric_like <= len(cells) / 2


def _map_header_cell(cell: str) -> str | None:
    low = cell.strip().lower()
    if not low:
        return None
    if "shipment" in low or "pro #" in low or "pro#" in low or "reference" in low or low == "id":
        return "ID"
    accessorial_code = find_accessorial_code(low)
    if accessorial_code:
        return f"ACCESSORIAL:{accessorial_code}"
    if TOTAL_RE.search(low):
        return "TOTAL"
    if FUEL_RE.search(low):
        return "FUEL"
    if BASE_RATE_RE.search(low):
        return "BASE_RATE"
    return None


def _table_strategy(source: PdfSource) -> list[InvoiceLineItem]:
    items = []
    for page in source.pages:
        for table in page.tables:
            if len(table) < 2 or not _looks_like_header_row(table[0]):
                continue

            column_map: dict[int, str] = {}
            for idx, cell in enumerate(table[0]):
                mapped = _map_header_cell(cell or "")
                if mapped:
                    column_map[idx] = mapped

            if "ID" not in column_map.values() or "TOTAL" not in column_map.values():
                continue

            for row in table[1:]:
                cells = {column_map[i]: (row[i] or "").strip() for i in column_map if i < len(row)}
                shipment_id = cells.get("ID", "")
                total_amount = find_first_amount(cells.get("TOTAL", ""))
                if not shipment_id or total_amount is None:
                    continue

                base_amount = find_first_amount(cells.get("BASE_RATE", "")) or 0.0
                fuel_amount = find_first_amount(cells.get("FUEL", "")) or 0.0
                accessorial_charges = {}
                for key, value in cells.items():
                    if key.startswith("ACCESSORIAL:"):
                        amount = find_first_amount(value)
                        if amount is not None:
                            accessorial_charges[key.split(":", 1)[1]] = amount

                row_text = " | ".join(f"{k}: {v}" for k, v in cells.items())
                items.append(
                    InvoiceLineItem(
                        invoice_number="",
                        shipment_id=shipment_id,
                        description=row_text[:120],
                        base_freight=base_amount,
                        fuel_surcharge=fuel_amount,
                        accessorial_charges=accessorial_charges,
                        billed_total=total_amount,
                        source_text=row_text,
                        source_page=page.page_number,
                        confidence=0.85,
                        extraction_method="heuristic",
                    )
                )
    return items


def extract_invoice_heuristically(source: PdfSource) -> HeuristicInvoiceResult:
    candidates = _table_strategy(source) + _line_scan_strategy(source)

    best_by_id: dict[str, InvoiceLineItem] = {}
    for item in candidates:
        existing = best_by_id.get(item.shipment_id)
        if existing is None or item.confidence > existing.confidence:
            best_by_id[item.shipment_id] = item

    invoice_number = _find_invoice_number(source.full_text)
    line_items = list(best_by_id.values())
    for item in line_items:
        item.invoice_number = invoice_number

    return HeuristicInvoiceResult(line_items=line_items, invoice_number=invoice_number)
