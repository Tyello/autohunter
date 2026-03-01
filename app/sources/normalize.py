from __future__ import annotations

import re
from typing import Any

from app.scrapers.framework import canonicalize_url
from app.sources.contract import NormalizedAd

_UF_RE = re.compile(r"\b([A-Z]{2})\b")
_NUM_RE = re.compile(r"\d+")
_PRICE_RE = re.compile(r"\d+[\d.,]*")


def _norm_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _norm_price(value: Any) -> int | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        v = int(value)
        return v if v > 0 else None

    s = str(value)
    m = _PRICE_RE.search(s.replace(" ", ""))
    if not m:
        return None
    token = m.group(0)
    if "," in token and "." in token:
        token = token.replace(".", "").replace(",", ".")
    elif "," in token:
        token = token.replace(",", ".")
    else:
        token = token.replace(".", "")
    try:
        out = int(float(token))
    except Exception:
        return None
    return out if out > 0 else None


def _norm_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    token = str(value).lower().replace("km", "").strip()
    token = token.replace(".", "").replace(",", "")
    m = _NUM_RE.search(token)
    return int(m.group(0)) if m else None


def _norm_year(value: Any) -> int | None:
    year = _norm_int(value)
    if year is None:
        return None
    return year if 1900 <= year <= 2100 else None


def _split_city_uf(city: Any, uf: Any, location: Any) -> tuple[str | None, str | None]:
    c = _norm_str(city)
    u = _norm_str(uf)
    if u:
        u = u.upper()
    loc = _norm_str(location)

    if not c and loc:
        parts = [p.strip() for p in re.split(r"[-/,]", loc) if p.strip()]
        if parts:
            c = parts[0]
        if len(parts) > 1 and not u:
            m = _UF_RE.search(parts[-1].upper())
            if m:
                u = m.group(1)
    if u and len(u) != 2:
        u = None
    return c, u


def normalize_ad(source: str, raw: dict[str, Any]) -> NormalizedAd:
    data = raw or {}
    flags: list[str] = []

    source_name = (_norm_str(data.get("source")) or source or "").lower()
    source_listing_id = _norm_str(data.get("source_listing_id") or data.get("external_id") or data.get("id"))
    url = canonicalize_url(_norm_str(data.get("url")) or "")
    if not source_listing_id:
        flags.append("missing_source_listing_id")
    if not url:
        flags.append("missing_url")

    price = _norm_price(data.get("price"))
    if price is None:
        flags.append("missing_price")

    km = _norm_int(data.get("km") or data.get("mileage_km") or data.get("mileage"))
    if km is None:
        flags.append("missing_km")

    year = _norm_year(data.get("year") or data.get("year_model") or data.get("ano"))
    if year is None:
        flags.append("missing_year")

    city, uf = _split_city_uf(data.get("city"), data.get("uf"), data.get("location"))
    if city is None:
        flags.append("missing_city")
    if uf is None:
        flags.append("missing_uf")

    images = data.get("images") or data.get("photos")
    images_count = None
    if isinstance(images, list):
        images_count = len([x for x in images if x])
    elif data.get("images_count") is not None:
        images_count = _norm_int(data.get("images_count"))

    known = {
        "source", "source_listing_id", "external_id", "id", "url", "title", "price", "currency",
        "city", "uf", "location", "year", "year_model", "ano", "km", "mileage_km", "mileage",
        "make", "brand", "model", "images", "photos", "images_count",
    }
    extras = {k: v for k, v in data.items() if k not in known and v is not None}

    return NormalizedAd(
        source=source_name,
        source_listing_id=source_listing_id,
        url=url,
        title=_norm_str(data.get("title")),
        price=price,
        currency=(_norm_str(data.get("currency")) or "BRL").upper(),
        city=city,
        uf=uf,
        year=year,
        km=km,
        make=_norm_str(data.get("make") or data.get("brand")),
        model=_norm_str(data.get("model")),
        images_count=images_count,
        quality_flags=tuple(flags),
        extras=extras,
    )


def normalize_many(source: str, items: list[dict[str, Any]]) -> list[NormalizedAd]:
    out: list[NormalizedAd] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        out.append(normalize_ad(source, raw))
    return out
