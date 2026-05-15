from __future__ import annotations

from typing import Any

from app.db.session import SessionLocal
from app.services.auction_lot_service import upsert_lot
from app.sources.auctions.registry import (
    get_auction_source_definition,
    list_supported_auction_source_keys,
    render_supported_auction_sources_hint,
)

SUPPORTED_SOURCES = list_supported_auction_source_keys()


def run_auction_ingestion(source: str, limit: int, enrich_details: bool = False) -> dict[str, Any]:
    definition = get_auction_source_definition(source)
    if definition is None:
        raise ValueError(f"Unsupported source: {source}. {render_supported_auction_sources_hint()}")

    source = definition.key
    enrich_applied = bool(enrich_details and definition.supports_enrich)
    if definition.supports_enrich:
        lots = definition.fetcher(limit=limit, enrich=enrich_applied)
    else:
        lots = definition.fetcher(limit=limit)
    reason = definition.reason_getter()

    summary: dict[str, Any] = {
        "source": source,
        "fetched": len(lots),
        "inserted": 0,
        "updated": 0,
        "skipped": 0,
        "errors": 0,
        "reason": reason if not lots else None,
        "enrich_applied": enrich_applied,
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
