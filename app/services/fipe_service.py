from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from sqlalchemy.orm import Session

from app.models.fipe_price import FipePrice


def get_fipe_price(db: Session, vehicle_key: str, reference_month: str) -> Optional[Decimal]:
    row = (
        db.query(FipePrice)
        .filter(FipePrice.vehicle_key == vehicle_key)
        .filter(FipePrice.reference_month == reference_month)
        .first()
    )
    return row.fipe_price if row else None


def listing_vehicle_keys(listing) -> list[str]:
    make = (getattr(listing, "make", None) or "").strip().lower()
    model = (getattr(listing, "model", None) or "").strip().lower()
    year = getattr(listing, "year", None)
    version = (getattr(listing, "version", None) or "").strip().lower()
    transmission = (getattr(listing, "transmission", None) or "").strip().lower()
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
