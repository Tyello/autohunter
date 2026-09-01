import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session

from app.models.fipe_price import FipePrice


def _normalize_key_token(value: str) -> str:
    """Canonicaliza um pedaço de vehicle_key para tolerar variações triviais
    de formatação entre fontes (espaços ao redor de '/', pontuação solta)."""
    v = (value or "").strip().lower()
    v = re.sub(r"\s*/\s*", "/", v)
    # Remove pontuação solta (ex: "Mec." -> "mec") mas preserva casas
    # decimais como "1.5" (não remove "." entre dígitos).
    v = re.sub(r"(?<!\d)[.,](?!\d)", "", v)
    v = re.sub(r"\s+", " ", v).strip()
    return v


def listing_vehicle_keys(listing) -> list[str]:
    make = _normalize_key_token(getattr(listing, "make", None) or "")
    model = _normalize_key_token(getattr(listing, "model", None) or "")
    year = getattr(listing, "year", None)
    version = _normalize_key_token(getattr(listing, "version", None) or "")
    transmission = _normalize_key_token(getattr(listing, "transmission", None) or "")
    if not make or not model or year is None:
        return []
    try:
        y = int(year)
    except Exception:
        return []

    keys = [f"{make}|{model}|{y}"]
    if version:
        keys.insert(0, f"{make}|{model}|{version}|{y}")
    if transmission:
        keys.append(f"{make}|{model}|{transmission}|{y}")
    return keys


def current_reference_month(*, now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    return dt.strftime("%Y-%m")
