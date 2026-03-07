from __future__ import annotations

import re
from typing import Any

from app.common.price_parser import parse_price_int_reais
from app.scrapers.framework import canonicalize_url
from app.sources.contract import NormalizedAd
from app.sources.media import derive_thumbnail_url, normalize_image_urls

_UF_RE = re.compile(r"\b([A-Z]{2})\b")
_NUM_RE = re.compile(r"\d+")
_PRICE_RE = re.compile(r"\d+[\d.,]*")


def _norm_str(value: Any) -> str | None:
    if value is None:
        return None
    s = str(value).strip()
    return s or None


def _norm_price(value: Any) -> int | None:
    if isinstance(value, str):
        m = _PRICE_RE.search(value.replace(" ", ""))
        if not m:
            return None
        return parse_price_int_reais(m.group(0))
    return parse_price_int_reais(value)


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
    base_extras = dict(data.get("extras") or {}) if isinstance(data.get("extras"), dict) else {}

    def pick(*keys: str):
        for k in keys:
            if k in data and data.get(k) is not None:
                return data.get(k)
            if k in base_extras and base_extras.get(k) is not None:
                return base_extras.get(k)
        return None

    source_name = (_norm_str(data.get("source")) or source or "").lower()
    source_listing_id = _norm_str(pick("source_listing_id", "external_id", "id"))
    url = canonicalize_url(_norm_str(data.get("url")) or "")
    price = _norm_price(pick("price"))
    km = _norm_int(pick("km", "mileage_km", "mileage"))
    year = _norm_year(pick("year", "year_model", "ano"))
    city, uf = _split_city_uf(pick("city"), pick("uf"), pick("location"))
    images = pick("images", "photos", "image_urls")
    explicit_thumbnail = pick("thumbnail_url", "thumbnail", "image_url", "image")
    gearbox = _norm_str(pick("gearbox", "transmission", "cambio"))
    image_urls: list[str] | None = None
    thumb_url: str | None = None
    images_count = None
    duplicates = 0
    broken = 0
    if images is not None:
        image_urls, duplicates, broken = normalize_image_urls(images)
        images_count = len(image_urls)
    elif pick("images_count") is not None:
        images_count = _norm_int(pick("images_count"))

    thumb_url = derive_thumbnail_url(explicit_thumbnail, image_urls if image_urls is not None else images)

    known = {
        "source", "source_listing_id", "external_id", "id", "url", "title", "price", "currency",
        "city", "uf", "location", "year", "year_model", "ano", "km", "mileage_km", "mileage",
        "make", "brand", "model", "images", "photos", "image_urls", "images_count", "thumbnail_url", "thumbnail", "image_url", "image",
        "gearbox", "transmission", "cambio", "extras",
    }
    extras = {k: v for k, v in data.items() if k not in known and v is not None}
    for k, v in base_extras.items():
        if k in known or v is None:
            continue
        extras.setdefault(k, v)
    if image_urls is not None:
        extras["image_urls"] = image_urls
        if duplicates:
            extras["image_duplicates"] = duplicates
        if broken:
            extras["image_broken"] = broken
    if thumb_url is not None:
        extras["thumbnail_url"] = thumb_url
    if gearbox is not None:
        extras.setdefault("gearbox", gearbox)

    return NormalizedAd(
        source=source_name,
        source_listing_id=source_listing_id,
        url=url,
        title=_norm_str(pick("title")),
        price=price,
        currency=(_norm_str(pick("currency")) or "BRL").upper(),
        city=city,
        uf=uf,
        year=year,
        km=km,
        make=_norm_str(pick("make", "brand")),
        model=_norm_str(pick("model")),
        images_count=images_count,
        quality_flags=tuple(),
        extras=extras,
    )


def normalize_many(source: str, items: list[dict[str, Any]]) -> list[NormalizedAd]:
    out: list[NormalizedAd] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        out.append(normalize_ad(source, raw))
    return out
