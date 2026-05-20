from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models.source_run import SourceRun
from app.services.auction_quality_service import build_auction_quality_report


def build_auction_source_history(db: Session, source: str, limit: int = 8) -> dict[str, Any]:
    runs = (
        db.query(SourceRun)
        .filter(SourceRun.source == source, SourceRun.kind == "manual")
        .order_by(SourceRun.created_at.desc())
        .limit(max(1, int(limit or 8) * 3))
        .all()
    )
    cycles: list[dict[str, Any]] = []
    for row in runs:
        payload = row.payload if isinstance(row.payload, dict) else {}
        summary = payload.get("auction_summary") if isinstance(payload, dict) else None
        if not isinstance(summary, dict):
            continue
        cycles.append(
            {
                "at": row.created_at,
                "found": int(summary.get("found", 0) or 0),
                "inserted": int(summary.get("inserted", 0) or 0),
                "updated": int(summary.get("updated", 0) or 0),
                "ignored": int(summary.get("ignored", 0) or 0),
                "errors": int(summary.get("errors", 0) or 0),
                "car_lots": int(summary.get("car_lots", 0) or 0),
                "with_current_bid_count": int(summary.get("with_current_bid_count", 0) or 0),
                "with_initial_bid_count": int(summary.get("with_initial_bid_count", 0) or 0),
                "with_auction_start_at_count": int(summary.get("with_auction_start_at_count", 0) or 0),
                "with_auction_end_at_count": int(summary.get("with_auction_end_at_count", 0) or 0),
                "open_or_live_count": int(summary.get("open_or_live_count", 0) or 0),
                "score": summary.get("score"),
            }
        )
        if len(cycles) >= int(limit or 8):
            break

    quality = build_auction_quality_report(db, source=source)
    quality_sources = quality.get("sources") or []
    current_score = None
    if quality_sources:
        current_score = quality_sources[0].get("quality_score")
        for row in cycles:
            if row.get("score") is None:
                row["score"] = current_score

    return {"source": source, "current_score": current_score, "cycles": cycles}
