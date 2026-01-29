# app/bot/listing_display.py
from __future__ import annotations

import re
from typing import Any, Dict, Optional


KM_RE = re.compile(r"(\d{1,3}(?:\.\d{3})+|\d{1,7})\s*km\b", re.IGNORECASE)
FUEL_WORDS_RE = re.compile(r"\b(gasolina|etanol|flex|diesel|gnv|h[ií]brido|el[eé]trico)\b", re.IGNORECASE)
GEARBOX_WORDS_RE = re.compile(r"\b(mec[aâ]nico|manual|autom[aá]tico|cvt|tiptronic)\b", re.IGNORECASE)


def _norm_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _strip_trailing_punct(s: str) -> str:
    return re.sub(r"[,\-–—\s]+$", "", (s or "").strip())


def _extract_km(text: str) -> Optional[str]:
    """
    Return KM as string like '223.000' or '223000' (keeps dots if present).
    """
    text = text or ""
    m = KM_RE.search(text)
    if not m:
        return None
    return m.group(1)


def clean_title_remove_fuel_gearbox(title: str) -> str:
    """
    Remove fuel + gearbox words from title (temporary requirement).
    Also removes isolated 'km' chunks from title if any.
    """
    t = _norm_spaces(title)

    # remove "223.000 km" from title
    t = KM_RE.sub("", t)

    # remove fuel/gearbox words
    t = FUEL_WORDS_RE.sub("", t)
    t = GEARBOX_WORDS_RE.sub("", t)

    # cleanup duplicated spaces/punctuation
    t = _norm_spaces(t)
    t = re.sub(r"\s+([,;:/\-\–—])", r"\1", t)
    t = re.sub(r"([,;:/\-\–—])\s+", r"\1 ", t)
    t = _strip_trailing_punct(t)
    return t


def normalize_location(raw_location: str) -> str:
    """
    Ensure location is only 'Cidade-UF' (no 'km', fuel, gearbox).
    Accepts things like:
    - 'km Gasolina Mecânico Curitiba-PR'
    - 'Curitiba , PR'
    - 'Curitiba , PR ' etc
    """
    s = _norm_spaces(raw_location)

    # remove km chunk
    s = KM_RE.sub("", s)

    # remove fuel/gearbox words
    s = FUEL_WORDS_RE.sub("", s)
    s = GEARBOX_WORDS_RE.sub("", s)

    s = _norm_spaces(s)

    # common formats -> normalize
    # "Curitiba , PR" -> "Curitiba-PR"
    s = re.sub(r"\s*,\s*", ", ", s)
    s = re.sub(r"\s*-\s*", "-", s)

    # Try extract "City - UF" or "City, UF" at end
    m = re.search(r"([A-Za-zÀ-ÿ\s'.]+?)[,\-]\s*([A-Z]{2})\b", s)
    if m:
        city = _norm_spaces(m.group(1))
        uf = m.group(2).upper()
        return f"{city}-{uf}"

    # If already "City-UF"
    m2 = re.search(r"([A-Za-zÀ-ÿ\s'.]+)\s*-\s*([A-Z]{2})\b", s)
    if m2:
        city = _norm_spaces(m2.group(1))
        uf = m2.group(2).upper()
        return f"{city}-{uf}"

    return _strip_trailing_punct(s)


def listing_fields_for_telegram(listing: Any) -> Dict[str, Optional[str]]:
    """
    Extract normalized fields for display in Telegram messages from either:
      - SQLAlchemy model (attributes)
      - dict-like object
    """
    def get(k: str) -> Optional[str]:
        if isinstance(listing, dict):
            v = listing.get(k)
        else:
            v = getattr(listing, k, None)
        return None if v is None else str(v)

    title = get("title") or ""
    location = get("location") or ""
    year = get("year")
    price = get("price")
    url = get("url")
    score = get("score")

    # Build normalized
    km = get("km")
    if not km:
        km = _extract_km(title) or _extract_km(location)

    title_clean = clean_title_remove_fuel_gearbox(title)
    location_clean = normalize_location(location)

    return {
        "title": title_clean or title,
        "year": year,
        "km": km,
        "price": price,
        "location": location_clean or location,
        "score": score,
        "url": url,
    }


def format_listing_message_telegram(listing: Any) -> str:
    """
    Telegram message body with KM on separate line and cleaned title/location.
    """
    f = listing_fields_for_telegram(listing)

    lines = []
    if f["title"]:
        lines.append(f["title"])

    if f["year"]:
        lines.append(f"Ano: {f['year']}")

    if f["km"]:
        lines.append(f"KM: {f['km']}")

    if f["price"]:
        lines.append(f"Preço: {f['price']}")

    if f["location"]:
        lines.append(f"Local: {f['location']}")

    if f["score"] not in (None, "", "None"):
        lines.append(f"Score: {f['score']}/100")

    if f["url"]:
        lines.append(f["url"])

    return "\n".join(lines)
