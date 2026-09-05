from __future__ import annotations

import csv
from pathlib import Path

from app.models import Shipment

REQUIRED_COLUMNS = {"shipment_id", "origin", "destination", "service_level", "weight_lbs"}


def parse_shipment_csv(path: str | Path) -> list[Shipment]:
    shipments: list[Shipment] = []

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        fieldnames = {(name or "").strip().lower() for name in (reader.fieldnames or [])}
        missing = REQUIRED_COLUMNS - fieldnames
        if missing:
            raise ValueError(f"shipments.csv is missing required columns: {sorted(missing)}")

        for row in reader:
            row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
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
