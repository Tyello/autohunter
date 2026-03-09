from __future__ import annotations

import hashlib
import re
from typing import Any

from app.common.price_parser import parse_price_int_reais
from app.scrapers.framework import canonicalize_url
from app.sources.contract import NormalizedAd
from app.sources.media import derive_thumbnail_url, normalize_image_urls

_UF_RE = re.compile(r"\b([A-Z]{2})\b")
_NUM_RE = re.compile(r"\d+")
_PRICE_RE = re.compile(r"\d+[\d.,]*")
_PREFIX_LOCATION_RE = re.compile(r"^\s*em\s+", re.I)
_MAKE_RE = re.compile(r"^([A-Za-zÀ-ÿ0-9]+)\s+(.+)$")
_PRICE_ID_RE = re.compile(r"^\d{4,}$")

_FUEL_MAP = {
    "gasolina": "Gasolina",
    "flex": "Flex",
    "diesel": "Diesel",
    "hibrido": "Híbrido",
    "híbrido": "Híbrido",
    "eletrico": "Elétrico",
    "elétrico": "Elétrico",
}

_TRANSMISSION_MAP = {
    "automatica": "Automática",
    "automatica": "Automática",
    "cambio automatico": "Automática",
    "câmbio automático": "Automática",
    "manual": "Manual",
    "cvt": "CVT",
    "automatizada": "Automatizada",
    "semi-automatica": "Semi-automática",
    "semi automática": "Semi-automática",
}

_STATE_NAME_TO_UF = {
    "sao paulo": "SP",
    "rio de janeiro": "RJ",
    "minas gerais": "MG",
    "parana": "PR",
    "rio grande do sul": "RS",
    "santa catarina": "SC",
    "bahia": "BA",
    "goias": "GO",
    "pernambuco": "PE",
    "ceara": "CE",
}

_CANONICAL_FUEL_TYPES = {"gasoline", "ethanol", "flex", "diesel", "electric", "hybrid"}
_CANONICAL_TRANSMISSIONS = {"manual", "automatic", "cvt", "automated", "semi_automatic"}
_CANONICAL_SELLER_TYPES = {"dealer", "private", "unknown"}
_CANONICAL_LISTING_TYPES = {"marketplace", "auction_lot", "classified"}


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


def normalize_mileage_km(value: Any) -> int | None:
    return _norm_int(value)


def _norm_token(value: str | None) -> str:
    if not value:
        return ""
    return re.sub(r"\s+", " ", value.strip().lower())


def normalize_fuel_type(value: Any) -> str | None:
    token = _norm_token(_norm_str(value)).replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    if token in _CANONICAL_FUEL_TYPES:
        return token
    if "hibr" in token:
        return "hybrid"
    if "eletr" in token:
        return "electric"
    for k, v in _FUEL_MAP.items():
        if k in token:
            return {
                "Gasolina": "gasoline",
                "Flex": "flex",
                "Diesel": "diesel",
                "Híbrido": "hybrid",
                "Elétrico": "electric",
            }.get(v)
    return None


def normalize_transmission(value: Any) -> str | None:
    raw = _norm_str(value)
    token = _norm_token(raw).replace("â", "a").replace("á", "a")
    if token in _CANONICAL_TRANSMISSIONS:
        return token
    if "cvt" in token:
        return "cvt"
    if "semi" in token:
        return "semi_automatic"
    if "automatiz" in token:
        return "automated"
    if "automatic" in token or "cambio automatico" in token or "câmbio automático" in (raw or "").lower():
        return "automatic"
    if "manual" in token:
        return "manual"
    return None


def normalize_seller_type(value: Any) -> str:
    token = _norm_token(_norm_str(value))
    if token in _CANONICAL_SELLER_TYPES:
        return token
    if token in {"loja", "concessionaria", "concessionária", "dealer"}:
        return "dealer"
    if token in {"particular", "owner", "private"}:
        return "private"
    return "unknown"


def normalize_listing_type(value: Any) -> str:
    token = _norm_token(_norm_str(value))
    return token if token in _CANONICAL_LISTING_TYPES else "marketplace"


def normalize_color(value: Any) -> str | None:
    txt = _norm_str(value)
    if not txt:
        return None
    return txt[:1].upper() + txt[1:].lower()


def normalize_location(location: Any, city: Any = None, state: Any = None) -> tuple[str | None, str | None, str | None]:
    loc = _norm_str(location)
    loc = _PREFIX_LOCATION_RE.sub("", loc or "") if loc else None
    c = _norm_str(city)
    st = _norm_str(state)

    parts = [p.strip() for p in re.split(r"[-/,]", loc or "") if p.strip()]
    if not c and parts:
        c = parts[0]

    if not st and len(parts) > 1:
        last = parts[-1]
        m = _UF_RE.search(last.upper())
        if m:
            st = m.group(1)
        else:
            key = _norm_token(last).replace("ã", "a")
            st = _STATE_NAME_TO_UF.get(key, st)

    if st:
        st = st.upper()
        if len(st) != 2:
            st = None

    formatted = None
    if c and st:
        formatted = f"{c}-{st}"
    elif loc:
        formatted = loc

    return formatted, c, st


def split_make_model_version(make: Any, model: Any, title: Any) -> tuple[str | None, str | None, str | None]:
    mk = _norm_str(make)
    md = _norm_str(model)
    tt = _norm_str(title)

    if mk and md and tt:
        prefix = f"{mk} {md}".strip().lower()
        if tt.lower().startswith(prefix):
            version = tt[len(prefix):].strip() or None
            return mk, md, version

    if tt:
        m = _MAKE_RE.match(tt)
        if m:
            mk = mk or m.group(1)
            rest = m.group(2).strip()
            first, *tail = rest.split(" ", 1)
            md = md or first
            version = tail[0].strip() if tail else None
            return mk, md, version

    return mk, md, None


def resolve_thumbnail_url(explicit_thumbnail: Any, images: Any) -> str | None:
    return derive_thumbnail_url(explicit_thumbnail, images)


def normalize_external_id(*, source: str, raw_external_id: Any, url: str | None, title: Any, price: Any) -> str | None:
    candidate = _norm_str(raw_external_id)
    if candidate and _PRICE_ID_RE.match(candidate):
        try:
            if parse_price_int_reais(candidate) == parse_price_int_reais(price):
                candidate = None
        except Exception:
            pass
    if candidate:
        return candidate

    canonical = canonicalize_url(_norm_str(url) or "") or _norm_str(url)
    basis = canonical or _norm_str(title)
    if not basis:
        return None
    digest = hashlib.sha1(f"{source}|{basis}".encode("utf-8")).hexdigest()[:16]
    return digest


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
    url = canonicalize_url(_norm_str(data.get("url")) or "")
    price = _norm_price(pick("price"))
    external_id = normalize_external_id(
        source=source_name,
        raw_external_id=pick("external_id", "source_listing_id", "id"),
        url=url,
        title=pick("title"),
        price=pick("price"),
    )

    mileage_km = normalize_mileage_km(pick("km", "mileage_km", "mileage"))
    year = _norm_year(pick("year", "year_model", "ano"))
    location, city, state = normalize_location(pick("location"), pick("city"), pick("uf", "state"))
    make, model, version = split_make_model_version(pick("make", "brand"), pick("model"), pick("title"))

    images = pick("images", "photos", "image_urls")
    explicit_thumbnail = pick("thumbnail_url", "thumbnail", "image_url", "image")
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

    thumb_url = resolve_thumbnail_url(explicit_thumbnail, image_urls if image_urls is not None else images)

    known = {
        "source", "source_listing_id", "external_id", "id", "url", "title", "price", "currency",
        "city", "uf", "state", "location", "year", "year_model", "ano", "km", "mileage_km", "mileage",
        "make", "brand", "model", "version", "images", "photos", "image_urls", "images_count", "thumbnail_url", "thumbnail", "image_url", "image",
        "gearbox", "transmission", "cambio", "fuel_type", "seller_type", "color", "raw_payload", "extractor_version", "extras",
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

    raw_payload = pick("raw_payload")
    if raw_payload is None:
        raw_payload = {
            "source": source_name,
            "external_id": external_id,
            "url": url,
            "title": _norm_str(pick("title")),
        }
    elif isinstance(raw_payload, str):
        raw_payload = {"raw": raw_payload[:2000]}

    extractor_version = _norm_str(pick("extractor_version")) or "normalize_ad_v2"

    return NormalizedAd(
        source=source_name,
        external_id=external_id,
        url=url,
        title=_norm_str(pick("title")),
        price=price,
        currency=(_norm_str(pick("currency")) or "BRL").upper(),
        city=city,
        uf=state,
        year=year,
        km=mileage_km,
        make=make,
        model=model,
        images_count=images_count,
        quality_flags=tuple(),
        extras={
            **extras,
            "location": location,
            "fuel_type": normalize_fuel_type(pick("fuel_type")),
            "transmission": normalize_transmission(pick("gearbox", "transmission", "cambio")),
            "version": version,
            "seller_type": normalize_seller_type(pick("seller_type")),
            "listing_type": normalize_listing_type(pick("listing_type")),
            "color": normalize_color(pick("color")),
            "extractor_version": extractor_version,
            "raw_payload": raw_payload,
        },
    )


def normalize_many(source: str, items: list[dict[str, Any]]) -> list[NormalizedAd]:
    out: list[NormalizedAd] = []
    for raw in items or []:
        if not isinstance(raw, dict):
            continue
        out.append(normalize_ad(source, raw))
    return out
