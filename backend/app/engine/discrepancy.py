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


def _expected_accessorial_amount(
    code: str,
    shipment: Shipment,
    rate_card: RateCard,
    accessorial_caps: dict[str, float],
    hourly_rules: dict[str, dict],
) -> tuple[float, str]:
    """Returns (expected amount, evidence text) for one accessorial code that
    applies to this shipment, per an hourly rule (e.g. detention with free
    hours) if one exists, else a flat contracted cap - preferring a cap
    specific to this lane (rate_card.accessorial_caps) over the contract-wide
    default, since different lanes can carry different accessorial pricing.
    """
    if code in hourly_rules:
        rule = hourly_rules[code]
        rate = rule.get("rate", 0.0)
        free_units = rule.get("free_units", 0.0)
        qty = shipment.accessorial_quantities.get(code, 0.0)
        amount = max(0.0, qty - free_units) * rate
        evidence = f"{code}: {qty:g}h billable @ ${rate:.2f}/h after {free_units:g}h free = ${amount:.2f}"
        return amount, evidence

    cap = rate_card.accessorial_caps.get(code)
    if cap is not None:
        return cap, f"{code} = ${cap:.2f} (contracted cap for lane {rate_card.lane})"

    cap = accessorial_caps.get(code)
    if cap is not None:
        return cap, f"{code} = ${cap:.2f} (contracted cap)"

    return 0.0, f"{code} (no contracted rate found for this accessorial)"


def _audit_line_item(
    line: InvoiceLineItem,
    shipment: Shipment,
    rate_card: RateCard,
    accessorial_caps: dict[str, float],
    hourly_rules: dict[str, dict],
) -> tuple[list[Discrepancy], float]:
    """Returns (discrepancies for this line, total expected charge for this line)."""
    discrepancies: list[Discrepancy] = []
    line_needs_review = rate_card.needs_review or line.needs_review

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

    if line.accessorial_charges:
        for code, billed_amount in line.accessorial_charges.items():
            if billed_amount <= TOLERANCE:
                continue  # a $0.00 line for an inapplicable accessorial isn't an overcharge
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

            expected_amount, evidence = _expected_accessorial_amount(
                code, shipment, rate_card, accessorial_caps, hourly_rules
            )
            if billed_amount > expected_amount + TOLERANCE:
                discrepancies.append(
                    Discrepancy(
                        shipment_id=shipment.shipment_id,
                        invoice_number=line.invoice_number,
                        lane=shipment.lane,
                        service_level=shipment.service_level,
                        reason=(
                            f"Accessorial '{code}' billed at ${billed_amount:,.2f} exceeds the "
                            f"contracted amount of ${expected_amount:,.2f}."
                        ),
                        billed_amount=billed_amount,
                        expected_amount=expected_amount,
                        overcharge_amount=round(billed_amount - expected_amount, 2),
                        contract_evidence=evidence,
                        invoice_evidence=line.source_text,
                    )
                )
                expected_accessorial_total += expected_amount
            else:
                expected_accessorial_total += billed_amount

    elif line.accessorial_total is not None:
        # Some invoices bill accessorials as one lump sum rather than
        # itemized by code. Derive what should have been charged from the
        # shipment's own record, and compare the totals.
        evidence_parts = []
        for code in shipment.accessorials:
            amount, evidence = _expected_accessorial_amount(
                code, shipment, rate_card, accessorial_caps, hourly_rules
            )
            expected_accessorial_total += amount
            evidence_parts.append(evidence)

        billed_accessorial_total = line.accessorial_total
        if billed_accessorial_total > expected_accessorial_total + TOLERANCE:
            discrepancies.append(
                Discrepancy(
                    shipment_id=shipment.shipment_id,
                    invoice_number=line.invoice_number,
                    lane=shipment.lane,
                    service_level=shipment.service_level,
                    reason=(
                        f"Accessorials billed at ${billed_accessorial_total:,.2f} exceed the "
                        f"contracted total of ${expected_accessorial_total:,.2f} for this "
                        "shipment's recorded accessorials."
                    ),
                    billed_amount=billed_accessorial_total,
                    expected_amount=expected_accessorial_total,
                    overcharge_amount=round(billed_accessorial_total - expected_accessorial_total, 2),
                    contract_evidence="; ".join(evidence_parts) if evidence_parts else "No accessorials on shipment record.",
                    invoice_evidence=line.source_text,
                )
            )

    if line_needs_review:
        for d in discrepancies:
            d.needs_review = True

    expected_total = expected_base + expected_fuel + expected_accessorial_total
    return discrepancies, expected_total


def run_audit(
    invoice_lines: list[InvoiceLineItem],
    shipments: list[Shipment],
    rate_cards: list[RateCard],
    accessorial_caps: dict[str, float],
    hourly_rules: dict[str, dict] | None = None,
) -> AuditResult:
    hourly_rules = hourly_rules or {}
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
            line, shipment, rate_card, accessorial_caps, hourly_rules
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
