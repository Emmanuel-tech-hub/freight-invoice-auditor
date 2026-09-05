from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from app.models import InvoiceLineItem
from app.parsers.invoice_heuristics import extract_invoice_heuristically
from app.parsers.kv_line import parse_kv_line
from app.parsers.pdf_source import PdfSource, extract_pdf_source, source_from_text
from app.parsers.synonyms import looks_like_freight_document


@dataclass
class InvoiceParseResult:
    line_items: list[InvoiceLineItem] = field(default_factory=list)
    document_classification: str = "invoice"  # "invoice" | "unclear" | "not_an_invoice"
    ocr_used: bool = False
    ocr_unavailable: bool = False
    raw_text: str = ""


def _parse_accessorials(raw: str) -> dict[str, float]:
    """Parse `LIFTGATE:95.00,DETENTION:50.00` into a code -> amount dict."""
    result: dict[str, float] = {}
    if not raw:
        return result
    for chunk in raw.split(","):
        chunk = chunk.strip()
        if not chunk or ":" not in chunk:
            continue
        code, _, amount = chunk.partition(":")
        try:
            result[code.strip().upper()] = float(amount.strip())
        except ValueError:
            continue
    return result


def _parse_kv_invoice_text(text: str) -> list[InvoiceLineItem]:
    """Parse the V1 structured `KEY: value | KEY: value` template."""
    line_items: list[InvoiceLineItem] = []
    current_invoice_number = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.upper().startswith("INVOICE:"):
            current_invoice_number = line.split(":", 1)[1].strip()

        elif line.upper().startswith("SHIPMENT:"):
            fields = parse_kv_line(line)
            try:
                line_items.append(
                    InvoiceLineItem(
                        invoice_number=current_invoice_number,
                        shipment_id=fields.get("SHIPMENT", "").strip(),
                        description=fields.get("DESCRIPTION", ""),
                        base_freight=float(fields.get("BASE_FREIGHT", 0) or 0),
                        fuel_surcharge=float(fields.get("FUEL_SURCHARGE", 0) or 0),
                        accessorial_charges=_parse_accessorials(fields.get("ACCESSORIALS", "")),
                        billed_total=float(fields.get("TOTAL_BILLED", 0) or 0),
                        source_text=line,
                    )
                )
            except ValueError:
                continue

    return line_items


# ---------------------------------------------------------------------------
# "Natural" invoice format: plain-English billing lines, e.g.
#   Fastlane Carrier - Invoice FL-88421
#   SHP-1001 | Chicago -> Dallas | Base $1,200 | Fuel $96 | Accessorials $135 | Total $1,431
# ---------------------------------------------------------------------------

_NATURAL_INVOICE_HEADER_RE = re.compile(r"\bInvoice\s+(?P<num>[A-Za-z0-9-]+)", re.IGNORECASE)
_NATURAL_INVOICE_LINE_RE = re.compile(
    r"^(?P<shipment_id>[A-Za-z0-9._-]+)\s*\|\s*(?P<origin>[^|]+?)\s*->\s*(?P<dest>[^|]+?)\s*\|"
    r"\s*Base\s*\$(?P<base>[\d,]+(?:\.\d+)?)\s*\|\s*Fuel\s*\$(?P<fuel>[\d,]+(?:\.\d+)?)\s*\|"
    r"\s*Accessorials\s*\$(?P<accessorials>[\d,]+(?:\.\d+)?)\s*\|\s*Total\s*\$(?P<total>[\d,]+(?:\.\d+)?)\s*$",
    re.IGNORECASE,
)


def _parse_natural_invoice_text(text: str) -> list[InvoiceLineItem]:
    line_items: list[InvoiceLineItem] = []
    invoice_number = ""

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if not invoice_number:
            hm = _NATURAL_INVOICE_HEADER_RE.search(line)
            if hm:
                invoice_number = hm.group("num").rstrip(".,")

        m = _NATURAL_INVOICE_LINE_RE.match(line)
        if m:
            line_items.append(
                InvoiceLineItem(
                    invoice_number=invoice_number,
                    shipment_id=m.group("shipment_id").strip(),
                    description=f"{m.group('origin').strip()} to {m.group('dest').strip()}",
                    base_freight=float(m.group("base").replace(",", "")),
                    fuel_surcharge=float(m.group("fuel").replace(",", "")),
                    accessorial_total=float(m.group("accessorials").replace(",", "")),
                    billed_total=float(m.group("total").replace(",", "")),
                    source_text=line,
                )
            )

    return line_items


def _tag_as_template(items: list[InvoiceLineItem]) -> list[InvoiceLineItem]:
    for item in items:
        item.confidence = 1.0
        item.extraction_method = "template"
    return items


def _heuristic_fallback(source: PdfSource) -> list[InvoiceLineItem]:
    """Tier 3: general-purpose extraction for invoices that don't match
    either exact template. See invoice_heuristics.py.
    """
    return extract_invoice_heuristically(source).line_items


def parse_invoice_text(text: str) -> list[InvoiceLineItem]:
    line_items = _parse_kv_invoice_text(text)
    if line_items:
        return _tag_as_template(line_items)

    line_items = _parse_natural_invoice_text(text)
    if line_items:
        return _tag_as_template(line_items)

    return _heuristic_fallback(source_from_text(text))


def parse_invoice_pdf_detailed(path: str | Path) -> InvoiceParseResult:
    source = extract_pdf_source(path)
    text = source.full_text

    line_items = _parse_kv_invoice_text(text)
    if line_items:
        return InvoiceParseResult(line_items=_tag_as_template(line_items))

    line_items = _parse_natural_invoice_text(text)
    if line_items:
        return InvoiceParseResult(line_items=_tag_as_template(line_items))

    line_items = _heuristic_fallback(source)
    if line_items:
        classification = "invoice"
    elif looks_like_freight_document(text):
        classification = "unclear"
    else:
        classification = "not_an_invoice"

    return InvoiceParseResult(
        line_items=line_items,
        document_classification=classification,
        ocr_used=source.ocr_used,
        ocr_unavailable=source.ocr_unavailable,
        raw_text=text,
    )


def parse_invoice_pdf(path: str | Path) -> list[InvoiceLineItem]:
    return parse_invoice_pdf_detailed(path).line_items
