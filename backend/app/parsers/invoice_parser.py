from __future__ import annotations

from pathlib import Path

from app.models import InvoiceLineItem
from app.parsers.kv_line import parse_kv_line
from app.parsers.pdf_text import extract_pdf_text


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


def parse_invoice_text(text: str) -> list[InvoiceLineItem]:
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


def parse_invoice_pdf(path: str | Path) -> list[InvoiceLineItem]:
    text = extract_pdf_text(path)
    return parse_invoice_text(text)
