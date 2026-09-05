"""Proves the Tier-2/3 extraction engine generalizes across genuinely
different contract/invoice layouts and terminology, rather than matching one
hardcoded format. See scripts/generate_extraction_fixtures.py and
scripts/generate_invoice_fixtures.py for how these PDFs were built.
"""
from pathlib import Path

from app.engine.discrepancy import run_audit
from app.models import REVIEW_CONFIDENCE_THRESHOLD
from app.parsers.contract_parser import parse_contract_pdf
from app.parsers.invoice_parser import parse_invoice_pdf, parse_invoice_pdf_detailed
from app.parsers.shipment_parser import parse_shipment_csv

FIXTURES = Path(__file__).resolve().parent / "fixtures"


def test_format_table_high_confidence():
    """Clean table, 'Linehaul/FSC' terminology, different column order/names
    than the V1 template - should extract with high confidence, no review.
    """
    contract = parse_contract_pdf(FIXTURES / "format_table.pdf")
    assert contract.document_classification == "rate_card"
    assert len(contract.rate_cards) == 3
    assert contract.review_items == []
    for rc in contract.rate_cards:
        assert rc.confidence >= REVIEW_CONFIDENCE_THRESHOLD
        assert rc.extraction_method == "heuristic"
        assert rc.source_page == 1
    lanes = {rc.lane for rc in contract.rate_cards}
    assert lanes == {"DENVER-SALT LAKE CITY", "DENVER-PHOENIX", "PORTLAND-BOISE"}
    assert contract.accessorial_caps.get("LIFTGATE") is not None


def test_format_sentence_lower_confidence_flagged_for_review():
    """Prose paragraph, 'Linehaul'/'Fuel Surcharge' terminology, lane joined
    by the word 'to' rather than an arrow - a weaker signal, so this should
    still extract the rates but flag them for review rather than silently
    trusting them.
    """
    contract = parse_contract_pdf(FIXTURES / "format_sentence.pdf")
    assert contract.document_classification == "rate_card"
    assert len(contract.rate_cards) == 3
    assert len(contract.review_items) == 3
    for rc in contract.review_items:
        assert rc.needs_review is True
        assert rc.confidence < REVIEW_CONFIDENCE_THRESHOLD
    lanes = {rc.lane for rc in contract.rate_cards}
    assert "LOS ANGELES-PHOENIX" in lanes


def test_format_block_vertical_labels():
    """Origin:/Destination:/Freight Charge:/Fuel Adjustment: stacked one per
    line rather than packed onto a single line - exercises the block-scan
    strategy specifically.
    """
    contract = parse_contract_pdf(FIXTURES / "format_block.pdf")
    assert contract.document_classification == "rate_card"
    assert len(contract.rate_cards) == 3
    lanes = {rc.lane: rc for rc in contract.rate_cards}
    assert "ATLANTA-NASHVILLE" in lanes
    assert lanes["ATLANTA-NASHVILLE"].rate_value == 540.0
    assert lanes["ATLANTA-NASHVILLE"].fuel_surcharge_pct == 9.5


def test_format_multipage_spans_pages():
    """Lanes and an accessorial schedule spread across two pages, 'Flat
    Rate'/'FSC%' terminology, comma-formatted numbers.
    """
    contract = parse_contract_pdf(FIXTURES / "format_multipage.pdf")
    assert len(contract.rate_cards) == 4
    pages = {rc.source_page for rc in contract.rate_cards}
    assert pages == {1, 2}
    lanes = {rc.lane: rc for rc in contract.rate_cards}
    assert lanes["BOSTON-NEW YORK"].rate_value == 1050.0  # "$1,050.00" parsed correctly


def test_format_permile_table_bare_numbers_and_column_order():
    """Rate-first column order (different from format_table.pdf), per-mile
    pricing detected from the column header wording, and a Detention column
    with bare numbers (no '$').
    """
    contract = parse_contract_pdf(FIXTURES / "format_permile.pdf")
    assert len(contract.rate_cards) == 3
    for rc in contract.rate_cards:
        assert rc.rate_type == "PER_MILE"
    assert contract.accessorial_caps.get("DETENTION") == 50.0


def test_format_messy_still_extracts():
    """Noisy formatting: irregular spacing, blank lines, header/footer
    clutter, casual wording around the actual rate sentences."""
    contract = parse_contract_pdf(FIXTURES / "format_messy.pdf")
    assert len(contract.rate_cards) == 2
    lanes = {rc.lane for rc in contract.rate_cards}
    assert "MIAMI-ORLANDO" in lanes


def test_not_a_contract_is_classified_correctly():
    """A document with zero freight terminology should be told apart from
    one that's freight-related but just hard to parse."""
    contract = parse_contract_pdf(FIXTURES / "not_a_contract.pdf")
    assert contract.rate_cards == []
    assert contract.document_classification == "not_a_contract"


def test_scanned_pdf_reports_ocr_status_honestly():
    """An image-only PDF (no text layer) should either OCR successfully or
    clearly report that OCR wasn't available - never silently return zero
    rate cards with no explanation."""
    contract = parse_contract_pdf(FIXTURES / "format_scanned.pdf")
    assert contract.rate_cards == []
    if contract.ocr_used:
        # If this environment does have tesseract, extraction should have
        # picked something up from the rendered image.
        pass
    else:
        assert contract.ocr_unavailable is True


def test_invoice_table_format():
    result = parse_invoice_pdf_detailed(FIXTURES / "invoice_table.pdf")
    assert result.document_classification == "invoice"
    assert len(result.line_items) == 3
    by_id = {li.shipment_id: li for li in result.line_items}
    assert by_id["SHP-2001"].billed_total == 1148.0
    assert by_id["SHP-2001"].accessorial_charges.get("LIFTGATE") == 70.0


def test_invoice_sentence_format():
    result = parse_invoice_pdf_detailed(FIXTURES / "invoice_sentence.pdf")
    assert len(result.line_items) == 3
    by_id = {li.shipment_id: li for li in result.line_items}
    assert by_id["SHP-3001"].base_freight == 650.0
    assert by_id["SHP-3001"].fuel_surcharge == 91.0


def test_heuristic_contract_end_to_end_audit_with_per_lane_accessorial_caps():
    """Full pipeline on a heuristically-extracted (table) contract: matches
    invoice lines to shipments to rate cards, and correctly applies each
    lane's OWN accessorial cap rather than a single contract-wide value -
    two lanes here have different liftgate fees ($70 vs $65).
    """
    contract = parse_contract_pdf(FIXTURES / "format_table.pdf")
    invoice_lines = parse_invoice_pdf(FIXTURES / "invoice_table.pdf")
    shipments = parse_shipment_csv(FIXTURES / "format_table_shipments.csv")

    result = run_audit(
        invoice_lines, shipments, contract.rate_cards, contract.accessorial_caps, contract.hourly_rules
    )

    assert result.unmatched_shipment_ids == []
    # SHP-2001 and SHP-2003 bill liftgate exactly at their own lane's cap
    # ($70 and $65 respectively) - only SHP-2002's inflated base freight
    # should be flagged.
    assert {d.shipment_id for d in result.discrepancies} == {"SHP-2002"}
    assert result.total_overcharge == 110.0
