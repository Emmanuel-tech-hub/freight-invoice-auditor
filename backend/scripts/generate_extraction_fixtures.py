"""Generates tests/fixtures/format_*.pdf - a deliberately varied set of
contract/rate-card and invoice PDFs, used to prove the Tier-2/3 extraction
engine generalizes beyond one hardcoded layout. Each uses different
terminology, structure, and number formatting from the others and from the
V1 template/natural formats.

Run with: python -m scripts.generate_extraction_fixtures   (from backend/)
"""
from __future__ import annotations

from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle, SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib import colors
from reportlab.lib.units import inch

FIXTURES_DIR = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


def draw_lines(path: Path, title: str, pages: list[list[str]]) -> None:
    """pages: list of pages, each a list of lines. Blank string = blank line."""
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    for page_lines in pages:
        y = height - 60
        c.setFont("Helvetica-Bold", 15)
        c.drawString(50, y, title)
        y -= 28
        c.setFont("Helvetica", 10)
        for line in page_lines:
            if y < 50:
                c.showPage()
                c.setFont("Helvetica", 10)
                y = height - 50
            c.drawString(50, y, line)
            y -= 15
        c.showPage()
    c.save()


# ---------------------------------------------------------------------------
# Format 1: clean table, "Linehaul/FSC" terminology
# ---------------------------------------------------------------------------
def build_format_table() -> None:
    doc = SimpleDocTemplate(str(FIXTURES_DIR / "format_table.pdf"), pagesize=letter)
    styles = getSampleStyleSheet()
    story = [Paragraph("Meridian Freight Systems — Rate Schedule 2026", styles["Title"]), Spacer(1, 16)]

    data = [
        ["Origin", "Destination", "Linehaul", "FSC", "Min Charge", "Liftgate Fee"],
        ["Denver, CO", "Salt Lake City, UT", "$980.00", "10%", "$150.00", "$70.00"],
        ["Denver, CO", "Phoenix, AZ", "$1,340.00", "10%", "$150.00", "$70.00"],
        ["Portland, OR", "Boise, ID", "$610.00", "9%", "$120.00", "$65.00"],
    ]
    table = Table(data, colWidths=[1.1 * inch] * 6)
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


# ---------------------------------------------------------------------------
# Format 2: prose/sentence style, "Linehaul $X, Fuel Surcharge Y%" terminology
# (deliberately NOT matching Tier-1's "Base $X | Fuel Y%" pipe-delimited regex)
# ---------------------------------------------------------------------------
def build_format_sentence() -> None:
    lines = [
        "This Rate Confirmation governs shipments tendered under Agreement #MF-8834.",
        "",
        "Los Angeles, CA to Phoenix, AZ: Linehaul $650.00, Fuel Surcharge 12%, Liftgate $85.00, Residential Delivery $70.00.",
        "Phoenix, AZ to Albuquerque, NM: Linehaul $520.00, Fuel Surcharge 12%, Detention $55.00.",
        "Albuquerque, NM to El Paso, TX: Linehaul $410.00, Fuel Surcharge 11%.",
        "",
        "All accessorial charges require prior authorization from Shipper.",
    ]
    draw_lines(FIXTURES_DIR / "format_sentence.pdf", "Southwest Regional Carriers - Rate Confirmation", [lines])


# ---------------------------------------------------------------------------
# Format 3: vertically-stacked label/value blocks, "Freight Charge/Fuel
# Adjustment" terminology
# ---------------------------------------------------------------------------
def build_format_block() -> None:
    lines = [
        "Lane 1",
        "Origin: Atlanta, GA",
        "Destination: Nashville, TN",
        "Freight Charge: $540.00",
        "Fuel Adjustment: 9.5%",
        "Detention Fee: $60.00",
        "",
        "Lane 2",
        "Origin: Nashville, TN",
        "Destination: Louisville, KY",
        "Freight Charge: $310.00",
        "Fuel Adjustment: 9.5%",
        "",
        "Lane 3",
        "Origin: Louisville, KY",
        "Destination: Indianapolis, IN",
        "Freight Charge: $275.00",
        "Fuel Adjustment: 9.0%",
        "Inside Delivery: $90.00",
    ]
    draw_lines(FIXTURES_DIR / "format_block.pdf", "Bluegrass Transport Co. - Contracted Lane Rates", [lines])


# ---------------------------------------------------------------------------
# Format 4: multi-page, "Flat Rate/FSC%" terminology, comma-formatted numbers
# ---------------------------------------------------------------------------
def build_format_multipage() -> None:
    page1 = [
        "Section 1: Northeast Lanes",
        "",
        "Boston, MA -> New York, NY: Flat Rate $1,050.00, FSC% 8.5%, Liftgate $60.00",
        "New York, NY -> Philadelphia, PA: Flat Rate $620.00, FSC% 8.5%",
    ]
    page2 = [
        "Section 2: Mid-Atlantic Lanes (continued)",
        "",
        "Philadelphia, PA -> Baltimore, MD: Flat Rate $480.00, FSC% 8.0%, Residential $75.00",
        "Baltimore, MD -> Washington, DC: Flat Rate $310.00, FSC% 8.0%",
        "",
        "Accessorial Schedule: Liftgate $60.00, Residential $75.00, Detention $50.00 per hour after 2 free hours.",
    ]
    draw_lines(FIXTURES_DIR / "format_multipage.pdf", "Atlantic Corridor Freight - Master Rate Sheet", [page1, page2])


# ---------------------------------------------------------------------------
# Format 5: per-mile pricing, bare numbers in a table (no $ signs), different
# column order than format_table
# ---------------------------------------------------------------------------
def build_format_permile_table() -> None:
    doc = SimpleDocTemplate(str(FIXTURES_DIR / "format_permile.pdf"), pagesize=letter)
    styles = getSampleStyleSheet()
    story = [Paragraph("Great Plains Trucking — FTL Mileage Rates", styles["Title"]), Spacer(1, 16)]

    # Column order deliberately different from format_table.pdf: rate first.
    data = [
        ["Rate (USD/mile)", "Fuel %", "From", "To", "Detention"],
        ["2.35", "14%", "Omaha, NE", "Kansas City, MO", "50"],
        ["2.10", "14%", "Kansas City, MO", "St. Louis, MO", "50"],
        ["2.60", "13%", "Omaha, NE", "Des Moines, IA", "50"],
    ]
    table = Table(data, colWidths=[1.2 * inch] * 5)
    table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1f4e79")),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("FONTSIZE", (0, 0), (-1, -1), 8),
            ]
        )
    )
    story.append(table)
    story.append(Spacer(1, 10))
    story.append(Paragraph("Rate is per mile, loaded. Detention billed in USD per hour after 2 free hours.", styles["Normal"]))
    doc.build(story)


# ---------------------------------------------------------------------------
# Messy: same content family as format_sentence, but with noisy formatting -
# extra blank lines, a running header/footer, irregular spacing.
# ---------------------------------------------------------------------------
def build_format_messy() -> None:
    lines = [
        "CONFIDENTIAL - INTERNAL USE ONLY",
        "",
        "",
        "   Rate memo (draft v3 -- do not distribute)     ",
        "",
        "hey team, updated numbers below per the call today.",
        "",
        "   Miami, FL   to    Orlando, FL :   linehaul  $ 410.00 ,   fuel surcharge   11 % ,  liftgate   $ 55.00  ",
        "",
        "",
        "Orlando, FL to Jacksonville, FL: linehaul $380.00, fuel surcharge 11%",
        "",
        "let me know if these look right before we send to the carrier.",
        "",
        "Page 1 of 1 - Meridian Internal Draft",
    ]
    draw_lines(FIXTURES_DIR / "format_messy.pdf", "", [lines])


# ---------------------------------------------------------------------------
# Not a contract at all - should classify as not_a_contract, zero rate cards.
# ---------------------------------------------------------------------------
def build_not_a_contract() -> None:
    lines = [
        "Employee Handbook Excerpt - Section 4: Time Off Policy",
        "",
        "Full-time employees accrue 15 days of paid time off per calendar year.",
        "Requests must be submitted at least two weeks in advance via the HR portal.",
        "Unused time off may be carried over up to a maximum of 5 days into the next year.",
        "",
        "Contact human.resources@example.com with any questions about this policy.",
    ]
    draw_lines(FIXTURES_DIR / "not_a_contract.pdf", "Acme Corp Employee Handbook", [lines])


# ---------------------------------------------------------------------------
# Scanned/image-only PDF: render the sentence-format content as a flattened
# image with no text layer, to exercise (and honestly test) the OCR path.
# ---------------------------------------------------------------------------
def build_scanned_like() -> None:
    from reportlab.graphics import renderPDF
    from reportlab.graphics.shapes import Drawing, String
    from reportlab.pdfgen import canvas as pdfcanvas
    import io

    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not available - skipping scanned-PDF fixture")
        return

    img = Image.new("RGB", (1700, 2200), "white")
    draw = ImageDraw.Draw(img)
    lines = [
        "Scanned Rate Sheet (image only, no text layer)",
        "",
        "Chicago, IL to Milwaukee, WI: Linehaul $310.00, Fuel Surcharge 9%",
    ]
    y = 100
    for line in lines:
        draw.text((100, y), line, fill="black")
        y += 60

    img_path = FIXTURES_DIR / "_scanned_source.png"
    img.save(img_path)

    c = pdfcanvas.Canvas(str(FIXTURES_DIR / "format_scanned.pdf"), pagesize=letter)
    width, height = letter
    c.drawImage(str(img_path), 0, 0, width=width, height=height)
    c.showPage()
    c.save()
    img_path.unlink(missing_ok=True)


if __name__ == "__main__":
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    build_format_table()
    build_format_sentence()
    build_format_block()
    build_format_multipage()
    build_format_permile_table()
    build_format_messy()
    build_not_a_contract()
    build_scanned_like()
    print(f"Extraction test fixtures written to {FIXTURES_DIR}")
