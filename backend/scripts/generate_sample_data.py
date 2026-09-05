"""Generates demo sample_data/{contract.pdf, invoice.pdf, shipments.csv}.

Run with: python -m scripts.generate_sample_data   (from backend/)

Builds a small, fully deterministic freight audit scenario: six lanes with
contracted rates, 24 shipments, and an invoice that bills most shipments
correctly but injects a handful of realistic overcharge patterns (rate
creep, fuel surcharge above the contracted cap, phantom accessorials, and
accessorials billed above their contracted cap) so the engine has something
to find.
"""
from __future__ import annotations

import csv
from pathlib import Path

from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

SAMPLE_DIR = Path(__file__).resolve().parent.parent / "sample_data"

LANES = [
    # (lane_key, service, rate_type, rate, min_charge, fuel_pct)
    ("CHICAGO IL-DALLAS TX", "LTL", "PER_CWT", 18.50, 150.00, 16.0),
    ("CHICAGO IL-DALLAS TX", "FTL", "PER_MILE", 2.35, 450.00, 16.0),
    ("LOS ANGELES CA-PHOENIX AZ", "LTL", "PER_CWT", 15.75, 125.00, 14.0),
    ("ATLANTA GA-MIAMI FL", "LTL", "PER_CWT", 14.20, 110.00, 15.0),
    ("NEW YORK NY-BOSTON MA", "LTL", "PER_CWT", 12.90, 100.00, 13.0),
    ("SEATTLE WA-PORTLAND OR", "LTL", "PER_CWT", 11.50, 95.00, 12.0),
]
RATE_BY_KEY = {(lane, svc): (rate_type, rate, minc, fuel) for lane, svc, rate_type, rate, minc, fuel in LANES}

ACCESSORIAL_CAPS = {
    "LIFTGATE": 75.00,
    "RESIDENTIAL": 95.00,
    "DETENTION": 50.00,
    "INSIDE_DELIVERY": 65.00,
}

# (shipment_id, lane, service, weight_lbs, miles, accessorials)
SHIPMENTS = [
    ("SHP-1001", "CHICAGO IL-DALLAS TX", "LTL", 3200, None, []),
    ("SHP-1002", "CHICAGO IL-DALLAS TX", "LTL", 2800, None, ["LIFTGATE"]),
    ("SHP-1003", "CHICAGO IL-DALLAS TX", "LTL", 4100, None, []),
    ("SHP-1004", "CHICAGO IL-DALLAS TX", "LTL", 1500, None, []),
    ("SHP-1005", "CHICAGO IL-DALLAS TX", "FTL", 18000, 925, []),
    ("SHP-1006", "CHICAGO IL-DALLAS TX", "FTL", 19500, 925, ["DETENTION"]),
    ("SHP-1007", "CHICAGO IL-DALLAS TX", "FTL", 12000, 300, []),
    ("SHP-1008", "CHICAGO IL-DALLAS TX", "FTL", 20000, 925, []),
    ("SHP-1009", "LOS ANGELES CA-PHOENIX AZ", "LTL", 2600, None, []),
    ("SHP-1010", "LOS ANGELES CA-PHOENIX AZ", "LTL", 3300, None, ["RESIDENTIAL"]),
    ("SHP-1011", "LOS ANGELES CA-PHOENIX AZ", "LTL", 5000, None, []),
    ("SHP-1012", "LOS ANGELES CA-PHOENIX AZ", "LTL", 1800, None, ["LIFTGATE"]),
    ("SHP-1013", "ATLANTA GA-MIAMI FL", "LTL", 2900, None, []),
    ("SHP-1014", "ATLANTA GA-MIAMI FL", "LTL", 3600, None, ["DETENTION"]),
    ("SHP-1015", "ATLANTA GA-MIAMI FL", "LTL", 4700, None, []),
    ("SHP-1016", "ATLANTA GA-MIAMI FL", "LTL", 2200, None, []),
    ("SHP-1017", "NEW YORK NY-BOSTON MA", "LTL", 1900, None, []),
    ("SHP-1018", "NEW YORK NY-BOSTON MA", "LTL", 3100, None, ["RESIDENTIAL"]),
    ("SHP-1019", "NEW YORK NY-BOSTON MA", "LTL", 2600, None, []),
    ("SHP-1020", "NEW YORK NY-BOSTON MA", "LTL", 5200, None, []),
    ("SHP-1021", "SEATTLE WA-PORTLAND OR", "LTL", 2100, None, []),
    ("SHP-1022", "SEATTLE WA-PORTLAND OR", "LTL", 2700, None, ["LIFTGATE", "INSIDE_DELIVERY"]),
    ("SHP-1023", "SEATTLE WA-PORTLAND OR", "LTL", 3400, None, []),
    ("SHP-1024", "SEATTLE WA-PORTLAND OR", "LTL", 1600, None, []),
]

# Overcharge injections applied on top of the correctly-computed invoice line.
# Each entry describes exactly how that shipment's billed invoice differs
# from what the contract allows.
OVERCHARGES = {
    "SHP-1003": {"base_rate_override": 21.00},  # billed at $21.00/cwt instead of $18.50
    "SHP-1006": {"accessorial_override": {"DETENTION": 120.00}},  # cap is $50
    "SHP-1008": {"fuel_pct_override": 25.0},  # contracted 16%
    "SHP-1011": {"base_rate_override": 19.00},  # contracted $15.75
    "SHP-1012": {"phantom_accessorial": ("INSIDE_DELIVERY", 65.00)},  # not on shipment record
    "SHP-1016": {"fuel_pct_override": 20.0},  # contracted 15%
    "SHP-1018": {"accessorial_override": {"RESIDENTIAL": 140.00}},  # cap is $95
    "SHP-1020": {"base_rate_override": 15.50},  # contracted $12.90
    "SHP-1024": {"phantom_accessorial": ("DETENTION", 50.00)},  # not on shipment record
}


def expected_base(rate_type: str, rate: float, minc: float, weight: float, miles: float | None) -> float:
    if rate_type == "PER_CWT":
        base = rate * (weight / 100.0)
    elif rate_type == "PER_MILE":
        base = rate * (miles or 0.0)
    else:
        base = rate
    return max(base, minc)


def build_shipments_csv() -> None:
    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    with open(SAMPLE_DIR / "shipments.csv", "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["shipment_id", "origin", "destination", "service_level", "weight_lbs", "miles", "ship_date", "accessorials"])
        for shipment_id, lane, service, weight, miles, accessorials in SHIPMENTS:
            origin, destination = lane.split("-", 1)
            writer.writerow(
                [
                    shipment_id,
                    origin,
                    destination,
                    service,
                    weight,
                    miles or "",
                    "2026-02-14",
                    ";".join(accessorials),
                ]
            )


def draw_lines(path: Path, title: str, lines: list[str]) -> None:
    c = canvas.Canvas(str(path), pagesize=letter)
    width, height = letter
    y = height - 60
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, y, title)
    y -= 30
    c.setFont("Courier", 9)
    for line in lines:
        if y < 50:
            c.showPage()
            c.setFont("Courier", 9)
            y = height - 50
        c.drawString(50, y, line)
        y -= 14
    c.save()


def build_contract_pdf() -> None:
    lines = ["RATE CARD"]
    for lane, service, rate_type, rate, minc, fuel in LANES:
        lines.append(
            f"LANE: {lane} | SERVICE: {service} | RATE_TYPE: {rate_type} | RATE: {rate:.2f} | "
            f"MIN_CHARGE: {minc:.2f} | FUEL_SURCHARGE_PCT: {fuel:.1f}"
        )
    lines.append("")
    lines.append("ACCESSORIAL CAPS")
    for code, amount in ACCESSORIAL_CAPS.items():
        lines.append(f"CODE: {code} | DESCRIPTION: {code.replace('_', ' ').title()} | MAX_AMOUNT: {amount:.2f}")

    draw_lines(SAMPLE_DIR / "contract.pdf", "Carrier Rate Agreement - Acme Freight Lines", lines)


def build_invoice_pdf() -> None:
    lines = ["INVOICE: ACME-INV-88231"]
    for shipment_id, lane, service, weight, miles, accessorials in SHIPMENTS:
        rate_type, rate, minc, fuel_pct = RATE_BY_KEY[(lane, service)]
        overcharge = OVERCHARGES.get(shipment_id, {})

        billed_rate = overcharge.get("base_rate_override", rate)
        base_freight = expected_base(rate_type, billed_rate, minc, weight, miles)

        billed_fuel_pct = overcharge.get("fuel_pct_override", fuel_pct)
        fuel_surcharge = round(base_freight * (billed_fuel_pct / 100.0), 2)

        accessorial_amounts = {code: ACCESSORIAL_CAPS[code] for code in accessorials}
        accessorial_amounts.update(overcharge.get("accessorial_override", {}))
        if "phantom_accessorial" in overcharge:
            code, amount = overcharge["phantom_accessorial"]
            accessorial_amounts[code] = amount

        total_billed = round(base_freight + fuel_surcharge + sum(accessorial_amounts.values()), 2)
        accessorial_str = ",".join(f"{code}:{amount:.2f}" for code, amount in accessorial_amounts.items())

        description = f"{service} {lane.replace('-', ' to ')}"
        line = (
            f"SHIPMENT: {shipment_id} | DESCRIPTION: {description} | BASE_FREIGHT: {base_freight:.2f} | "
            f"FUEL_SURCHARGE: {fuel_surcharge:.2f} | ACCESSORIALS: {accessorial_str} | "
            f"TOTAL_BILLED: {total_billed:.2f}"
        )
        lines.append(line)

    draw_lines(SAMPLE_DIR / "invoice.pdf", "Invoice ACME-INV-88231 - Acme Freight Lines", lines)


if __name__ == "__main__":
    build_shipments_csv()
    build_contract_pdf()
    build_invoice_pdf()
    print(f"Sample data written to {SAMPLE_DIR}")
