from __future__ import annotations

"""Central parser for wishlist text directives.

Goal
----
Keep the product rules consistent across *all* sources by parsing any
"human" directives (year/price) from the wishlist query into structured
filters.

This module is intentionally lightweight (regex only) to run 24/7 on
Raspberry Pi.

Why it exists
-------------
Historically, some wishlists were stored with directives inside the query
string (e.g. "audi a6 entre 2014 e 2020"). If the directive isn't parsed
and persisted as filters, matching becomes inconsistent and fragile.

By centralizing parsing here and reusing it in:
  - wishlist creation (persist filters)
  - matching (derive filters for legacy wishlists)
  - matchdebug explanations

we guarantee identical behavior across all sources.
"""

import re
from dataclasses import dataclass
from typing import Optional


@dataclass(frozen=True)
class ParsedWishlist:
    cleaned_query: str
    year_min: Optional[int] = None
    year_max: Optional[int] = None
    price_min: Optional[int] = None
    price_max: Optional[int] = None


# ---------------------------------------------------------------------------
# Regex patterns
# ---------------------------------------------------------------------------

# Year
_YEAR_MAX_PATTERNS = [
    re.compile(r"(?:\bate\b|\baté\b)\s+(\d{4})", re.IGNORECASE),
    re.compile(r"(?:\bate\b|\baté\b)\s+ano\s+(\d{4})", re.IGNORECASE),
    re.compile(r"\bano\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
    re.compile(r"\byear\s*(?:<=|=<|≤)\s*(\d{4})", re.IGNORECASE),
]

_YEAR_MIN_PATTERNS = [
    re.compile(r"\b(?:a\s+partir\s+de|apartir\s+de|desde)\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\bano\s*(?:>=|=>|≥)\s*(\d{4})\b", re.IGNORECASE),
    re.compile(r"\byear\s*(?:>=|=>|≥)\s*(\d{4})\b", re.IGNORECASE),
]

_YEAR_RANGE_PATTERNS = [
    re.compile(r"\bentre\s+(\d{4})\s+e\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\bde\s+(\d{4})\s+a\s+(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})\s*(?:\bate\b|\baté\b)\s*(\d{4})\b", re.IGNORECASE),
    re.compile(r"\b(\d{4})\s*(?:-|–|—)\s*(\d{4})\b", re.IGNORECASE),
]

# Price (BRL)
_PRICE_RANGE_PATTERNS = [
    re.compile(
        r"\bentre\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\s+e\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bde\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\s+a\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b([0-9\.,]+\s*[kKmM]?)\s*(?:-|–|—)\s*([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]

_PRICE_MAX_PATTERNS = [
    re.compile(r"\b(?:ate|até)\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:preco|preço|valor|price)\s*(?:<=|=<|≤)\s*(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]

_PRICE_MIN_PATTERNS = [
    re.compile(r"\b(?:a\s+partir\s+de|apartir\s+de|desde)\s+(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b", re.IGNORECASE),
    re.compile(
        r"\b(?:preco|preço|valor|price)\s*(?:>=|=>|≥)\s*(?:r\$\s*)?([0-9\.,]+\s*[kKmM]?)\b",
        re.IGNORECASE,
    ),
]


def _clean_span(q: str, start: int, end: int) -> str:
    q = (q[:start] + " " + q[end:]).strip()
    q = re.sub(r"\s+", " ", q).strip()
    return q


def _parse_human_money_to_int(raw: str) -> Optional[int]:
    """Convert '200k', '1.2m', '120.000', 'R$ 80.000' -> integer."""
    if not raw:
        return None

    s = raw.strip().lower()
    s = s.replace("r$", "").strip()
    s = re.sub(r"\s+", "", s)

    mult = 1
    if s.endswith("k"):
        mult = 1_000
        s = s[:-1]
    elif s.endswith("m"):
        mult = 1_000_000
        s = s[:-1]

    # '90.000' style
    s = s.replace(".", "") if re.search(r"\d\.\d{3}", s) else s
    s = s.replace(",", ".")
    s = re.sub(r"[^0-9\.]+", "", s)
    if not s:
        return None

    try:
        num = float(s)
    except Exception:
        return None

    if num <= 0:
        return None

    v = int(round(num * mult))
    return v if v > 0 else None


def _is_plausible_price(v: int) -> bool:
    return 1 <= v <= 9_999_999_999


def parse_wishlist_query(query: str) -> ParsedWishlist:
    """Parse a wishlist free-text query into cleaned query + directives.

    Contract:
    - year directives are **inclusive** (min=>gte, max=>lte)
    - price directives are **inclusive**
    """
    q = (query or "").strip()
    if not q:
        return ParsedWishlist(cleaned_query="")

    # --- Year directives ---
    year_min: Optional[int] = None
    year_max: Optional[int] = None

    for rx in _YEAR_RANGE_PATTERNS:
        m = rx.search(q)
        if not m:
            continue
        try:
            y1 = int(m.group(1))
            y2 = int(m.group(2))
        except Exception:
            y1 = y2 = None
        if y1 and y2 and 1900 <= y1 <= 2100 and 1900 <= y2 <= 2100:
            year_min, year_max = (y1, y2) if y1 <= y2 else (y2, y1)
            q = _clean_span(q, m.start(), m.end())
            break

    if year_max is None:
        for rx in _YEAR_MAX_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            try:
                y = int(m.group(1))
            except Exception:
                y = None
            if y and 1900 <= y <= 2100:
                year_max = y
                q = _clean_span(q, m.start(), m.end())
                break

    if year_min is None:
        for rx in _YEAR_MIN_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            try:
                y = int(m.group(1))
            except Exception:
                y = None
            if y and 1900 <= y <= 2100:
                year_min = y
                q = _clean_span(q, m.start(), m.end())
                break

    # --- Price directives ---
    price_min: Optional[int] = None
    price_max: Optional[int] = None

    for rx in _PRICE_RANGE_PATTERNS:
        m = rx.search(q)
        if not m:
            continue
        v1 = _parse_human_money_to_int(m.group(1) or "")
        v2 = _parse_human_money_to_int(m.group(2) or "")
        if not v1 or not v2:
            continue
        if not (_is_plausible_price(v1) and _is_plausible_price(v2)):
            continue
        price_min, price_max = (v1, v2) if v1 <= v2 else (v2, v1)
        q = _clean_span(q, m.start(), m.end())
        break

    if price_max is None:
        for rx in _PRICE_MAX_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            raw = (m.group(1) or "").strip()
            v = _parse_human_money_to_int(raw)
            # Avoid confusing "até 2020" with price
            if v is None and raw.isdigit() and len(raw) == 4:
                continue
            if v and _is_plausible_price(v):
                price_max = v
                q = _clean_span(q, m.start(), m.end())
                break

    if price_min is None:
        for rx in _PRICE_MIN_PATTERNS:
            m = rx.search(q)
            if not m:
                continue
            raw = (m.group(1) or "").strip()
            v = _parse_human_money_to_int(raw)
            if v and _is_plausible_price(v):
                price_min = v
                q = _clean_span(q, m.start(), m.end())
                break

    q = re.sub(r"\s+", " ", (q or "")).strip()
    return ParsedWishlist(cleaned_query=q, year_min=year_min, year_max=year_max, price_min=price_min, price_max=price_max)
