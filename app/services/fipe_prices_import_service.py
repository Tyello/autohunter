from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.fipe_price import FipePrice
from app.services.fipe_service import current_reference_month, listing_vehicle_keys

_REF_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def normalize_fipe_vehicle_key(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip().lower())


def _parse_reference_month(value: str | None, fallback: str) -> str | None:
    candidate = (value or fallback or "").strip()
    if not _REF_MONTH_RE.match(candidate):
        return None
    return candidate


def _parse_price(value) -> Decimal | None:
    try:
        price = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, AttributeError):
        return None
    if price <= 0:
        return None
    return price


def upsert_fipe_prices(db: Session, rows: list[dict], *, reference_month: str | None = None, dry_run: bool = False) -> dict:
    default_month = _parse_reference_month(reference_month, current_reference_month())
    if default_month is None:
        raise ValueError("reference_month inválido; esperado YYYY-MM")

    counters = {"total": len(rows or []), "valid": 0, "inserted": 0, "updated": 0, "skipped_invalid": 0, "dry_run": bool(dry_run)}
    for row in rows or []:
        key = normalize_fipe_vehicle_key((row or {}).get("vehicle_key"))
        month = _parse_reference_month((row or {}).get("reference_month"), default_month)
        price = _parse_price((row or {}).get("fipe_price"))
        currency = str((row or {}).get("currency") or "BRL").strip().upper() or "BRL"
        if not key or month is None or price is None:
            counters["skipped_invalid"] += 1
            continue
        counters["valid"] += 1
        existing = db.query(FipePrice).filter(FipePrice.vehicle_key == key, FipePrice.reference_month == month).first()
        if existing:
            counters["updated"] += 1
            if not dry_run:
                existing.fipe_price = price
                existing.currency = currency
        else:
            counters["inserted"] += 1
            if not dry_run:
                db.add(FipePrice(vehicle_key=key, fipe_price=price, reference_month=month, currency=currency))

    if not dry_run:
        db.commit()
    return counters


def build_fipe_coverage_report(db: Session, *, reference_month: str | None = None, limit: int = 20) -> dict:
    month = _parse_reference_month(reference_month, current_reference_month())
    if month is None:
        raise ValueError("reference_month inválido; esperado YYYY-MM")
    limit = max(1, min(50, int(limit)))

    key_counts: Counter[str] = Counter()
    listings_with_key = 0
    for listing in db.query(CarListing).all():
        keys = [normalize_fipe_vehicle_key(k) for k in listing_vehicle_keys(listing) if normalize_fipe_vehicle_key(k)]
        if keys:
            listings_with_key += 1
            for key in set(keys):
                key_counts[key] += 1

    unique_keys = set(key_counts.keys())
    covered_rows = db.query(FipePrice.vehicle_key).filter(FipePrice.reference_month == month, FipePrice.vehicle_key.in_(list(unique_keys) or ["__none__"])).all()
    covered_keys = {normalize_fipe_vehicle_key(row[0]) for row in covered_rows}

    missing = [(k, c) for k, c in key_counts.most_common() if k not in covered_keys]
    covered = [k for k in key_counts.keys() if k in covered_keys]
    coverage_pct = round((len(covered_keys) / len(unique_keys) * 100.0), 2) if unique_keys else 0.0

    return {
        "reference_month": month,
        "listings_with_fipe_keys": listings_with_key,
        "vehicle_keys_distinct": len(unique_keys),
        "vehicle_keys_covered": len(covered_keys),
        "coverage_pct": coverage_pct,
        "examples_missing": [k for k, _ in missing[:limit]],
        "examples_covered": covered[:limit],
        "top_missing_keys": [{"vehicle_key": k, "count": c} for k, c in missing[:limit]],
    }
