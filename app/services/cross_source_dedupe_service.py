from __future__ import annotations

import hashlib
import re
from typing import Any

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing

PRICE_BUCKET = 1000
MILEAGE_BUCKET = 5000


def _norm_text(value: Any) -> str | None:
    if value is None:
        return None
    s = re.sub(r"\s+", " ", str(value).strip().lower())
    if not s:
        return None
    return re.sub(r"[^a-z0-9 ]+", "", s) or None


def _norm_int(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except Exception:
        return None


def _bucket(value: int | None, size: int) -> int | None:
    if value is None or value < 0:
        return None
    return (value // size) * size


def _read_field(listing: dict | CarListing, field: str) -> Any:
    if isinstance(listing, dict):
        return listing.get(field)
    return getattr(listing, field, None)


def compute_cross_source_fingerprint(listing: dict | CarListing) -> str | None:
    make = _norm_text(_read_field(listing, "make"))
    model = _norm_text(_read_field(listing, "model"))
    year = _norm_int(_read_field(listing, "year"))

    if not make or not model or year is None:
        return None

    price_bucket = _bucket(_norm_int(_read_field(listing, "price")), PRICE_BUCKET)
    mileage_bucket = _bucket(_norm_int(_read_field(listing, "mileage_km")), MILEAGE_BUCKET)

    if price_bucket is None and mileage_bucket is None:
        return None

    version = _norm_text(_read_field(listing, "version"))
    transmission = _norm_text(_read_field(listing, "transmission"))

    key = "|".join(
        [
            f"make:{make}",
            f"model:{model}",
            f"year:{year}",
            f"p:{price_bucket if price_bucket is not None else 'na'}",
            f"km:{mileage_bucket if mileage_bucket is not None else 'na'}",
            f"v:{version or 'na'}",
            f"t:{transmission or 'na'}",
        ]
    )
    return hashlib.sha256(key.encode("utf-8")).hexdigest()[:24]


def find_cross_source_fingerprint_collisions(db: Session, limit: int = 20) -> list[dict[str, Any]]:
    grouped = (
        db.query(
            CarListing.cross_source_fingerprint.label("fingerprint"),
            func.count(CarListing.id).label("listing_count"),
            func.count(distinct(CarListing.source)).label("source_count"),
        )
        .filter(CarListing.cross_source_fingerprint.isnot(None))
        .group_by(CarListing.cross_source_fingerprint)
        .having(func.count(distinct(CarListing.source)) > 1)
        .order_by(func.count(CarListing.id).desc())
        .limit(max(1, int(limit)))
        .all()
    )

    out: list[dict[str, Any]] = []
    for row in grouped:
        fp = row.fingerprint
        rows = (
            db.query(CarListing)
            .filter(CarListing.cross_source_fingerprint == fp)
            .order_by(CarListing.updated_at.desc())
            .limit(8)
            .all()
        )
        sources = sorted({str(r.source) for r in rows if r.source})
        examples = [
            {
                "id": str(r.id),
                "source": r.source,
                "title": r.title,
                "year": r.year,
                "price": float(r.price) if r.price is not None else None,
                "mileage_km": r.mileage_km,
                "url": r.url,
            }
            for r in rows
        ]
        out.append(
            {
                "fingerprint": fp,
                "listing_count": int(row.listing_count or 0),
                "source_count": int(row.source_count or 0),
                "sources": sources,
                "examples": examples,
            }
        )
    return out
