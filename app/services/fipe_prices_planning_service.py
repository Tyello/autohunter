from __future__ import annotations

from collections import Counter
from decimal import Decimal

from sqlalchemy.orm import Session

from app.models.car_listing import CarListing
from app.models.fipe_price import FipePrice
from app.services.fipe_catalog_resolver_service import resolve_listing_to_fipe_candidates
from app.services.fipe_monthly_sync_service import normalize_fipe_month
from app.services.fipe_service import listing_vehicle_keys


SKIPPED_REASONS = (
    "insufficient_data",
    "no_match",
    "ambiguous",
    "below_confidence",
    "missing_price",
    "missing_vehicle_key",
    "already_exists",
    "already_planned",
)


def _to_int_price(value) -> int | None:
    if value is None:
        return None
    try:
        dec = Decimal(str(value))
    except Exception:
        return None
    if dec <= 0:
        return None
    return int(dec)


def build_fipe_price_plan_for_listing(db: Session, *, listing, reference_month: str, min_confidence: int = 80) -> dict:
    month = normalize_fipe_month(reference_month)
    keys = listing_vehicle_keys(listing)
    if not keys:
        return {"status": "skipped", "reason": "missing_vehicle_key"}

    result = resolve_listing_to_fipe_candidates(db, listing=listing, reference_month=month, limit=10)
    status = result.get("status")
    if status in ("insufficient_data", "no_match", "ambiguous"):
        return {"status": "skipped", "reason": status}

    best = result.get("best_candidate") or {}
    if not best:
        return {"status": "skipped", "reason": "no_match"}

    confidence_label = (best.get("confidence_label") or "").strip().lower()
    confidence_score = int(best.get("confidence_score") or 0)
    if confidence_label != "high" or confidence_score < int(min_confidence):
        return {"status": "skipped", "reason": "below_confidence"}

    price = _to_int_price(best.get("price"))
    if not price:
        return {"status": "skipped", "reason": "missing_price"}

    vehicle_key = keys[0]
    existing = (
        db.query(FipePrice)
        .filter(FipePrice.vehicle_key == vehicle_key)
        .filter(FipePrice.reference_month == month)
        .first()
    )
    if existing:
        out = {
            "status": "skipped",
            "reason": "already_exists",
            "existing_fipe_price": int(existing.fipe_price),
        }
        if int(existing.fipe_price) != price:
            out["would_update"] = {
                "vehicle_key": vehicle_key,
                "reference_month": month,
                "current_fipe_price": int(existing.fipe_price),
                "planned_fipe_price": price,
                "currency": (existing.currency or "BRL").upper(),
            }
        return out

    planned = {
        "listing_id": str(getattr(listing, "id", "")),
        "vehicle_key": vehicle_key,
        "candidate_vehicle_keys": keys,
        "reference_month": month,
        "fipe_price": price,
        "currency": (best.get("currency") or "BRL").upper(),
        "source": "fipe_catalog_resolver",
        "catalog_entry_id": str(best.get("catalog_entry_id") or ""),
        "fipe_code": best.get("fipe_code"),
        "confidence_score": confidence_score,
        "confidence_label": confidence_label,
        "model_name": best.get("model_name"),
        "reasons": best.get("reasons") or [],
        "warnings": best.get("warnings") or [],
    }
    return {"status": "planned", "item": planned}


def build_fipe_price_plan(db: Session, *, reference_month: str, limit: int = 100, min_confidence: int = 80) -> dict:
    month = normalize_fipe_month(reference_month)
    size = max(1, min(500, int(limit)))
    listings = (
        db.query(CarListing)
        .order_by(CarListing.created_at.desc())
        .limit(size)
        .all()
    )

    skipped_counts = Counter({k: 0 for k in SKIPPED_REASONS})
    planned_inserts = []
    planned_keys = set()
    would_updates = []
    examples_skipped = []

    for listing in listings:
        row = build_fipe_price_plan_for_listing(
            db,
            listing=listing,
            reference_month=month,
            min_confidence=min_confidence,
        )
        if row.get("status") == "planned":
            item = row["item"]
            planned_key = (item.get("vehicle_key"), item.get("reference_month"))
            if planned_key in planned_keys:
                reason = "already_planned"
                skipped_counts[reason] += 1
                if len(examples_skipped) < 20:
                    examples_skipped.append(
                        {
                            "listing_id": str(getattr(listing, "id", "")),
                            "reason": reason,
                        }
                    )
                continue
            planned_keys.add(planned_key)
            planned_inserts.append(item)
            continue
        reason = row.get("reason") or "no_match"
        skipped_counts[reason] += 1
        if row.get("would_update"):
            would_updates.append(row["would_update"])
        if len(examples_skipped) < 20:
            examples_skipped.append(
                {
                    "listing_id": str(getattr(listing, "id", "")),
                    "reason": reason,
                }
            )

    return {
        "reference_month": month,
        "sample_size": len(listings),
        "planned_inserts_count": len(planned_inserts),
        "would_update_count": len(would_updates),
        "already_exists_count": skipped_counts["already_exists"],
        "skipped_counts": dict(skipped_counts),
        "planned_inserts": planned_inserts,
        "would_updates": would_updates,
        "examples_skipped": examples_skipped,
    }
