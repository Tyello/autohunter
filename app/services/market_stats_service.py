from __future__ import annotations

from decimal import Decimal
from typing import Iterable

from sqlalchemy.orm import Session
from sqlalchemy import tuple_

from app.models.market_stats import MarketStatsCohort
from app.scoring.types import MarketStats


def cohort_key_for_listing(listing) -> tuple[str, str, int] | None:
    make = getattr(listing, "make", None)
    model = getattr(listing, "model", None)
    year = getattr(listing, "year", None)

    if not make or not model or year is None:
        return None

    try:
        y = int(year)
    except Exception:
        return None

    mk = str(make).strip().lower()
    md = str(model).strip().lower()
    if not mk or not md:
        return None

    return (mk, md, y)


def _row_to_stats(row: MarketStatsCohort) -> MarketStats:
    return MarketStats(
        make=str(row.make),
        model=str(row.model),
        year=int(row.year),
        median_price=Decimal(str(row.median_price)),
        p25_price=Decimal(str(row.p25_price)) if row.p25_price is not None else None,
        p75_price=Decimal(str(row.p75_price)) if row.p75_price is not None else None,
        sample_size=int(row.sample_size or 0),
    )


def get_market_stats(db: Session, listing) -> MarketStats | None:
    k = cohort_key_for_listing(listing)
    if not k:
        return None
    mk, md, y = k
    row = (
        db.query(MarketStatsCohort)
        .filter(MarketStatsCohort.make == mk)
        .filter(MarketStatsCohort.model == md)
        .filter(MarketStatsCohort.year == y)
        .one_or_none()
    )
    return _row_to_stats(row) if row else None


def batch_get_market_stats(db: Session, listings: Iterable) -> dict[tuple[str, str, int], MarketStats]:
    """Fetch MarketStats for many listings with 1 query."""
    keys: list[tuple[str, str, int]] = []
    seen: set[tuple[str, str, int]] = set()

    for l in (listings or []):
        k = cohort_key_for_listing(l)
        if not k or k in seen:
            continue
        seen.add(k)
        keys.append(k)

    if not keys:
        return {}

    rows = (
        db.query(MarketStatsCohort)
        .filter(tuple_(MarketStatsCohort.make, MarketStatsCohort.model, MarketStatsCohort.year).in_(keys))
        .all()
    )

    out: dict[tuple[str, str, int], MarketStats] = {}
    for r in rows or []:
        k = (str(r.make), str(r.model), int(r.year))
        out[k] = _row_to_stats(r)

    return out
