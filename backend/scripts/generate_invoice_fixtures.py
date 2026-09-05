"""Generates tests/fixtures/invoice_*.pdf - varied invoice layouts to prove
the invoice extractor generalizes the same way the contract one does.

Run with: python -m scripts.generate_invoice_fixtures   (from backend/)
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def build_invoice_table() -> None:
    doc = SimpleDocTemplate(str(FIXTURES_DIR / "invoice_table.pdf"), pagesize=letter)
    styles = getSampleStyleSheet()
    story = [Paragraph("Meridian Freight Systems — Invoice INV-55210", styles["Title"]), Spacer(1, 16)]

    data = [
        ["PRO #", "Linehaul", "FSC", "Liftgate Fee", "Total Due"],
        ["SHP-2001", "$980.00", "$98.00", "$70.00", "$1,148.00"],
        ["SHP-2002", "$1,450.00", "$134.00", "$0.00", "$1,584.00"],
        ["SHP-2003", "$610.00", "$54.90", "$65.00", "$729.90"],
    ]
    table = Table(data, colWidths=[1.1 * inch] * 5)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#333333")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    doc.build(story)


def build_invoice_sentence() -> None:
    from reportlab.pdfgen import canvas

    lines = [
        "Southwest Regional Carriers - Invoice #SRC-77410",
        "",
        "Shipment SHP-3001 (Los Angeles, CA to Phoenix, AZ): Linehaul $650.00, "
        "Fuel Surcharge $91.00, Liftgate $85.00. Total Due: $826.00",
        "Shipment SHP-3002 (Phoenix, AZ to Albuquerque, NM): Linehaul $520.00, "
        "Fuel Surcharge $62.40. Total Due: $582.40",
        "Shipment SHP-3003 (Albuquerque, NM to El Paso, TX): Linehaul $460.00, "
        "Fuel Surcharge $50.60. Total Due: $510.60",
        "",
        "Payment due within 30 days of invoice date.",
    ]
    c = canvas.Canvas(str(FIXTURES_DIR / "invoice_sentence.pdf"), pagesize=letter)
    width, height = letter
    y = height - 60
    c.setFont("Helvetica", 10)
    for line in lines:
        c.drawString(50, y, line)
        y -= 16
    c.save()


if __name__ == "__main__":
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    build_invoice_table()
    build_invoice_sentence()
    print(f"Invoice test fixtures written to {FIXTURES_DIR}")
