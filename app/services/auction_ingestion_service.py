from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.services.auction_lot_service import upsert_lot
from app.sources.auctions.copart import fetch_copart_lots, get_last_reason as copart_reason
from app.sources.auctions.vip import fetch_vip_lots, get_last_reason as vip_reason

SUPPORTED_SOURCES = {"copart_auctions", "vip_auctions"}


def run_auction_ingestion(source: str, limit: int, enrich_details: bool = False) -> dict[str, Any]:
    if source not in SUPPORTED_SOURCES:
        raise ValueError(f"Unsupported source: {source}. Available: {', '.join(sorted(SUPPORTED_SOURCES))}")

    if source == "copart_auctions":
        lots = fetch_copart_lots(limit=limit)
        reason = copart_reason()
    else:
        lots = fetch_vip_lots(limit=limit, enrich=enrich_details)
        reason = vip_reason()

    summary: dict[str, Any] = {
        "source": source,
        "fetched": len(lots),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "reason": reason if not lots else None,
    }

    db = SessionLocal()
    try:
        for lot in lots:
            _, created = upsert_lot(db, lot.to_payload())
            if created:
                summary["inserted"] += 1
            else:
                summary["updated"] += 1
        db.commit()
        return summary
    except Exception:
        db.rollback()
        summary["errors"] += 1
        raise
    finally:
        db.close()
