"""Shipment CSV parsing, driven by a column-name synonym map rather than one
fixed header set - "Wt (lbs)", "Weight_LB", and "weight_lbs" all resolve to
the same canonical field. Only shipment id / origin / destination are
required; everything else (service level, weight, accessorial flags) is
used if present and defaulted sensibly if not.
"""
from __future__ import annotations

import csv
import re
from pathlib import Path

from app.models import Shipment

# canonical field -> normalized header variants that mean it.
_COLUMN_SYNONYMS: dict[str, list[str]] = {
    "SHIPMENT_ID": ["shipment id", "shipment", "shipment no", "id", "pro", "pro no", "reference", "ref", "bol", "bol no"],
    "ORIGIN": ["origin", "from", "pickup", "pu", "ship from", "origin city"],
    "DESTINATION": ["destination", "to", "delivery", "dest", "ship to", "destination city"],
    "SERVICE_LEVEL": ["service level", "service", "mode", "svc"],
    "WEIGHT_LBS": ["weight lbs", "weight", "weight lb", "wt", "wt lbs", "gross weight", "weight in lbs"],
    "MILES": ["miles", "mileage", "distance"],
    "SHIP_DATE": ["ship date", "date", "pickup date"],
    "ACCESSORIALS": ["accessorials", "accessorial", "accessorial codes", "extras"],
    "DELIVERY_TYPE": ["delivery type"],
    "LIFTGATE": ["liftgate", "lift gate"],
    "DETENTION_HOURS": ["detention hours", "detention"],
}


def _normalize_header(raw: str) -> str:
    text = (raw or "").strip().lower().replace("_", " ")
    text = re.sub(r"[^a-z0-9 ]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


_HEADER_LOOKUP: dict[str, str] = {
    _normalize_header(variant): field
    for field, variants in _COLUMN_SYNONYMS.items()
    for variant in variants
}

REQUIRED_FIELDS = {"SHIPMENT_ID", "ORIGIN", "DESTINATION"}


def _build_column_map(fieldnames: list[str]) -> dict[str, str]:
    """Returns {raw_header: canonical_field} for headers we recognize."""
    column_map = {}
    for raw in fieldnames:
        canonical = _HEADER_LOOKUP.get(_normalize_header(raw))
        if canonical:
            column_map[raw] = canonical
    return column_map


def _row_by_canonical(row: dict[str, str], column_map: dict[str, str]) -> dict[str, str]:
    return {canonical: row.get(raw, "").strip() for raw, canonical in column_map.items()}


def _parse_row(fields: dict[str, str]) -> Shipment:
    accessorials: list[str] = []
    quantities: dict[str, float] = {}

    if fields.get("ACCESSORIALS"):
        accessorials.extend(a.strip().upper() for a in re.split(r"[;,]", fields["ACCESSORIALS"]) if a.strip())

    if fields.get("DELIVERY_TYPE", "").lower() == "residential":
        accessorials.append("RESIDENTIAL")

    liftgate = fields.get("LIFTGATE", "").lower()
    if liftgate and liftgate not in ("none", "no", "false", "0"):
        accessorials.append("LIFTGATE")

    detention_hours = float(fields.get("DETENTION_HOURS") or 0)
    if detention_hours > 0:
        accessorials.append("DETENTION")
        quantities["DETENTION"] = detention_hours

    miles_raw = fields.get("MILES", "")

    return Shipment(
        shipment_id=fields["SHIPMENT_ID"],
        origin=fields["ORIGIN"],
        destination=fields["DESTINATION"],
        service_level=(fields.get("SERVICE_LEVEL") or "STANDARD").upper(),
        weight_lbs=float(fields.get("WEIGHT_LBS") or 0),
        miles=float(miles_raw) if miles_raw else None,
        ship_date=fields.get("SHIP_DATE") or None,
        accessorials=accessorials,
        accessorial_quantities=quantities,
    )


def parse_shipment_csv(path: str | Path) -> list[Shipment]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        raw_fieldnames = [name for name in (reader.fieldnames or []) if name]
        rows = list(reader)

    column_map = _build_column_map(raw_fieldnames)
    found_fields = set(column_map.values())
    missing = REQUIRED_FIELDS - found_fields
    if missing:
        raise ValueError(
            f"shipments.csv is missing columns for: {sorted(m.lower() for m in missing)}. "
            f"Recognized columns: {sorted(raw_fieldnames)}"
        )

    shipments: list[Shipment] = []
    for row in rows:
        fields = _row_by_canonical(row, column_map)
        if not fields.get("SHIPMENT_ID"):
            continue
        shipments.append(_parse_row(fields))

    return shipments
