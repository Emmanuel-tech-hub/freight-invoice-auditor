"""Freight-industry terminology synonyms, used by the heuristic extractors so
they recognize a concept ("base rate") regardless of which word a given
carrier's document uses for it ("linehaul", "freight rate", "flat rate"...).

This is intentionally a plain data file: adding a carrier's house terminology
for something is a one-line addition here, not a new parsing strategy.
"""
from __future__ import annotations

import re

BASE_RATE_TERMS = [
    "base rate", "base freight", "linehaul", "line haul", "freight rate",
    "flat rate", "line-haul rate", "base charge", "freight charge",
    "transportation charge", "shipping rate", "rate",
]

FUEL_TERMS = [
    "fuel surcharge", "fuel adjustment", "fsc", "f.s.c.", "fuel",
]

MIN_CHARGE_TERMS = [
    "minimum charge", "minimum freight", "min charge", "minimum",
]

TOTAL_TERMS = [
    "total due", "amount due", "grand total", "invoice total", "total charges",
    "total",
]

# Canonical accessorial code -> terminology variants a carrier might use.
ACCESSORIAL_TERMS: dict[str, list[str]] = {
    "LIFTGATE": ["liftgate", "lift gate", "tailgate service"],
    "RESIDENTIAL": ["residential delivery", "residential", "home delivery", "res delivery"],
    "DETENTION": ["detention", "driver detention", "wait time", "waiting time"],
    "LAYOVER": ["layover", "lay over"],
    "INSIDE_DELIVERY": ["inside delivery", "white glove delivery", "white glove"],
    "APPOINTMENT": ["appointment fee", "delivery appointment", "appointment"],
    "REDELIVERY": ["redelivery", "re-delivery attempt", "failed delivery attempt"],
    "STORAGE": ["storage fee", "warehouse storage", "storage"],
    "OVERWEIGHT": ["overweight fee", "overweight"],
    "HAZMAT": ["hazmat fee", "hazardous materials fee", "hazmat"],
}

# Words whose presence anywhere in a document suggests it's freight/logistics
# related at all, used to distinguish "not a contract" from "a contract we
# just couldn't confidently extract rates from".
FREIGHT_DOMAIN_TERMS = [
    "carrier", "shipment", "shipper", "freight", "rate card", "tariff",
    "lane", "linehaul", "accessorial", "fuel surcharge", "bol", "ltl", "ftl",
    "consignee", "logistics", "cwt", "hundredweight",
]

LANE_ORIGIN_LABELS = ["origin", "from", "pickup", "pu location", "ship from"]
LANE_DEST_LABELS = ["destination", "to", "delivery", "drop", "ship to"]
SERVICE_LEVEL_LABELS = ["service", "service level", "mode", "service type"]


def _compile(phrases: list[str]) -> re.Pattern:
    escaped = sorted((re.escape(p) for p in phrases), key=len, reverse=True)
    return re.compile(r"\b(" + "|".join(escaped) + r")\b", re.IGNORECASE)


BASE_RATE_RE = _compile(BASE_RATE_TERMS)
FUEL_RE = _compile(FUEL_TERMS)
MIN_CHARGE_RE = _compile(MIN_CHARGE_TERMS)
TOTAL_RE = _compile(TOTAL_TERMS)
FREIGHT_DOMAIN_RE = _compile(FREIGHT_DOMAIN_TERMS)

ACCESSORIAL_RE_BY_CODE: dict[str, re.Pattern] = {
    code: _compile(terms) for code, terms in ACCESSORIAL_TERMS.items()
}


def find_accessorial_code(label: str) -> str | None:
    """Match a free-text label (e.g. a table column header or line prefix)
    to a canonical accessorial code, or None if it doesn't match any known
    term.
    """
    for code, pattern in ACCESSORIAL_RE_BY_CODE.items():
        if pattern.search(label):
            return code
    return None


def looks_like_freight_document(text: str) -> bool:
    return bool(FREIGHT_DOMAIN_RE.search(text))
