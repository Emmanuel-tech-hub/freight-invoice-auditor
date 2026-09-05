from __future__ import annotations

import re
from pathlib import Path

from pydantic import BaseModel, Field

from app.models import RateCard, normalize_place
from app.parsers.kv_line import parse_kv_line
from app.parsers.pdf_text import extract_pdf_text


class ContractData(BaseModel):
    rate_cards: list[RateCard]
    accessorial_caps: dict[str, float] = Field(default_factory=dict)
    hourly_rules: dict[str, dict] = Field(default_factory=dict)
    # e.g. {"DETENTION": {"rate": 50.0, "free_units": 2.0}} for accessorials
    # billed per-unit (per hour) above a free allowance, rather than a flat cap.
    raw_text: str = ""


def _normalize_lane(raw: str) -> str:
    origin, sep, destination = raw.partition("->")
    if not sep:
        origin, sep, destination = raw.partition("-")
    return f"{normalize_place(origin)}-{normalize_place(destination)}"


def _parse_kv_contract_text(text: str) -> ContractData:
    """Parse the V1 structured `KEY: value | KEY: value` template."""
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


# ---------------------------------------------------------------------------
# "Natural" contract format: plain-English rate sentences, e.g.
#   Chicago, IL -> Dallas, TX: Base $1,200 | Fuel 8% | Residential $75 | Liftgate $60
#   Detention: $50/hour after first 2 free hours, only when documented.
# ---------------------------------------------------------------------------

_NATURAL_LANE_RE = re.compile(
    r"^(?P<origin>[^:|]+?)\s*->\s*(?P<dest>[^:|]+?)\s*:\s*Base\s*\$(?P<base>[\d,]+(?:\.\d+)?)"
    r"\s*\|\s*Fuel\s*(?P<fuel>[\d.]+)\s*%\s*(?P<rest>.*)$",
    re.IGNORECASE,
)
_NATURAL_FEE_RE = re.compile(r"^(?P<name>[A-Za-z][A-Za-z ]*?)\s*\$(?P<amount>[\d,]+(?:\.\d+)?)$")
_NATURAL_DETENTION_RE = re.compile(
    r"^Detention:\s*\$(?P<rate>[\d.]+)\s*/\s*hour\s+after\s+(?:the\s+)?first\s+(?P<free>[\d.]+)\s+free\s+hours",
    re.IGNORECASE,
)


def _parse_natural_contract_text(text: str) -> ContractData:
    rate_cards: list[RateCard] = []
    accessorial_caps: dict[str, float] = {}
    hourly_rules: dict[str, dict] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue

        m = _NATURAL_LANE_RE.match(line)
        if m:
            lane = f"{normalize_place(m.group('origin'))}-{normalize_place(m.group('dest'))}"
            rate_cards.append(
                RateCard(
                    lane=lane,
                    service_level="STANDARD",
                    rate_type="FLAT",
                    rate_value=float(m.group("base").replace(",", "")),
                    fuel_surcharge_pct=float(m.group("fuel")),
                    source_text=line,
                )
            )
            for part in m.group("rest").split("|"):
                part = part.strip()
                if not part:
                    continue
                fm = _NATURAL_FEE_RE.match(part)
                if fm:
                    code = fm.group("name").strip().upper().replace(" ", "_")
                    accessorial_caps[code] = float(fm.group("amount").replace(",", ""))
            continue

        dm = _NATURAL_DETENTION_RE.match(line)
        if dm:
            hourly_rules["DETENTION"] = {
                "rate": float(dm.group("rate")),
                "free_units": float(dm.group("free")),
            }

    return ContractData(
        rate_cards=rate_cards,
        accessorial_caps=accessorial_caps,
        hourly_rules=hourly_rules,
        raw_text=text,
    )


def parse_contract_text(text: str) -> ContractData:
    contract = _parse_kv_contract_text(text)
    if contract.rate_cards:
        return contract
    return _parse_natural_contract_text(text)


def parse_contract_pdf(path: str | Path) -> ContractData:
    text = extract_pdf_text(path)
    return parse_contract_text(text)
