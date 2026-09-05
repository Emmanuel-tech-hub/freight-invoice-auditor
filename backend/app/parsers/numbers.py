"""Robust currency/percentage parsing for heuristic extraction, tolerant of
the number-formatting variation real documents use: `$1,200`, `1200.00`,
`USD 1,200.00`, `1.2K` is NOT handled (ambiguous), but comma thousands
separators, optional `$`/`USD`, and trailing `.00` all are.
"""
from __future__ import annotations

import re
from typing import Optional

_AMOUNT_RE = re.compile(r"(?:USD|US\$|\$)\s*(-?[\d,]+(?:\.\d{1,2})?)|(-?[\d,]+(?:\.\d{2}))\b")
_PERCENT_RE = re.compile(r"(-?[\d]+(?:\.\d+)?)\s*%")


def find_amounts(text: str) -> list[float]:
    """Find dollar-like amounts in text, in order of appearance. Requires
    either a currency marker ($/USD) or a decimal cents component, so bare
    integers (weights, hours, piece counts) aren't misread as dollars.
    """
    amounts: list[float] = []
    for m in _AMOUNT_RE.finditer(text):
        raw = m.group(1) or m.group(2)
        if raw is None:
            continue
        try:
            amounts.append(float(raw.replace(",", "")))
        except ValueError:
            continue
    return amounts


def find_first_amount(text: str) -> Optional[float]:
    amounts = find_amounts(text)
    return amounts[0] if amounts else None


def find_percent(text: str) -> Optional[float]:
    m = _PERCENT_RE.search(text)
    if not m:
        return None
    try:
        return float(m.group(1))
    except ValueError:
        return None


def find_loose_number(text: str) -> Optional[float]:
    """Like find_first_amount, but also accepts a bare integer/decimal with
    no currency marker (e.g. a table cell that's just "1200"). Use only once
    context (a recognized rate/fee label) already justifies treating the
    cell as a monetary value.
    """
    amount = find_first_amount(text)
    if amount is not None:
        return amount
    m = re.search(r"-?[\d,]+(?:\.\d+)?", text)
    if not m:
        return None
    try:
        return float(m.group(0).replace(",", ""))
    except ValueError:
        return None
