"""Tier-2 contract extraction: used only when the exact structured templates
(contract_parser's KV-line and natural-sentence strategies) find nothing.

Unlike those, this doesn't match one fixed layout - it runs multiple general
strategies (table columns matched by header synonym, and free-text lane/rate
line scanning) driven by the terminology dictionary in synonyms.py, and
scores each candidate's confidence instead of assuming every match is
correct. A document that clearly isn't freight-related is distinguished from
one that is but couldn't be confidently parsed.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.models import RateCard, normalize_place
from app.parsers.numbers import find_amounts, find_first_amount, find_percent
from app.parsers.pdf_source import PdfSource
from app.parsers.synonyms import (
    BASE_RATE_RE,
    FUEL_RE,
    LANE_DEST_LABELS,
    LANE_ORIGIN_LABELS,
    MIN_CHARGE_RE,
    SERVICE_LEVEL_LABELS,
    find_accessorial_code,
    looks_like_freight_document,
)

LANE_ARROW_RE = re.compile(r"\s*(?:->|-->|—|–|→)\s*")
# A "place-ish" token: capitalized word(s), optionally with a state/comma tail.
_PLACE = r"[A-Z][A-Za-z.]+(?:[ ,]\s*[A-Za-z.]{2,})*"
LANE_ARROW_LINE_RE = re.compile(rf"(?P<origin>{_PLACE})\s*(?:->|-->|—|–|→)\s*(?P<dest>{_PLACE})")
LANE_TO_LINE_RE = re.compile(rf"(?P<origin>{_PLACE})\s+to\s+(?P<dest>{_PLACE})")

PER_MILE_RE = re.compile(r"per\s*mile|/\s*mile\b|/\s*mi\b|\bmileage\b", re.IGNORECASE)
PER_CWT_RE = re.compile(r"per\s*cwt|hundredweight|/\s*cwt\b", re.IGNORECASE)

MAX_LOOKAHEAD_CHARS = 60


@dataclass
class HeuristicContractResult:
    rate_cards: list[RateCard] = field(default_factory=list)
    accessorial_caps: dict[str, float] = field(default_factory=dict)
    document_classification: str = "not_a_contract"  # "rate_card" | "unclear" | "not_a_contract"


def _rate_type_near(text: str) -> str:
    if PER_MILE_RE.search(text):
        return "PER_MILE"
    if PER_CWT_RE.search(text):
        return "PER_CWT"
    return "FLAT"


def _amount_after(text: str, label_match: re.Match) -> float | None:
    window = text[label_match.end() : label_match.end() + MAX_LOOKAHEAD_CHARS]
    return find_first_amount(window)


def _service_level_near(text: str) -> str:
    for label in SERVICE_LEVEL_LABELS:
        m = re.search(re.escape(label) + r"\s*[:\-]?\s*([A-Za-z]{2,12})", text, re.IGNORECASE)
        if m:
            return m.group(1).upper()
    return "STANDARD"


def _scan_line_for_lane_rate(line: str, page_number: int) -> tuple[RateCard, dict[str, float]] | None:
    base_match = BASE_RATE_RE.search(line)
    if not base_match:
        return None

    arrow_match = LANE_ARROW_LINE_RE.search(line)
    lane_confidence_bonus = 0.0
    lane_match = arrow_match
    if lane_match is None:
        lane_match = LANE_TO_LINE_RE.search(line)
        lane_confidence_bonus = -0.2  # "to" is a much weaker lane signal than an arrow
    if lane_match is None:
        return None

    base_amount = _amount_after(line, base_match)
    if base_amount is None:
        return None

    fuel_match = FUEL_RE.search(line)
    fuel_pct = find_percent(line[fuel_match.end():]) if fuel_match else None
    if fuel_pct is None:
        fuel_pct = 0.0

    min_match = MIN_CHARGE_RE.search(line)
    min_charge = _amount_after(line, min_match) if min_match else 0.0

    accessorial_caps: dict[str, float] = {}
    for m in re.finditer(r"[A-Za-z][A-Za-z .]{2,30}?(?=\s*\$)", line):
        code = find_accessorial_code(m.group(0))
        if code:
            amount = find_first_amount(line[m.end():m.end() + 20])
            if amount is not None:
                accessorial_caps[code] = amount

    specific_label = base_match.group(0).lower() not in ("rate",)
    confidence = (0.85 if specific_label else 0.65) + lane_confidence_bonus
    confidence = max(0.3, min(confidence, 0.95))

    rate_card = RateCard(
        lane=f"{normalize_place(lane_match.group('origin'))}-{normalize_place(lane_match.group('dest'))}",
        service_level=_service_level_near(line),
        rate_type=_rate_type_near(line),
        rate_value=base_amount,
        minimum_charge=min_charge or 0.0,
        fuel_surcharge_pct=fuel_pct,
        source_text=line.strip(),
        source_page=page_number,
        confidence=round(confidence, 2),
        extraction_method="heuristic",
        accessorial_caps=dict(accessorial_caps),
    )
    return rate_card, accessorial_caps


def _line_scan_strategy(source: PdfSource) -> list[tuple[RateCard, dict[str, float]]]:
    results = []
    for page in source.pages:
        for raw_line in page.text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            hit = _scan_line_for_lane_rate(line, page.page_number)
            if hit:
                results.append(hit)
    return results


# ---------------------------------------------------------------------------
# Block-scan strategy: some contracts stack one "Origin: / Destination: /
# Rate: / Fuel: ..." label-value pair per line rather than packing a whole
# lane onto one line. Group consecutive lines into blocks (split on blank
# lines, or when a new "Lane"/"Origin:" line starts while the current block
# already has one) and pool label:value pairs across the whole block.
# ---------------------------------------------------------------------------

_LABEL_VALUE_RE = re.compile(r"^([A-Za-z][A-Za-z /]{2,40}?)\s*[:\-]\s*(.+)$")
_BLOCK_START_RE = re.compile(r"^(lane\b|origin\s*[:\-])", re.IGNORECASE)


def _split_into_blocks(text: str) -> list[list[str]]:
    blocks: list[list[str]] = []
    current: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            if current:
                blocks.append(current)
                current = []
            continue
        starts_new = _BLOCK_START_RE.match(line) and any(
            re.match(r"^origin\s*[:\-]", existing, re.IGNORECASE) for existing in current
        )
        if starts_new:
            blocks.append(current)
            current = []
        current.append(line)
    if current:
        blocks.append(current)
    return blocks


def _scan_block_for_lane_rate(block_lines: list[str], page_number: int) -> tuple[RateCard, dict[str, float]] | None:
    origin = dest = None
    base_amount = None
    fuel_pct = 0.0
    min_charge = 0.0
    accessorial_caps: dict[str, float] = {}

    for line in block_lines:
        arrow_m = LANE_ARROW_LINE_RE.search(line)
        if arrow_m and origin is None:
            origin, dest = arrow_m.group("origin"), arrow_m.group("dest")
            continue

        lv = _LABEL_VALUE_RE.match(line)
        if not lv:
            continue
        label, value = lv.group(1).strip().lower(), lv.group(2).strip()

        if origin is None and any(term in label for term in LANE_ORIGIN_LABELS):
            origin = value
        elif dest is None and any(term in label for term in LANE_DEST_LABELS):
            dest = value
        elif base_amount is None and BASE_RATE_RE.search(label):
            base_amount = find_first_amount(value)
        elif FUEL_RE.search(label):
            pct = find_percent(value)
            if pct is not None:
                fuel_pct = pct
        elif MIN_CHARGE_RE.search(label):
            min_charge = find_first_amount(value) or 0.0
        else:
            code = find_accessorial_code(label)
            if code:
                amount = find_first_amount(value)
                if amount is not None:
                    accessorial_caps[code] = amount

    if not origin or not dest or base_amount is None:
        return None

    joined = " | ".join(block_lines)
    rate_card = RateCard(
        lane=f"{normalize_place(origin)}-{normalize_place(dest)}",
        service_level=_service_level_near(joined),
        rate_type=_rate_type_near(joined),
        rate_value=base_amount,
        minimum_charge=min_charge,
        fuel_surcharge_pct=fuel_pct,
        source_text=joined,
        source_page=page_number,
        confidence=0.8,
        extraction_method="heuristic",
        accessorial_caps=dict(accessorial_caps),
    )
    return rate_card, accessorial_caps


def _block_scan_strategy(source: PdfSource) -> list[tuple[RateCard, dict[str, float]]]:
    results = []
    for page in source.pages:
        for block in _split_into_blocks(page.text):
            hit = _scan_block_for_lane_rate(block, page.page_number)
            if hit:
                results.append(hit)
    return results


def _looks_like_header_row(row: list[str | None]) -> bool:
    cells = [c for c in row if c]
    if not cells:
        return False
    numeric_like = sum(1 for c in cells if re.fullmatch(r"[\d.,$%\s-]+", c))
    return numeric_like <= len(cells) / 2


def _map_header_cell(cell: str) -> str | None:
    low = cell.strip().lower()
    if not low:
        return None
    if any(term in low for term in LANE_ORIGIN_LABELS):
        return "ORIGIN"
    if any(term in low for term in LANE_DEST_LABELS):
        return "DEST"
    if "lane" in low or "route" in low:
        return "LANE"
    if any(term in low for term in SERVICE_LEVEL_LABELS):
        return "SERVICE"
    accessorial_code = find_accessorial_code(low)
    if accessorial_code:
        return f"ACCESSORIAL:{accessorial_code}"
    if FUEL_RE.search(low):
        return "FUEL"
    if MIN_CHARGE_RE.search(low):
        return "MIN_CHARGE"
    if BASE_RATE_RE.search(low):
        return "BASE_RATE"
    return None


def _table_strategy(source: PdfSource) -> list[tuple[RateCard, dict[str, float]]]:
    results = []
    for page in source.pages:
        for table in page.tables:
            if len(table) < 2 or not _looks_like_header_row(table[0]):
                continue

            column_map: dict[int, str] = {}
            for idx, cell in enumerate(table[0]):
                mapped = _map_header_cell(cell or "")
                if mapped:
                    column_map[idx] = mapped

            has_lane = "LANE" in column_map.values() or (
                "ORIGIN" in column_map.values() and "DEST" in column_map.values()
            )
            if not has_lane or "BASE_RATE" not in column_map.values():
                continue

            base_rate_col_idx = next(i for i, v in column_map.items() if v == "BASE_RATE")
            base_rate_header = table[0][base_rate_col_idx] or ""

            for row in table[1:]:
                cells = {column_map[i]: (row[i] or "").strip() for i in column_map if i < len(row)}

                if "LANE" in cells:
                    lane_match = LANE_ARROW_LINE_RE.search(cells["LANE"]) or LANE_TO_LINE_RE.search(cells["LANE"])
                    if not lane_match:
                        continue
                    origin, dest = lane_match.group("origin"), lane_match.group("dest")
                else:
                    origin, dest = cells.get("ORIGIN", ""), cells.get("DEST", "")
                if not origin or not dest:
                    continue

                base_amount = find_first_amount(cells.get("BASE_RATE", "")) or _loose_cell_number(
                    cells.get("BASE_RATE", "")
                )
                if base_amount is None:
                    continue

                fuel_pct = find_percent(cells.get("FUEL", "")) or 0.0
                min_charge = find_first_amount(cells.get("MIN_CHARGE", "")) or 0.0

                accessorial_caps = {}
                for key, value in cells.items():
                    if key.startswith("ACCESSORIAL:"):
                        amount = find_first_amount(value) or _loose_cell_number(value)
                        if amount is not None:
                            accessorial_caps[key.split(":", 1)[1]] = amount

                row_text = " | ".join(f"{k}: {v}" for k, v in cells.items())
                rate_card = RateCard(
                    lane=f"{normalize_place(origin)}-{normalize_place(dest)}",
                    service_level=(cells.get("SERVICE") or "STANDARD").upper(),
                    rate_type=_rate_type_near(base_rate_header + " " + cells.get("BASE_RATE", "") + " " + row_text),
                    rate_value=base_amount,
                    minimum_charge=min_charge,
                    fuel_surcharge_pct=fuel_pct,
                    source_text=row_text,
                    source_page=page.page_number,
                    confidence=0.9,
                    extraction_method="heuristic",
                    accessorial_caps=dict(accessorial_caps),
                )
                results.append((rate_card, accessorial_caps))
    return results


def _loose_cell_number(text: str) -> float | None:
    m = re.search(r"-?[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None


def extract_contract_heuristically(source: PdfSource) -> HeuristicContractResult:
    candidates = _table_strategy(source) + _line_scan_strategy(source) + _block_scan_strategy(source)

    best_by_key: dict[tuple[str, str], tuple[RateCard, dict[str, float]]] = {}
    for rate_card, caps in candidates:
        key = (rate_card.lane, rate_card.service_level)
        existing = best_by_key.get(key)
        if existing is None or rate_card.confidence > existing[0].confidence:
            best_by_key[key] = (rate_card, caps)

    rate_cards = [rc for rc, _ in best_by_key.values()]
    accessorial_caps: dict[str, float] = {}
    for _, caps in best_by_key.values():
        accessorial_caps.update(caps)

    if rate_cards:
        classification = "rate_card"
    elif looks_like_freight_document(source.full_text):
        classification = "unclear"
    else:
        classification = "not_a_contract"

    return HeuristicContractResult(
        rate_cards=rate_cards,
        accessorial_caps=accessorial_caps,
        document_classification=classification,
    )
