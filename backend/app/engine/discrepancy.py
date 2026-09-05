"""The money-finding engine: compares billed invoice amounts against
contracted rates and shipment records, and produces evidenced discrepancies.
"""
from __future__ import annotations

from app.engine.matcher import find_rate_card, index_rate_cards, index_shipments
from app.models import AuditResult, Discrepancy, InvoiceLineItem, RateCard, Shipment

TOLERANCE = 0.01


def _expected_base_charge(rate_card: RateCard, shipment: Shipment) -> float:
    if rate_card.rate_type == "PER_CWT":
        base = rate_card.rate_value * (shipment.weight_lbs / 100.0)
    elif rate_card.rate_type == "PER_MILE":
        base = rate_card.rate_value * (shipment.miles or 0.0)
    elif rate_card.rate_type == "FLAT":
        base = rate_card.rate_value
    else:
        base = 0.0
    return max(base, rate_card.minimum_charge)


def _audit_line_item(
    line: InvoiceLineItem,
    shipment: Shipment,
    rate_card: RateCard,
    accessorial_caps: dict[str, float],
) -> tuple[list[Discrepancy], float]:
    """Returns (discrepancies for this line, total expected charge for this line)."""
    discrepancies: list[Discrepancy] = []

    expected_base = _expected_base_charge(rate_card, shipment)
    if line.base_freight > expected_base + TOLERANCE:
        discrepancies.append(
            Discrepancy(
                shipment_id=shipment.shipment_id,
                invoice_number=line.invoice_number,
                lane=shipment.lane,
                service_level=shipment.service_level,
                reason=(
                    f"Base freight billed at ${line.base_freight:,.2f} exceeds the contracted "
                    f"{rate_card.rate_type.replace('_', ' ').title()} rate of "
                    f"${rate_card.rate_value:,.2f} (expected ${expected_base:,.2f})."
                ),
                billed_amount=line.base_freight,
                expected_amount=expected_base,
                overcharge_amount=round(line.base_freight - expected_base, 2),
                contract_evidence=rate_card.source_text,
                invoice_evidence=line.source_text,
            )
        )

    expected_fuel = expected_base * (rate_card.fuel_surcharge_pct / 100.0)
    if line.fuel_surcharge > expected_fuel + TOLERANCE:
        discrepancies.append(
            Discrepancy(
                shipment_id=shipment.shipment_id,
                invoice_number=line.invoice_number,
                lane=shipment.lane,
                service_level=shipment.service_level,
                reason=(
                    f"Fuel surcharge billed at ${line.fuel_surcharge:,.2f} exceeds the "
                    f"contracted {rate_card.fuel_surcharge_pct:.1f}% cap "
                    f"(expected ${expected_fuel:,.2f})."
                ),
                billed_amount=line.fuel_surcharge,
                expected_amount=expected_fuel,
                overcharge_amount=round(line.fuel_surcharge - expected_fuel, 2),
                contract_evidence=rate_card.source_text,
                invoice_evidence=line.source_text,
            )
        )

    expected_accessorial_total = 0.0
    for code, billed_amount in line.accessorial_charges.items():
        if code not in shipment.accessorials:
            discrepancies.append(
                Discrepancy(
                    shipment_id=shipment.shipment_id,
                    invoice_number=line.invoice_number,
                    lane=shipment.lane,
                    service_level=shipment.service_level,
                    reason=(
                        f"Accessorial '{code}' billed at ${billed_amount:,.2f} but is not "
                        "recorded as performed on this shipment."
                    ),
                    billed_amount=billed_amount,
                    expected_amount=0.0,
                    overcharge_amount=round(billed_amount, 2),
                    contract_evidence=f"No shipment record authorizing accessorial '{code}'.",
                    invoice_evidence=line.source_text,
                )
            )
            continue

        cap = accessorial_caps.get(code)
        if cap is not None and billed_amount > cap + TOLERANCE:
            discrepancies.append(
                Discrepancy(
                    shipment_id=shipment.shipment_id,
                    invoice_number=line.invoice_number,
                    lane=shipment.lane,
                    service_level=shipment.service_level,
                    reason=(
                        f"Accessorial '{code}' billed at ${billed_amount:,.2f} exceeds the "
                        f"contracted cap of ${cap:,.2f}."
                    ),
                    billed_amount=billed_amount,
                    expected_amount=cap,
                    overcharge_amount=round(billed_amount - cap, 2),
                    contract_evidence=f"Accessorial cap CODE: {code} | MAX_AMOUNT: {cap:.2f}",
                    invoice_evidence=line.source_text,
                )
            )
            expected_accessorial_total += cap
        else:
            expected_accessorial_total += billed_amount

    expected_total = expected_base + expected_fuel + expected_accessorial_total
    return discrepancies, expected_total


def run_audit(
    invoice_lines: list[InvoiceLineItem],
    shipments: list[Shipment],
    rate_cards: list[RateCard],
    accessorial_caps: dict[str, float],
) -> AuditResult:
    shipments_by_id = index_shipments(shipments)
    rate_cards_by_key = index_rate_cards(rate_cards)

    all_discrepancies: list[Discrepancy] = []
    total_billed = 0.0
    total_expected = 0.0
    unmatched_shipment_ids: list[str] = []
    shipments_with_discrepancies: set[str] = set()

    for line in invoice_lines:
        shipment = shipments_by_id.get(line.shipment_id)
        if shipment is None:
            unmatched_shipment_ids.append(line.shipment_id)
            continue

        rate_card = find_rate_card(rate_cards_by_key, shipment)
        if rate_card is None:
            unmatched_shipment_ids.append(line.shipment_id)
            continue

        line_discrepancies, expected_total = _audit_line_item(
            line, shipment, rate_card, accessorial_caps
        )

        total_billed += line.billed_total
        total_expected += expected_total
        all_discrepancies.extend(line_discrepancies)
        if line_discrepancies:
            shipments_with_discrepancies.add(shipment.shipment_id)

    total_overcharge = round(sum(d.overcharge_amount for d in all_discrepancies), 2)

    return AuditResult(
        discrepancies=all_discrepancies,
        total_billed=round(total_billed, 2),
        total_expected=round(total_expected, 2),
        total_overcharge=total_overcharge,
        shipments_audited=len(invoice_lines) - len(unmatched_shipment_ids),
        shipments_with_discrepancies=len(shipments_with_discrepancies),
        unmatched_shipment_ids=unmatched_shipment_ids,
    )
