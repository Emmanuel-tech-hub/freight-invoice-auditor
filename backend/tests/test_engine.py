from pathlib import Path

from app.engine.discrepancy import run_audit
from app.parsers.contract_parser import parse_contract_pdf, parse_contract_text
from app.parsers.invoice_parser import parse_invoice_pdf, parse_invoice_text
from app.parsers.shipment_parser import parse_shipment_csv

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"

CONTRACT_TEXT = """
RATE CARD
LANE: CHICAGO IL -> DALLAS TX | SERVICE: LTL | RATE_TYPE: PER_CWT | RATE: 18.50 | MIN_CHARGE: 150.00 | FUEL_SURCHARGE_PCT: 16.0

ACCESSORIAL CAPS
CODE: LIFTGATE | DESCRIPTION: Liftgate Service | MAX_AMOUNT: 75.00
"""

INVOICE_TEXT = """
INVOICE: INV-1
SHIPMENT: SHP-1 | DESCRIPTION: LTL Chicago to Dallas | BASE_FREIGHT: 592.00 | FUEL_SURCHARGE: 94.72 | ACCESSORIALS: LIFTGATE:150.00 | TOTAL_BILLED: 836.72
SHIPMENT: SHP-2 | DESCRIPTION: LTL Chicago to Dallas | BASE_FREIGHT: 592.00 | FUEL_SURCHARGE: 94.72 | ACCESSORIALS: | TOTAL_BILLED: 686.72
"""


def test_parse_contract_text():
    contract = parse_contract_text(CONTRACT_TEXT)
    assert len(contract.rate_cards) == 1
    rc = contract.rate_cards[0]
    assert rc.lane == "CHICAGO IL-DALLAS TX"
    assert rc.rate_value == 18.50
    assert contract.accessorial_caps["LIFTGATE"] == 75.00


def test_parse_invoice_text():
    lines = parse_invoice_text(INVOICE_TEXT)
    assert len(lines) == 2
    assert lines[0].shipment_id == "SHP-1"
    assert lines[0].accessorial_charges["LIFTGATE"] == 150.00
    assert lines[0].billed_total == 836.72


def test_engine_flags_overcharges_end_to_end():
    from app.models import RateCard, Shipment, InvoiceLineItem

    rate_cards = [
        RateCard(
            lane="CHICAGO IL-DALLAS TX",
            service_level="LTL",
            rate_type="PER_CWT",
            rate_value=18.50,
            minimum_charge=150.00,
            fuel_surcharge_pct=16.0,
            source_text="LANE: CHICAGO IL-DALLAS TX | SERVICE: LTL | RATE_TYPE: PER_CWT | RATE: 18.50",
        )
    ]
    shipments = [
        Shipment(
            shipment_id="SHP-1",
            origin="CHICAGO IL",
            destination="DALLAS TX",
            service_level="LTL",
            weight_lbs=3200,
            accessorials=["LIFTGATE"],
        ),
        Shipment(
            shipment_id="SHP-2",
            origin="CHICAGO IL",
            destination="DALLAS TX",
            service_level="LTL",
            weight_lbs=3200,
            accessorials=[],
        ),
    ]
    invoice_lines = [
        InvoiceLineItem(
            invoice_number="INV-1",
            shipment_id="SHP-1",
            base_freight=592.00,  # correct: 18.50 * 32
            fuel_surcharge=94.72,  # correct: 592 * 0.16
            accessorial_charges={"LIFTGATE": 150.00},  # cap is 75 -> overcharge of 75
            billed_total=836.72,
        ),
        InvoiceLineItem(
            invoice_number="INV-1",
            shipment_id="SHP-2",
            base_freight=650.00,  # billed higher than contracted 592 -> overcharge of 58
            fuel_surcharge=94.72,
            accessorial_charges={},
            billed_total=744.72,
        ),
    ]

    result = run_audit(invoice_lines, shipments, rate_cards, {"LIFTGATE": 75.00})

    assert result.shipments_audited == 2
    assert result.shipments_with_discrepancies == 2
    reasons = [d.reason for d in result.discrepancies]
    assert any("exceeds the contracted amount" in r for r in reasons)
    assert any("exceeds the contracted" in r and "rate" in r for r in reasons)
    assert result.total_overcharge == 75.00 + 58.00


def test_unmatched_shipment_is_not_a_discrepancy():
    from app.models import RateCard, InvoiceLineItem

    rate_cards = [
        RateCard(lane="A-B", service_level="LTL", rate_type="FLAT", rate_value=100.0, source_text="x")
    ]
    invoice_lines = [
        InvoiceLineItem(invoice_number="INV-1", shipment_id="GHOST", base_freight=999, billed_total=999)
    ]
    result = run_audit(invoice_lines, [], rate_cards, {})
    assert result.discrepancies == []
    assert result.unmatched_shipment_ids == ["GHOST"]
    assert result.shipments_audited == 0


def test_sample_data_end_to_end():
    contract = parse_contract_pdf(SAMPLE_DIR / "contract.pdf")
    invoice_lines = parse_invoice_pdf(SAMPLE_DIR / "invoice.pdf")
    shipments = parse_shipment_csv(SAMPLE_DIR / "shipments.csv")

    assert len(contract.rate_cards) == 6
    assert len(shipments) == 24
    assert len(invoice_lines) == 24

    result = run_audit(invoice_lines, shipments, contract.rate_cards, contract.accessorial_caps)

    assert result.unmatched_shipment_ids == []
    assert result.shipments_audited == 24
    # 9 shipments were seeded with an overcharge in generate_sample_data.py
    assert result.shipments_with_discrepancies == 9
    assert result.total_overcharge > 0


def test_natural_format_end_to_end():
    """Plain-English contract/invoice + an alternate shipment CSV schema,
    as produced by a real carrier rather than the V1 KV-line template.
    """
    fixtures = Path(__file__).resolve().parent / "fixtures"
    contract = parse_contract_pdf(fixtures / "natural_contract.pdf")
    invoice_lines = parse_invoice_pdf(fixtures / "natural_invoice.pdf")
    shipments = parse_shipment_csv(fixtures / "natural_shipments.csv")

    assert len(contract.rate_cards) == 3
    assert contract.accessorial_caps["RESIDENTIAL"] == 75.0
    assert contract.accessorial_caps["LIFTGATE"] == 60.0
    assert contract.hourly_rules["DETENTION"] == {"rate": 50.0, "free_units": 2.0}

    assert len(shipments) == 3
    assert shipments[0].accessorials == ["RESIDENTIAL", "LIFTGATE"]

    assert len(invoice_lines) == 3
    assert invoice_lines[0].accessorial_total == 135.0

    result = run_audit(
        invoice_lines, shipments, contract.rate_cards, contract.accessorial_caps, contract.hourly_rules
    )

    assert result.unmatched_shipment_ids == []
    assert result.shipments_audited == 3
    # SHP-1003 is billed $850 base against a contracted $800 flat rate,
    # and its fuel surcharge is computed off the inflated base too.
    assert result.shipments_with_discrepancies == 1
    assert {d.shipment_id for d in result.discrepancies} == {"SHP-1003"}
    assert result.total_overcharge == 54.0
