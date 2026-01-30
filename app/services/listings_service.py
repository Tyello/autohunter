from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy.orm import Session

from app.repositories.car_listings_repo import insert_ignore_duplicates_return_ids


# car_listings.price is NUMERIC(12,2): absolute value must be < 10^10.
_MAX_DB_PRICE = Decimal("9999999999.99")


def _sanitize_price(v: Any) -> Decimal | None:
    """Hard guard to prevent DB numeric overflows.

    Scrapers are best-effort; if they mis-parse a long digit sequence, we must
    not allow a single bad listing to kill the whole bulk upsert.
    """
    if v is None:
        return None

    try:
        if isinstance(v, Decimal):
            d = v
        elif isinstance(v, (int, float)):
            d = Decimal(str(v))
        elif isinstance(v, str):
            # strings should already be parsed upstream, but be defensive.
            vv = v.strip()
            if not vv:
                return None
            # keep only digits and separators
            vv = "".join(ch for ch in vv if ch.isdigit() or ch in ".,")
            vv = vv.replace(".", "").replace(",", ".")
            d = Decimal(vv)
        else:
            return None
    except (InvalidOperation, ValueError):
        return None

    if not d.is_finite() or d <= 0 or d > _MAX_DB_PRICE:
        return None
    try:
        return d.quantize(Decimal("0.01"))
    except Exception:
        return d


def _sanitize_listings(listings: list[dict]) -> list[dict]:
    out: list[dict] = []
    for l in listings or []:
        if not isinstance(l, dict):
            continue
        ll = dict(l)
        if "price" in ll:
            ll["price"] = _sanitize_price(ll.get("price"))
        out.append(ll)
    return out

def ingest_listings(db: Session, listings: list[dict]):
    if not listings:
        return []

    listings = _sanitize_listings(listings)
    inserted_ids = insert_ignore_duplicates_return_ids(db, listings)
    return list(inserted_ids or [])
