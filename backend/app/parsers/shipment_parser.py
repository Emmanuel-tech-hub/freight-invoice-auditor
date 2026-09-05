from __future__ import annotations

import csv
from pathlib import Path

from app.models import Shipment

REQUIRED_COLUMNS = {"shipment_id", "origin", "destination", "service_level", "weight_lbs"}

# An alternate schema seen in the wild: no explicit service_level or itemized
# accessorials column; instead delivery_type/liftgate/detention_hours flag
# which accessorials apply, and the engine derives their contracted cost.
ALT_REQUIRED_COLUMNS = {"shipment_id", "origin", "destination", "weight_lb"}


def _read_rows(path: str | Path) -> tuple[set[str], list[dict[str, str]]]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
        rows = [
            {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
            for row in reader
        ]
    return fieldnames, rows


def _parse_standard_rows(rows: list[dict[str, str]]) -> list[Shipment]:
    shipments: list[Shipment] = []
    for row in rows:
        if not row.get("shipment_id"):
            continue

        accessorials_raw = row.get("accessorials", "")
        accessorials = [a.strip().upper() for a in accessorials_raw.split(";") if a.strip()]
        miles_raw = row.get("miles", "")

        shipments.append(
            Shipment(
                shipment_id=row["shipment_id"],
                origin=row["origin"],
                destination=row["destination"],
                service_level=row["service_level"].upper(),
                weight_lbs=float(row["weight_lbs"] or 0),
                miles=float(miles_raw) if miles_raw else None,
                ship_date=row.get("ship_date") or None,
                accessorials=accessorials,
            )
        )
    return shipments


def _parse_alt_rows(rows: list[dict[str, str]]) -> list[Shipment]:
    shipments: list[Shipment] = []
    for row in rows:
        if not row.get("shipment_id"):
            continue

        accessorials: list[str] = []
        quantities: dict[str, float] = {}

        if row.get("delivery_type", "").strip().lower() == "residential":
            accessorials.append("RESIDENTIAL")

        liftgate = row.get("liftgate", "").strip().lower()
        if liftgate and liftgate not in ("none", "no", "false", "0"):
            accessorials.append("LIFTGATE")

        detention_hours = float(row.get("detention_hours") or 0)
        if detention_hours > 0:
            accessorials.append("DETENTION")
            quantities["DETENTION"] = detention_hours

        shipments.append(
            Shipment(
                shipment_id=row["shipment_id"],
                origin=row["origin"],
                destination=row["destination"],
                service_level="STANDARD",
                weight_lbs=float(row.get("weight_lb") or 0),
                ship_date=row.get("ship_date") or None,
                accessorials=accessorials,
                accessorial_quantities=quantities,
            )
        )
    return shipments


def parse_shipment_csv(path: str | Path) -> list[Shipment]:
    fieldnames, rows = _read_rows(path)

    if REQUIRED_COLUMNS <= fieldnames:
        return _parse_standard_rows(rows)
    if ALT_REQUIRED_COLUMNS <= fieldnames:
        return _parse_alt_rows(rows)

    missing = REQUIRED_COLUMNS - fieldnames
    raise ValueError(f"shipments.csv is missing required columns: {sorted(missing)}")
