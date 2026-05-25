from __future__ import annotations

import hashlib
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import distinct, func
from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.notification import Notification

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


def evaluate_cross_source_notification_dedupe(
    db: Session,
    *,
    user_id,
    wishlist_id,
    listing,
    window_days: int = 30,
) -> dict[str, Any]:
    out = {
        "should_suppress": False,
        "reason": None,
        "fingerprint": getattr(listing, "cross_source_fingerprint", None),
        "matched_notification_id": None,
        "matched_listing_id": None,
        "matched_source": None,
        "current_source": getattr(listing, "source", None),
    }
    fp = out["fingerprint"]
    if not fp:
        out["reason"] = "missing_fingerprint"
        return out

    now = datetime.now(timezone.utc)
    window_start = now - timedelta(days=max(1, int(window_days or 30)))
    rows = (
        db.query(Notification, CarListing)
        .join(CarListing, CarListing.id == Notification.car_listing_id)
        .filter(Notification.user_id == user_id)
        .filter(Notification.wishlist_id == wishlist_id)
        .filter(Notification.status.in_(("queued", "processing", "sent")))
        .filter(Notification.created_at >= window_start)
        .filter(CarListing.cross_source_fingerprint == fp)
        .all()
    )
    if not rows:
        out["reason"] = "no_recent_match"
        return out

    current_source = str(getattr(listing, "source", "") or "").strip().lower()
    cross_source_rows = [
        (n, l) for (n, l) in rows if str(getattr(l, "source", "") or "").strip().lower() != current_source
    ]
    if not cross_source_rows:
        out["reason"] = "same_source_only"
        return out
    if len(cross_source_rows) > 1:
        out["reason"] = "ambiguous_multiple_matches"
        return out

    n, l = cross_source_rows[0]
    out["should_suppress"] = True
    out["reason"] = "cross_source_duplicate_recent_notification"
    out["matched_notification_id"] = str(n.id)
    out["matched_listing_id"] = str(l.id)
    out["matched_source"] = l.source
    return out
