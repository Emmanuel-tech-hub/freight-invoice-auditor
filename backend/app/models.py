"""Domain models shared across parsers, the matching engine, and the API."""
from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


def normalize_place(raw: str) -> str:
    """Normalize a place name for lane matching: drop any state/suffix after
    a comma (so "Chicago, IL" and "Chicago" both key to "CHICAGO"), since
    invoices don't always repeat the state carried in the contract/shipment
    records.
    """
    return raw.split(",")[0].strip().upper()


class AccessorialFee(BaseModel):
    code: str
    description: str
    amount: float


class RateCard(BaseModel):
    """A single contracted rate for a lane + service level, from a carrier contract."""

    lane: str  # normalized "ORIGIN-DESTINATION", e.g. "CHICAGO IL-DALLAS TX"
    service_level: str  # e.g. "LTL", "FTL", "GROUND", "EXPEDITED"
    rate_type: str  # "PER_CWT", "PER_MILE", "FLAT"
    rate_value: float
    minimum_charge: float = 0.0
    fuel_surcharge_pct: float = 0.0
    accessorial_caps: dict[str, float] = Field(default_factory=dict)
    source_text: str = ""  # raw contract line(s) this was extracted from, for evidence


class Shipment(BaseModel):
    shipment_id: str
    origin: str
    destination: str
    service_level: str
    weight_lbs: float
    miles: Optional[float] = None
    ship_date: Optional[str] = None
    accessorials: list[str] = Field(default_factory=list)
    accessorial_quantities: dict[str, float] = Field(default_factory=dict)
    # e.g. {"DETENTION": 3} hours, for accessorials billed per-unit rather than flat.

    @property
    def lane(self) -> str:
        return f"{normalize_place(self.origin)}-{normalize_place(self.destination)}"


class InvoiceLineItem(BaseModel):
    invoice_number: str
    shipment_id: str
    description: str = ""
    base_freight: float = 0.0
    fuel_surcharge: float = 0.0
    accessorial_charges: dict[str, float] = Field(default_factory=dict)
    accessorial_total: Optional[float] = None
    # Some invoices bill accessorials as one lump sum rather than itemized by
    # code. When set (and accessorial_charges is empty), the engine compares
    # this total against the sum of contracted accessorial charges implied by
    # the shipment record, instead of checking each code individually.
    billed_total: float = 0.0
    source_text: str = ""  # raw invoice line(s) this was extracted from, for evidence


class Discrepancy(BaseModel):
    shipment_id: str
    invoice_number: str
    lane: str
    service_level: str
    reason: str
    billed_amount: float
    expected_amount: float
    overcharge_amount: float
    contract_evidence: str
    invoice_evidence: str


class AuditResult(BaseModel):
    discrepancies: list[Discrepancy]
    total_billed: float
    total_expected: float
    total_overcharge: float
    shipments_audited: int
    shipments_with_discrepancies: int
    unmatched_shipment_ids: list[str] = Field(default_factory=list)
