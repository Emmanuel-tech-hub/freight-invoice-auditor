from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, Field

from app.models import RateCard
from app.parsers.kv_line import parse_kv_line
from app.parsers.pdf_text import extract_pdf_text


class ContractData(BaseModel):
    rate_cards: list[RateCard]
    accessorial_caps: dict[str, float] = Field(default_factory=dict)
    raw_text: str = ""


def _normalize_lane(raw: str) -> str:
    origin, sep, destination = raw.partition("->")
    if not sep:
        origin, sep, destination = raw.partition("-")
    return f"{origin.strip().upper()}-{destination.strip().upper()}"


def parse_contract_text(text: str) -> ContractData:
    rate_cards: list[RateCard] = []
    accessorial_caps: dict[str, float] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        if line.upper().startswith("LANE:"):
            fields = parse_kv_line(line)
            try:
                rate_cards.append(
                    RateCard(
                        lane=_normalize_lane(fields.get("LANE", "")),
                        service_level=fields.get("SERVICE", "").upper(),
                        rate_type=fields.get("RATE_TYPE", "").upper(),
                        rate_value=float(fields.get("RATE", 0) or 0),
                        minimum_charge=float(fields.get("MIN_CHARGE", 0) or 0),
                        fuel_surcharge_pct=float(fields.get("FUEL_SURCHARGE_PCT", 0) or 0),
                        source_text=line,
                    )
                )
            except ValueError:
                continue

        elif line.upper().startswith("CODE:"):
            fields = parse_kv_line(line)
            code = fields.get("CODE", "").upper()
            amount = fields.get("MAX_AMOUNT")
            if code and amount is not None:
                try:
                    accessorial_caps[code] = float(amount)
                except ValueError:
                    continue

    return ContractData(rate_cards=rate_cards, accessorial_caps=accessorial_caps, raw_text=text)


def parse_contract_pdf(path: str | Path) -> ContractData:
    text = extract_pdf_text(path)
    return parse_contract_text(text)
