from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import and_
from sqlalchemy.orm import Session

from app.core.settings import settings
from app.models.system_log import SystemLog

SHADOW_HIT_MSG = "cross-source dedupe shadow hit"
SUPPRESSED_MSG = "cross-source dedupe suppressed"
ERROR_MSG = "cross-source dedupe evaluation error"
ALLOWED_MESSAGES = (SHADOW_HIT_MSG, SUPPRESSED_MSG, ERROR_MSG)


def _cap_hours(hours: int) -> int:
    value = 24 if hours is None else int(hours)
    return max(1, min(168, value))


def _cap_examples(limit: int) -> int:
    return max(1, min(50, int(limit or 20)))


def build_cross_source_dedupe_shadow_report(db: Session, *, hours: int = 24, limit: int = 20) -> dict[str, Any]:
    hours_capped = _cap_hours(hours)
    limit_capped = _cap_examples(limit)
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=hours_capped)

    rows = (
        db.query(SystemLog)
        .filter(
            and_(
                SystemLog.component == "notifications_queue",
                SystemLog.message.in_(ALLOWED_MESSAGES),
                SystemLog.created_at >= window_start,
            )
        )
        .order_by(SystemLog.created_at.desc())
        .limit(1000)
        .all()
    )

    fingerprints = Counter()
    source_pairs = Counter()
    wishlists = Counter()
    examples: list[dict[str, Any]] = []
    shadow_hit = 0
    suppressed = 0
    errors = 0

    for row in rows:
        payload = row.payload or {}
        if row.message == SHADOW_HIT_MSG:
            shadow_hit += 1
        elif row.message == SUPPRESSED_MSG:
            suppressed += 1
        elif row.message == ERROR_MSG:
            errors += 1

        fp = str(payload.get("fingerprint") or "").strip()
        if fp:
            fingerprints[fp] += 1

        current_source = str(payload.get("current_source") or "").strip()
        matched_source = str(payload.get("matched_source") or "").strip()
        if current_source or matched_source:
            source_pairs[(current_source or "-", matched_source or "-")] += 1

        wishlist_id = payload.get("wishlist_id")
        if wishlist_id:
            wishlists[str(wishlist_id)] += 1

        mode = str(payload.get("mode") or ("shadow" if row.message == SHADOW_HIT_MSG else "live" if row.message == SUPPRESSED_MSG else "error"))
        if len(examples) < limit_capped:
            examples.append(
                {
                    "current_listing_id": payload.get("current_listing_id"),
                    "matched_listing_id": payload.get("matched_listing_id"),
                    "current_source": payload.get("current_source"),
                    "matched_source": payload.get("matched_source"),
                    "fingerprint": payload.get("fingerprint"),
                    "user_id": payload.get("user_id"),
                    "wishlist_id": payload.get("wishlist_id"),
                    "created_at": row.created_at,
                    "mode": mode,
                }
            )

    return {
        "window_hours": hours_capped,
        "window_start": window_start,
        "window_end": now,
        "limit": limit_capped,
        "flags": {
            "enabled": bool(getattr(settings, "cross_source_dedupe_enabled", False)),
            "shadow_mode": bool(getattr(settings, "cross_source_dedupe_shadow_mode", True)),
            "window_days": int(getattr(settings, "cross_source_dedupe_window_days", 30) or 30),
        },
        "events": {
            "shadow_hit": shadow_hit,
            "live_suppressed": suppressed,
            "evaluation_error": errors,
        },
        "top_fingerprints": [{"fingerprint": fp, "count": cnt} for fp, cnt in fingerprints.most_common(10)],
        "top_source_pairs": [
            {"current_source": src_a, "matched_source": src_b, "count": cnt}
            for (src_a, src_b), cnt in source_pairs.most_common(10)
        ],
        "top_wishlists": [{"wishlist_id": wl, "count": cnt} for wl, cnt in wishlists.most_common(10)],
        "examples": examples,
    }
